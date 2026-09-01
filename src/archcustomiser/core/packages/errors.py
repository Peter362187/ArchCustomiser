"""Fehlertypen der Paketschicht.

Strikte Trennung von zwei Ebenen:

* **Transport** -- etwas hat technisch nicht funktioniert. Das sind Exceptions.
* **Paket** -- "existiert nicht" ist ein *Ergebnis*, keine Ausnahme. Es wird als
  Datensatz zurueckgegeben und darf niemals eine ganze Pruefung abbrechen.

Diese Trennung ist die Voraussetzung fuer die wichtigste Regel der Schicht:
Ein Paket darf nur dann als "existiert nicht" gemeldet werden, wenn ein
vollstaendiger Index vorliegt. Sonst meldet ein Netzausfall
"Das Paket firefox existiert nicht" -- genau der irrefuehrende Fehler, den die
Spezifikation (Abschnitt 13) vermeiden will.

Jeder Fehler traegt zwei Texte: ``user_message`` fuer den Dialog und
``technical`` fuer das Log.
"""

from __future__ import annotations

from datetime import timedelta


class PackageLayerError(Exception):
    """Basisklasse. Immer mit einer verstaendlichen Meldung."""

    def __init__(self, user_message: str, technical: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical = technical or user_message

    def __str__(self) -> str:
        return self.user_message


class InvalidPackageName(ValueError):
    """Syntaktisch unmoeglicher Paketname.

    Wird ohne jeden Netzwerk- oder Dateizugriff erkannt. Alles, was hier
    durchfaellt, erreicht niemals ``subprocess``, ``urllib`` oder das
    Dateisystem.
    """

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"{name!r}: {reason}")
        self.name = name
        self.reason = reason
        self.user_message = f"{name!r} ist kein gueltiger Paketname: {reason}"


class BackendUnavailable(PackageLayerError):
    """Die Paketdaten sind derzeit nicht erreichbar."""


class NetworkUnavailable(BackendUnavailable):
    """Keine Verbindung: DNS, Timeout, Verbindung abgelehnt."""

    def __init__(self, technical: str = "") -> None:
        super().__init__(
            "Keine Verbindung zu den Arch-Paketservern. Bitte die Netzwerkverbindung pruefen.",
            technical,
        )


class MirrorError(BackendUnavailable):
    """Der Spiegelserver antwortet, aber nicht brauchbar."""

    def __init__(self, technical: str, status: int | None = None, tried: tuple[str, ...] = ()) -> None:
        super().__init__(
            "Die Paketdatenbanken konnten von keinem Spiegelserver geladen werden.",
            technical,
        )
        self.status = status
        self.tried = tried


class RepositoryDataError(PackageLayerError):
    """Die heruntergeladene Datenbank ist beschaedigt."""

    def __init__(self, repo: str, technical: str) -> None:
        super().__init__(
            f"Die Paketdatenbank des Repositories {repo!r} ist beschaedigt und wurde verworfen.",
            technical,
        )
        self.repo = repo


class CacheError(PackageLayerError):
    """Der Zwischenspeicher ist nicht beschreibbar."""


class PacmanNotAvailable(BackendUnavailable):
    def __init__(self) -> None:
        super().__init__(
            "Auf diesem System ist pacman nicht verfuegbar.",
            "shutil.which('pacman') is None",
        )


class PacmanInvocationError(BackendUnavailable):
    def __init__(self, returncode: int, stderr_tail: str) -> None:
        super().__init__(
            "Der Aufruf von pacman ist fehlgeschlagen.",
            f"exit={returncode}: {stderr_tail}",
        )
        self.returncode = returncode
        self.stderr_tail = stderr_tail


class StaleDataError(PackageLayerError):
    """Die Paketdaten sind zu alt fuer einen verlaesslichen Build."""

    def __init__(self, age: timedelta) -> None:
        days = age.days
        super().__init__(
            f"Die Paketdaten sind {days} Tage alt. Vor einem Build sollten sie "
            f"aktualisiert werden, sonst schlaegt die Installation moeglicherweise fehl.",
            f"age={age}",
        )
        self.age = age
