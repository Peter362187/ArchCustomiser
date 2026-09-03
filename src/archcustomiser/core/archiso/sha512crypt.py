"""sha512crypt in reinem Python.

Warum das hier steht, obwohl es das Verfahren in jedem Linux gibt: die beiden
bisherigen Wege sind beide an ein fremdes Programm gebunden.

* ``libcrypt`` gibt es nur unter Linux. macOS hat keine eigenstaendige libcrypt,
  und das ``crypt(3)`` in libSystem ist die alte DES-Variante.
* ``openssl passwd -6`` gibt es nur mit echtem OpenSSL. macOS liefert LibreSSL,
  dessen ``passwd`` die Schalter ``-5`` und ``-6`` gar nicht kennt -- die
  SHA-crypt-Verfahren kamen erst in OpenSSL 1.1.1 dazu, lange nach dem Fork.
  Unter Windows gibt es beides nur, wenn zufaellig Git for Windows installiert
  ist und sein ``openssl`` im PATH liegt.

Wo beides fehlte, wurde das Benutzerkonto **gesperrt** angelegt. Das war ehrlich
gemeldet, aber es hiess: wer auf einem Mac oder einem schlanken Windows eine ISO
baut, bekommt ein Konto ohne Passwort.

Dieselbe Rechnung in Python kostet siebzig Zeilen, keine Abhaengigkeit -- und ist
sogar sicherer als der bisherige Rueckfallweg, weil der Klartext den Prozess
nicht mehr verlaesst: kein Subprozess, kein stdin, nichts, was ein anderer
Prozess mitlesen koennte.

Umgesetzt nach der Spezifikation von Ulrich Drepper (SHA-crypt), gegen deren
Testvektoren geprueft.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Final

# Das Alphabet von crypt(3) -- NICHT das von base64. Reihenfolge und Zeichen
# unterscheiden sich, und ein Vertauschen faellt erst auf, wenn sich niemand
# mehr anmelden kann.
_ALPHABET: Final = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

DEFAULT_ROUNDS: Final = 5000
MIN_ROUNDS: Final = 1000
MAX_ROUNDS: Final = 999_999_999
MAX_SALT_LENGTH: Final = 16

# Die Bytes des Digests werden nicht der Reihe nach kodiert, sondern in dieser
# von der Spezifikation vorgegebenen Folge. Je drei Bytes ergeben vier Zeichen.
_ORDER: Final = (
    (0, 21, 42), (22, 43, 1), (44, 2, 23), (3, 24, 45), (25, 46, 4),
    (47, 5, 26), (6, 27, 48), (28, 49, 7), (50, 8, 29), (9, 30, 51),
    (31, 52, 10), (53, 11, 32), (12, 33, 54), (34, 55, 13), (56, 14, 35),
    (15, 36, 57), (37, 58, 16), (59, 17, 38), (18, 39, 60), (40, 61, 19),
    (62, 20, 41),
)


def _encode(digest: bytes) -> str:
    """Die crypt(3)-Kodierung: drei Bytes zu vier Zeichen, kleinstes zuerst."""
    text: list[str] = []
    for links, mitte, rechts in _ORDER:
        wert = (digest[links] << 16) | (digest[mitte] << 8) | digest[rechts]
        for _ in range(4):
            text.append(_ALPHABET[wert & 0x3F])
            wert >>= 6
    # Das letzte Byte steht allein und ergibt nur zwei Zeichen.
    wert = digest[63]
    for _ in range(2):
        text.append(_ALPHABET[wert & 0x3F])
        wert >>= 6
    return "".join(text)


def _repeat(block: bytes, length: int) -> bytes:
    """``block`` so oft aneinander, bis ``length`` Bytes erreicht sind."""
    if not block:
        return b""
    ganze, rest = divmod(length, len(block))
    return block * ganze + block[:rest]


def sha512_crypt(password: str, salt: str, rounds: int = DEFAULT_ROUNDS) -> str:
    """Erzeugt einen ``$6$``-Hash, wie ihn ``/etc/shadow`` erwartet.

    ``salt`` wird auf sechzehn Zeichen gekuerzt, wie es die Spezifikation
    vorschreibt. ``rounds`` erscheint nur dann im Ergebnis, wenn es vom
    Standardwert abweicht -- genau so verhaelt sich auch ``crypt(3)``.
    """
    if not MIN_ROUNDS <= rounds <= MAX_ROUNDS:
        raise ValueError(f"rounds muss zwischen {MIN_ROUNDS} und {MAX_ROUNDS} liegen")

    kennwort = password.encode("utf-8")
    salz = salt.encode("utf-8")[:MAX_SALT_LENGTH]

    # Schritt 4-8: der Zwischendigest B.
    b = hashlib.sha512(kennwort + salz + kennwort).digest()

    # Schritt 1-3 und 9-12: Digest A.
    a = hashlib.sha512()
    a.update(kennwort + salz)
    a.update(_repeat(b, len(kennwort)))
    # Fuer jedes gesetzte Bit der Kennwortlaenge B, sonst das Kennwort selbst --
    # vom niedrigsten Bit aufwaerts.
    laenge = len(kennwort)
    while laenge:
        a.update(b if laenge & 1 else kennwort)
        laenge >>= 1
    zwischen = a.digest()

    # Schritt 13-15: die Folge P, aus dem Kennwort.
    dp = hashlib.sha512(kennwort * len(kennwort)).digest()
    p = _repeat(dp, len(kennwort))

    # Schritt 16-19: die Folge S, aus dem Salz. Die Wiederholungszahl haengt vom
    # ersten Byte des Zwischendigests ab.
    ds = hashlib.sha512(salz * (16 + zwischen[0])).digest()
    s = _repeat(ds, len(salz))

    # Schritt 21: die eigentliche Streckung. Der Sinn der Schleife ist, dass sie
    # dauert -- deshalb ist sie nicht "optimierbar".
    aktuell = zwischen
    for runde in range(rounds):
        c = hashlib.sha512()
        c.update(p if runde & 1 else aktuell)
        if runde % 3:
            c.update(s)
        if runde % 7:
            c.update(p)
        c.update(aktuell if runde & 1 else p)
        aktuell = c.digest()

    kopf = "$6$" if rounds == DEFAULT_ROUNDS else f"$6$rounds={rounds}$"
    return f"{kopf}{salz.decode('utf-8')}${_encode(aktuell)}"


def generate_salt(length: int = MAX_SALT_LENGTH) -> str:
    """Ein zufaelliges Salz aus dem crypt-Alphabet.

    Ueber ``secrets``, nicht ``random``: das Salz muss unvorhersagbar sein,
    sonst laesst sich eine vorberechnete Tabelle wiederverwenden.
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
