"""Fehlertypen des ISO-Baus.

Gleiche Trennung wie in den anderen Schichten: ``user_message`` fuer den
Dialog, ``technical`` fuer das Protokoll.

Eine Besonderheit hier: ``BuildFailed`` traegt die letzten Fehlerzeilen von
mkarchiso mit. Der Exit-Code allein sagt nichts -- die Ursache steht immer in
einer ``ERROR:``-Zeile davor, und mkarchiso sammelt Validierungsfehler sogar
und meldet am Ende nur die Anzahl.
"""

from __future__ import annotations


class BuildError(Exception):
    """Basisklasse."""

    def __init__(self, user_message: str, technical: str = "") -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.technical = technical or user_message

    def __str__(self) -> str:
        return self.user_message


class PreflightError(BuildError):
    """Der Build wurde gar nicht erst gestartet."""

    def __init__(self, user_message: str, remedies: tuple[str, ...] = (), technical: str = "") -> None:
        super().__init__(user_message, technical)
        self.remedies = remedies


class BuildCancelled(BuildError):
    """Der Benutzer hat abgebrochen."""

    def __init__(self) -> None:
        super().__init__("Der Build wurde abgebrochen.")


class BuildFailed(BuildError):
    """mkarchiso ist mit einem Fehler beendet worden."""

    def __init__(
        self,
        returncode: int,
        errors: tuple[str, ...] = (),
        stage: str = "",
        log_path: str = "",
    ) -> None:
        cause = errors[0] if errors else f"mkarchiso endete mit Code {returncode}"
        where = f" (Schritt: {stage})" if stage else ""
        super().__init__(
            f"Der ISO-Build ist fehlgeschlagen{where}.\n\n{cause}",
            f"returncode={returncode} stage={stage!r} errors={list(errors)}",
        )
        self.returncode = returncode
        self.errors = errors
        self.stage = stage
        self.log_path = log_path


class MkarchisoMissing(PreflightError):
    def __init__(self) -> None:
        super().__init__(
            "mkarchiso wurde nicht gefunden. Ohne archiso laesst sich keine ISO bauen.",
            ("sudo pacman -S --needed archiso",),
            "shutil.which('mkarchiso') is None",
        )


class NotEnoughSpace(PreflightError):
    def __init__(self, path: str, available_gb: float, needed_gb: float) -> None:
        super().__init__(
            f"Im Arbeitsverzeichnis {path} sind nur {available_gb:.1f} GB frei. "
            f"Fuer diesen Build werden etwa {needed_gb:.0f} GB gebraucht.\n\n"
            f"Ein abgebrochener Build hinterlaesst ein unvollstaendiges "
            f"Arbeitsverzeichnis, das erst wieder aufgeraeumt werden muss.",
            (
                "Ein anderes Arbeitsverzeichnis auf einer groesseren Platte waehlen.",
                "Alte Arbeitsverzeichnisse frueherer Builds loeschen.",
            ),
            f"path={path!r} available={available_gb} needed={needed_gb}",
        )
        self.available_gb = available_gb
        self.needed_gb = needed_gb
