"""Syntaxpruefung fuer Paketnamen -- die Sicherheitsgrenze der Schicht.

Jeder Name, der aus einem Eingabefeld oder einer Profildatei kommt, muss hier
durch, bevor er ``subprocess``, ``urllib`` oder das Dateisystem erreicht.

Was das konkret verhindert:

* ``-Sy`` oder ``--dbpath=/`` als "Paketname": ein fuehrendes ``-`` wuerde von
  pacman als Schalter gelesen. Zusaetzlich setzt der Aufrufer immer ``--`` vor
  die Namensliste -- zwei unabhaengige Schutzschichten.
* ``../../etc/passwd``: Schraegstriche wuerden beim Cache-Dateinamen ausbrechen.
* ``; rm -rf /`` oder ``$(id)``: waeren nur gefaehrlich, wenn irgendwo eine
  Shell im Spiel waere. Es gibt keine -- aber der Name faellt hier trotzdem
  durch, weil er kein gueltiger Paketname ist.

Die erlaubte Zeichenmenge folgt der Arch-Paketrichtlinie: Kleinbuchstaben,
Ziffern und ``@ . _ + -``, wobei ``-`` nicht am Anfang stehen darf.
"""

from __future__ import annotations

import re
import unicodedata

from .errors import InvalidPackageName

MAX_NAME_LENGTH = 128

_VALID_NAME = re.compile(r"^[a-z0-9@._+][a-z0-9@._+-]*$")

# Version-Einschraenkungen wie "firefox>=140" duerfen eingegeben werden, sind in
# einer archiso-Paketliste aber wirkungslos -- der Aufrufer bekommt sie
# abgetrennt zurueck und kann warnen.
_CONSTRAINT = re.compile(r"^(?P<name>[^<>=]+)(?P<op><=|>=|<|>|=)(?P<version>.+)$")

_SEPARATORS = re.compile(r"[\s,;\n\r\t]+")


def split_constraint(raw: str) -> tuple[str, str | None]:
    """Trennt ``firefox>=140`` in ``("firefox", ">=140")``."""
    match = _CONSTRAINT.match(raw.strip())
    if not match:
        return raw.strip(), None
    return match.group("name").strip(), f"{match.group('op')}{match.group('version')}".strip()


def validate_name(raw: str) -> str:
    """Gibt den normalisierten Namen zurueck oder wirft ``InvalidPackageName``."""
    if not isinstance(raw, str):
        raise InvalidPackageName(str(raw), "kein Text")

    text = raw.strip()
    if not text:
        raise InvalidPackageName(raw, "leerer Name")

    if len(text) > MAX_NAME_LENGTH:
        raise InvalidPackageName(text[:40] + "...", f"laenger als {MAX_NAME_LENGTH} Zeichen")

    if "\x00" in text:
        raise InvalidPackageName(raw, "enthaelt ein Nullbyte")

    # Homoglyphen und Zeichen ausserhalb von ASCII sind in Paketnamen nicht
    # vorgesehen und ein klassischer Verwechslungsvektor.
    if not text.isascii():
        normalized = unicodedata.normalize("NFKC", text)
        raise InvalidPackageName(
            text,
            "enthaelt Zeichen ausserhalb des ASCII-Bereichs"
            + (f" (aussehen wie {normalized!r})" if normalized != text else ""),
        )

    if text.startswith("-"):
        raise InvalidPackageName(
            text, "darf nicht mit '-' beginnen (waere ein Kommandozeilenschalter)"
        )

    if "/" in text or "\\" in text:
        raise InvalidPackageName(text, "darf keine Pfadtrenner enthalten")

    if text in (".", ".."):
        raise InvalidPackageName(text, "ist ein Verzeichnisverweis, kein Paketname")

    if not _VALID_NAME.match(text):
        raise InvalidPackageName(
            text,
            "erlaubt sind Kleinbuchstaben, Ziffern und die Zeichen @ . _ + -",
        )

    return text


def is_valid(raw: str) -> bool:
    try:
        validate_name(raw)
    except InvalidPackageName:
        return False
    return True


def parse_list(raw: str) -> list[str]:
    """Zerlegt eine Eingabezeile in Einzelnamen.

    Getrennt wird an Leerzeichen, Komma, Semikolon und Zeilenumbruch --
    Benutzer schreiben alles davon. Doppelte Eintraege fallen weg,
    die Reihenfolge bleibt erhalten.
    """
    seen: set[str] = set()
    result: list[str] = []
    for token in _SEPARATORS.split(raw or ""):
        token = token.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def split_provide(entry: str) -> tuple[str, str | None]:
    """Zerlegt einen %PROVIDES%-Eintrag wie ``libcap.so=2-64``."""
    name, separator, version = entry.partition("=")
    return (name.strip(), version.strip() if separator else None)
