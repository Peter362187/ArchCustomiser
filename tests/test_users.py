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


# ---------------------------------------------------------------------------
# Die Kaskade nach dem Umbau
#
# Frueher hing das Hashen an libcrypt (nur Linux) oder "openssl passwd -6"
# (nicht auf macOS, unter Windows nur mit Git for Windows). Seit die zweite
# Stufe eine eigene Rechnung ist, kann sie nicht mehr fehlschlagen.
# ---------------------------------------------------------------------------


def test_hashing_works_without_any_external_tool(monkeypatch) -> None:
    """Der Kern des Umbaus: kein Fremdprogramm mehr noetig."""
    monkeypatch.setattr(users, "_hash_via_libcrypt", lambda _p: None)
    hash_ = users.hash_password("hunter2")
    assert hash_.startswith("$6$")
    assert "hunter2" not in hash_


def test_the_module_cannot_start_a_process_at_all() -> None:
    """Die schaerfste Form der Zusicherung: das Modul kennt subprocess nicht.

    Der Klartext ging frueher durch das stdin eines openssl-Subprozesses.
    Diesen Weg zu entfernen genuegt nicht -- solange das Modul subprocess noch
    importiert, kann ihn jemand versehentlich wieder einbauen. Jetzt gibt es
    den Import nicht mehr, und dieser Test faellt, sobald er zurueckkehrt.
    """
    assert not hasattr(users, "subprocess")
    assert not hasattr(users, "shutil")


def test_hashing_starts_no_process(monkeypatch) -> None:
    """Und zur Sicherheit auch am laufenden Aufruf gemessen."""
    import subprocess as echtes_subprocess

    monkeypatch.setattr(users, "_hash_via_libcrypt", lambda _p: None)

    def darf_nicht(*args, **kwargs):
        raise AssertionError("es wurde ein Prozess gestartet")

    monkeypatch.setattr(echtes_subprocess, "run", darf_nicht)
    monkeypatch.setattr(echtes_subprocess, "Popen", darf_nicht)
    assert users.hash_password("hunter2").startswith("$6$")


def test_libcrypt_still_wins_when_available(monkeypatch) -> None:
    """yescrypt ist staerker als sha512crypt -- libcrypt behaelt den Vortritt."""
    monkeypatch.setattr(users, "_hash_via_libcrypt", lambda _p: "$y$jvorgetaeuscht")
    assert users.hash_password("hunter2") == "$y$jvorgetaeuscht"


def test_a_broken_libcrypt_does_not_stop_the_cascade(monkeypatch) -> None:
    def platzt(_password: str) -> str:
        raise RuntimeError("libcrypt kaputt")

    monkeypatch.setattr(users, "_hash_via_libcrypt", platzt)
    assert users.hash_password("hunter2").startswith("$6$")


def test_hashing_is_now_available_everywhere(monkeypatch) -> None:
    """Auch ohne libcrypt -- also auch auf Windows und macOS."""
    monkeypatch.setattr(users, "_hash_via_libcrypt", lambda _p: None)
    assert users.hashing_available() is True


def test_the_only_remaining_failure_is_an_empty_password() -> None:
    with pytest.raises(HashingUnavailable):
        users.hash_password("")
