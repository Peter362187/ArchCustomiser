"""Fehlertypen der Profilerzeugung.

Gleiche Trennung wie in der Paketschicht: ``user_message`` fuer den Dialog,
``technical`` fuer das Log. Jeder Fehler nennt nach Moeglichkeit die
Katalogoption, die ihn ausgeloest hat -- sonst sucht man in 70 Optionen.
"""

from __future__ import annotations


class ProfileError(Exception):
    """Basisklasse der Profilerzeugung."""

    def __init__(self, user_message: str, technical: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical = technical or user_message

    def __str__(self) -> str:
        return self.user_message


class UnsafePathError(ProfileError):
    """Ein Zielpfad wuerde das Profilverzeichnis verlassen."""

    def __init__(self, path: str, reason: str, origin: str = "") -> None:
        where = f" (aus {origin})" if origin else ""
        super().__init__(
            f"Der Pfad {path!r} ist nicht zulaessig{where}: {reason}",
            f"path={path!r} origin={origin!r} reason={reason}",
        )
        self.path = path
        self.reason = reason
        self.origin = origin


class UnsafeValueError(ProfileError):
    """Ein Wert laesst sich nicht sicher nach Bash uebertragen."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(
            f"Der Wert fuer {field!r} kann nicht verwendet werden: {reason}",
            f"field={field!r} reason={reason}",
        )
        self.field = field
        self.reason = reason


class DuplicateEntryError(ProfileError):
    """Zwei Optionen wollen dieselbe Datei mit verschiedenem Inhalt schreiben."""

    def __init__(self, path: str, first: str, second: str) -> None:
        super().__init__(
            f"Die Datei {path!r} wird von {first!r} und {second!r} mit "
            f"unterschiedlichem Inhalt beansprucht. Bitte eine der beiden "
            f"Optionen abwaehlen.",
            f"path={path!r} first={first!r} second={second!r}",
        )
        self.path = path
        self.first = first
        self.second = second


class MissingAssetError(ProfileError):
    """Eine Branding-Datei fehlt oder ist unbrauchbar."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(
            f"Die Datei {path!r} konnte nicht verwendet werden: {reason}",
            f"asset={path!r} reason={reason}",
        )
        self.path = path
        self.reason = reason


class HashingUnavailable(ProfileError):
    """Auf diesem System laesst sich kein Passwort-Hash erzeugen."""

    def __init__(self, technical: str = "") -> None:
        super().__init__(
            "Auf diesem System kann kein Passwort-Hash erzeugt werden. Das Konto "
            "wird gesperrt angelegt; das Passwort laesst sich nach der Installation "
            "mit 'passwd' setzen.",
            technical,
        )


class SinkError(ProfileError):
    """Das Profil konnte nicht geschrieben werden."""


class TargetNotEmptyError(SinkError):
    """Im Zielverzeichnis liegen fremde Dateien."""

    def __init__(self, path: str, count: int) -> None:
        super().__init__(
            f"Das Verzeichnis {path} ist nicht leer ({count} Eintraege) und enthaelt "
            f"kein von diesem Programm erzeugtes Profil.\n\n"
            f"Bitte ein leeres oder neues Verzeichnis waehlen -- vorhandene Dateien "
            f"werden nicht ueberschrieben.",
            f"target={path!r} entries={count}",
        )
        self.path = path
        self.count = count


class SymlinksUnsupportedError(SinkError):
    """Das Dateisystem erlaubt keine Symlinks (Windows ohne Berechtigung)."""

    def __init__(self, path: str, technical: str = "") -> None:
        super().__init__(
            "Auf diesem System koennen keine symbolischen Verknuepfungen angelegt "
            "werden. Ein archiso-Profil braucht sie, um Dienste zu aktivieren.\n\n"
            "Bitte stattdessen 'Als Archiv exportieren' verwenden -- ein tar-Archiv "
            "speichert Verknuepfungen unabhaengig vom Dateisystem.",
            f"path={path!r} {technical}",
        )
