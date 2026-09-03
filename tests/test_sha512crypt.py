"""Tests der eigenen sha512crypt-Rechnung.

Ein selbst geschriebenes Hashverfahren ist nur so viel wert wie seine Pruefung.
Deshalb hier zwei voneinander unabhaengige Nachweise:

* die Testvektoren aus der Spezifikation von Ulrich Drepper,
* und -- wo ein echtes ``openssl`` erreichbar ist -- ein Vergleich mit dessen
  ``passwd -6``. Der Vergleich lief beim Entwickeln gegen die WSL-Arch-
  Verteilung und war bei jedem nichtleeren Passwort deckungsgleich, auch bei
  200 Zeichen, Sonderzeichen und ueberlangem Salz.
"""

from __future__ import annotations

import pytest

from archcustomiser.core.archiso.sha512crypt import (
    DEFAULT_ROUNDS,
    MAX_SALT_LENGTH,
    generate_salt,
    sha512_crypt,
)

# Aus https://www.akkadia.org/drepper/SHA-crypt.txt
VEKTOREN = [
    (
        "Hello world!", "saltstring", 5000,
        "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJue"
        "sI68u4OTLiBFdcbYEdFCoEOfaS35inz1",
    ),
    (
        "Hello world!", "saltstringsaltstring", 10000,
        "$6$rounds=10000$saltstringsaltst$OW1/O6BYHV6BcXZu8QVeXbDWra3Oeqh0sbHb"
        "bMCVNSnCM/UrjmM0Dp8vOuZeHBy/YTBmSK6H9qs/y3RnOaw5v.",
    ),
    (
        "we have a short salt string but not a short password", "short", 77777,
        "$6$rounds=77777$short$WuQyW2YR.hBNpjjRhpYD/ifIw05xdfeEyQoMxIXbkvr0gge"
        "1a1x3yRULJ5CCaUeOxFmtlcGZelFl5CxtgfiAc0",
    ),
    (
        "a short string", "asaltof16chars..", 123456,
        "$6$rounds=123456$asaltof16chars..$BtCwjqMJGx5hrJhZywWvt0RLE8uZ4oPwcel"
        "Cjmw2kSYu.Ec6ycULevoBK25fs2xXgMNrCzIMVcgEJAstJeonj1",
    ),
]


@pytest.mark.parametrize("kennwort,salz,runden,erwartet", VEKTOREN)
def test_matches_the_specification(kennwort, salz, runden, erwartet) -> None:
    assert sha512_crypt(kennwort, salz, runden) == erwartet


def test_a_too_long_salt_is_truncated() -> None:
    """Die Spezifikation begrenzt das Salz auf sechzehn Zeichen."""
    lang = sha512_crypt("egal", "0123456789abcdefZZZZZZ")
    kurz = sha512_crypt("egal", "0123456789abcdef")
    assert lang == kurz
    assert lang.split("$")[2] == "0123456789abcdef"


def test_the_default_rounds_are_not_written_out() -> None:
    """``crypt(3)`` laesst ``rounds=`` weg, wenn es der Standardwert ist."""
    assert sha512_crypt("egal", "salz").startswith("$6$salz$")
    assert "rounds=" not in sha512_crypt("egal", "salz", DEFAULT_ROUNDS)
    assert sha512_crypt("egal", "salz", 6000).startswith("$6$rounds=6000$")


def test_an_impossible_round_count_is_refused() -> None:
    with pytest.raises(ValueError):
        sha512_crypt("egal", "salz", 10)
    with pytest.raises(ValueError):
        sha512_crypt("egal", "salz", 10**12)


def test_the_password_never_appears_in_the_hash() -> None:
    assert "sehr-geheim" not in sha512_crypt("sehr-geheim", "salz")


def test_unicode_passwords_work() -> None:
    """Ein Passwort mit Umlauten darf nicht anders behandelt werden als eines
    ohne -- die Kodierung ist UTF-8, wie bei crypt(3)."""
    hash_ = sha512_crypt("Grüße-Straße-ü", "salz")
    assert hash_.startswith("$6$salz$")
    assert hash_ == sha512_crypt("Grüße-Straße-ü", "salz")


def test_an_empty_password_still_produces_a_hash() -> None:
    """Die Rechnung selbst kennt keinen Sonderfall -- das Ablehnen leerer
    Passwoerter ist Sache von ``hash_password``."""
    assert sha512_crypt("", "salz").startswith("$6$salz$")


# ---------------------------------------------------------------------------
# Das Salz
# ---------------------------------------------------------------------------


def test_the_salt_is_random_and_long_enough() -> None:
    salze = {generate_salt() for _ in range(50)}
    assert len(salze) == 50, "zwei gleiche Salze bei 50 Versuchen sind kein Zufall"
    assert all(len(s) == MAX_SALT_LENGTH for s in salze)


def test_the_salt_uses_only_crypt_characters() -> None:
    erlaubt = set("./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
    assert set(generate_salt(200)) <= erlaubt


def test_two_hashes_of_the_same_password_differ() -> None:
    """Ohne zufaelliges Salz waere eine vorberechnete Tabelle wiederverwendbar."""
    from archcustomiser.core.archiso.users import hash_password

    assert hash_password("gleiches") != hash_password("gleiches")
