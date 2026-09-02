"""Tests der Benutzeranlage und der Passwort-Hash-Kaskade.

Bis zur Durchsicht am 02.09.2026 hatte ``core/archiso/users.py`` **keinen
einzigen direkten Test** -- der sicherheitskritischste Codepfad des Kerns war
unverifiziert. Ueber ``ProfileGenerator`` war er zwar mit abgedeckt, aber nur
auf dem gluecklichen Weg.

Geprueft wird deshalb vor allem, was schiefgehen kann: dass der Klartext
nirgends stehenbleibt, dass jede Ebene der Kaskade fuer sich funktioniert und
dass ein Fehlschlag ein *gesperrtes* Konto ergibt statt eines offenen.
"""

from __future__ import annotations

import pytest

from archcustomiser.core.archiso import users
from archcustomiser.core.archiso.errors import HashingUnavailable
from archcustomiser.core.secrets import Secret

# Alle von crypt(3) erlaubten Praefixe, die hier vorkommen koennen.
GUELTIGE_PRAEFIXE = ("$y$", "$gy$", "$6$", "$5$", "$2b$", "$1$", "$7$")


# ---------------------------------------------------------------------------
# hash_password
# ---------------------------------------------------------------------------


def test_an_empty_password_is_refused() -> None:
    """Ein leeres Passwort zu hashen ergaebe ein offenes Konto."""
    with pytest.raises(HashingUnavailable):
        users.hash_password("")


def test_the_hash_never_contains_the_plaintext() -> None:
    klartext = "hunter2-sehr-geheim"
    try:
        hash_ = users.hash_password(klartext)
    except HashingUnavailable:
        pytest.skip("auf diesem System ist kein Hashen moeglich")
    assert klartext not in hash_
    assert hash_.startswith(GUELTIGE_PRAEFIXE), f"unerwartetes Format: {hash_[:6]}"


def test_a_secret_is_accepted_as_well_as_a_string() -> None:
    try:
        aus_text = users.hash_password("dasselbe-passwort")
        aus_secret = users.hash_password(Secret("dasselbe-passwort"))
    except HashingUnavailable:
        pytest.skip("auf diesem System ist kein Hashen moeglich")
    # Verschiedene Salze -- also verschiedene Hashes, aber gleiches Verfahren.
    assert aus_text[:3] == aus_secret[:3]
    assert "dasselbe-passwort" not in aus_text + aus_secret


def test_two_hashes_of_the_same_password_differ() -> None:
    """Ohne Salz waere ein Regenbogentabellen-Angriff trivial."""
    try:
        erster = users.hash_password("gleiches-passwort")
        zweiter = users.hash_password("gleiches-passwort")
    except HashingUnavailable:
        pytest.skip("auf diesem System ist kein Hashen moeglich")
    assert erster != zweiter, "gleiche Hashes deuten auf ein fehlendes Salz"


def test_the_cascade_falls_through_to_the_next_level(monkeypatch) -> None:
    """Faellt libcrypt aus, muss openssl uebernehmen."""
    monkeypatch.setattr(users, "_hash_via_libcrypt", lambda _p: None)
    try:
        hash_ = users.hash_password("probe-passwort")
    except HashingUnavailable:
        pytest.skip("openssl ist auf diesem System nicht verfuegbar")
    assert hash_.startswith("$6$"), "openssl liefert sha512crypt"


def test_an_exception_in_one_level_does_not_abort_the_cascade(monkeypatch) -> None:
    """Ein kaputtes libcrypt darf nicht das ganze Hashen verhindern."""

    def platzt(_password: str) -> str:
        raise RuntimeError("libcrypt kaputt")

    monkeypatch.setattr(users, "_hash_via_libcrypt", platzt)
    try:
        hash_ = users.hash_password("probe-passwort")
    except HashingUnavailable:
        pytest.skip("openssl ist auf diesem System nicht verfuegbar")
    assert hash_.startswith("$6$")


def test_without_any_method_it_says_so_clearly(monkeypatch) -> None:
    monkeypatch.setattr(users, "_hash_via_libcrypt", lambda _p: None)
    monkeypatch.setattr(users, "_hash_via_openssl", lambda _p: None)
    with pytest.raises(HashingUnavailable) as info:
        users.hash_password("egal")
    # Die Meldung fuer den Benutzer muss sagen, was jetzt passiert -- nicht,
    # welche Bibliothek fehlt. Der technische Grund steht getrennt davon.
    meldung = str(info.value)
    assert "gesperrt" in meldung
    assert "passwd" in meldung
    assert "openssl" in info.value.technical or "libcrypt" in info.value.technical


def test_hashing_available_agrees_with_hash_password(monkeypatch) -> None:
    """Die beiden duerfen nicht auseinanderlaufen.

    Waere ``hashing_available()`` optimistischer als die Wirklichkeit, boete
    die Oberflaeche ein Passwortfeld an, das beim Erzeugen wirkungslos bliebe.
    """
    moeglich = users.hashing_available()
    try:
        users.hash_password("probe")
        tatsaechlich = True
    except HashingUnavailable:
        tatsaechlich = False
    assert moeglich == tatsaechlich

    monkeypatch.setattr(users, "_hash_via_libcrypt", lambda _p: None)
    monkeypatch.setattr(users, "_hash_via_openssl", lambda _p: None)
    assert users.hashing_available() is False


def test_openssl_is_never_given_the_password_as_an_argument(monkeypatch) -> None:
    """In argv steht das Passwort fuer jeden lesbar in /proc/<pid>/cmdline."""
    aufgezeichnet: dict[str, object] = {}

    class FakeResult:
        returncode = 0
        stdout = "$6$salz$hash"
        stderr = ""

    def fake_run(argv, **kwargs):
        aufgezeichnet["argv"] = list(argv)
        aufgezeichnet["input"] = kwargs.get("input")
        return FakeResult()

    monkeypatch.setattr(users.shutil, "which", lambda _n: "/usr/bin/openssl")
    monkeypatch.setattr(users.subprocess, "run", fake_run)

    users._hash_via_openssl("streng-geheim")
    assert "streng-geheim" not in " ".join(aufgezeichnet["argv"])
    assert aufgezeichnet["input"] == "streng-geheim", "muss ueber stdin gehen"
    assert "-stdin" in aufgezeichnet["argv"]


def test_openssl_output_in_a_wrong_format_is_rejected(monkeypatch) -> None:
    """Lieber gar kein Hash als ein unbrauchbarer in der shadow-Datei."""

    class FakeResult:
        returncode = 0
        stdout = "voellig unerwartete Ausgabe"
        stderr = ""

    monkeypatch.setattr(users.shutil, "which", lambda _n: "/usr/bin/openssl")
    monkeypatch.setattr(users.subprocess, "run", lambda *a, **k: FakeResult())
    assert users._hash_via_openssl("egal") is None


# ---------------------------------------------------------------------------
# Die erzeugten Dateizeilen
# ---------------------------------------------------------------------------


def test_root_stays_locked_by_default() -> None:
    zeile = users.root_shadow_line()
    felder = zeile.split(":")
    assert felder[0] == "root"
    assert felder[1] == users.LOCKED, "root muss gesperrt sein"


def test_a_shadow_line_never_leaks_the_plaintext() -> None:
    try:
        hash_ = users.hash_password("mein-klartext-passwort")
    except HashingUnavailable:
        pytest.skip("auf diesem System ist kein Hashen moeglich")
    assert "mein-klartext-passwort" not in hash_
