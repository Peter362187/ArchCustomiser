"""Wo ein Build ausgefuehrt wird.

Der Ablauf ist derselbe, egal ob mkarchiso direkt auf diesem Rechner laeuft
oder in einer WSL-Verteilung daneben. Was sich unterscheidet, sind drei Dinge,
und genau die kapselt dieses Modul:

* wie ein Aufruf zusammengesetzt wird (``mkarchiso …`` oder ``wsl -d … -e mkarchiso …``),
* wie Verzeichnisse angelegt werden (lokal oder drueben),
* wo die fertige ISO gesucht wird.

Ohne diese Trennung muesste der Runner an drei Stellen Sonderfaelle kennen --
und die Windows-Variante waere nicht mehr testbar, ohne WSL zu haben.
"""

from __future__ import annotations

import logging
import shutil
import re
from pathlib import Path, PurePosixPath
from typing import Mapping, Protocol, Sequence

from .errors import MkarchisoMissing
from ..archiso.quoting import shell_quote

log = logging.getLogger(__name__)


class ExecutionTarget(Protocol):
    """Wohin ein Bauauftrag geht."""

    name: str

    def resolve_executable(self) -> str:
        """Der Programmname, wie ihn der Zielrechner kennt."""

    def wrap(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> list[str]:
        """Macht aus dem Aufruf einen auf diesem Rechner startbaren Befehl.

        ``env`` sind Variablen, die das aufgerufene Programm sehen muss. Lokal
        reicht dafuer die Prozessumgebung; ueber eine Systemgrenze hinweg muss
        sie ausdruecklich mitgegeben werden.
        """

    def make_dirs(self, *paths: str) -> None:
        """Legt Verzeichnisse auf dem Zielrechner an."""

    def cwd(self) -> str | None:
        """Arbeitsverzeichnis fuer den Prozessstart -- oder None."""

    def sanitize_environment(self, env: dict[str, str]) -> dict[str, str]:
        """Bereinigt die Umgebung des startenden Prozesses."""

    def find_iso(self, out_dir: str, expected: str) -> str | None:
        """Sucht die fertige ISO auf dem Zielrechner."""

    def fetch_iso(self, remote_iso: str, destination: Path) -> Path:
        """Holt die ISO dorthin, wo der Benutzer sie erwartet."""


class LocalTarget:
    """Der Normalfall: mkarchiso laeuft auf diesem Rechner."""

    name = "lokal"

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable

    def resolve_executable(self) -> str:
        found = self._executable or shutil.which("mkarchiso")
        if found is None:
            raise MkarchisoMissing()
        return found

    def wrap(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> list[str]:
        # Lokal erbt der Prozess die Umgebung ohnehin.
        return [str(item) for item in argv]

    def make_dirs(self, *paths: str) -> None:
        for path in paths:
            Path(path).mkdir(parents=True, exist_ok=True)

    def cwd(self) -> str | None:
        return None

    def sanitize_environment(self, env: dict[str, str]) -> dict[str, str]:
        return env

    def find_iso(self, out_dir: str, expected: str) -> str | None:
        directory = Path(out_dir)
        if expected:
            candidate = directory / expected
            if candidate.is_file():
                return str(candidate)
        try:
            found = sorted(
                directory.glob("*.iso"), key=lambda p: p.stat().st_mtime, reverse=True
            )
        except OSError:
            return None
        return str(found[0]) if found else None

    def fetch_iso(self, remote_iso: str, destination: Path) -> Path:
        # Sie liegt bereits, wo sie hingehoert.
        return Path(remote_iso)


class WslExecutionTarget:
    """mkarchiso laeuft in einer WSL-Verteilung.

    Alle Pfade sind hier Linux-Pfade. Sie duerfen nicht durch ``pathlib.Path``
    laufen -- unter Windows wuerde daraus ``\\home\\jason`` statt
    ``/home/jason``.
    """

    name = "wsl"

    def __init__(self, wsl_target) -> None:
        self.wsl = wsl_target
        self.name = f"wsl:{wsl_target.distribution}"

    def resolve_executable(self) -> str:
        if not self.wsl.has_command("mkarchiso"):
            raise MkarchisoMissing()
        return "mkarchiso"

    def wrap(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> list[str]:
        """Baut den Aufruf fuer die Verteilung.

        Umgebungsvariablen, die auf der Windows-Seite gesetzt sind, erreichen
        WSL **nicht** von selbst -- sie muessten ueber ``WSLENV`` angemeldet
        werden. Statt sich auf dessen Regeln zu verlassen, werden sie hier
        ausdruecklich ueber ``env`` vorangestellt: eine feste Argumentliste,
        keine Shell, kein Raum fuer Missverstaendnisse.
        """
        arguments = [str(item) for item in argv]
        if env:
            assignments = []
            for key, value in sorted(env.items()):
                if not _VALID_ENV_NAME.match(key):
                    raise ValueError(f"unzulaessiger Variablenname: {key!r}")
                text = str(value)
                # Steuerzeichen koennten die Argumentliste zerreissen.
                if any(ord(char) < 32 for char in text):
                    raise ValueError(f"unzulaessiger Wert fuer {key!r}")
                assignments.append(f"{key}={text}")
            arguments = ["env", *assignments, *arguments]
        return self.wsl.wrap(arguments)

    def make_dirs(self, *paths: str) -> None:
        for path in paths:
            result = self.wsl.run(["mkdir", "-p", path])
            if not result.ok:
                from .wsl import WslError

                raise WslError(
                    f"Das Verzeichnis {path} konnte in WSL nicht angelegt werden.",
                    result.stderr.strip(),
                )

    def cwd(self) -> str | None:
        """Ein Verzeichnis, das WSL auf die Linux-Seite abbilden kann.

        ``wsl.exe`` uebernimmt das aktuelle Verzeichnis des aufrufenden
        Prozesses. Liegt das auf einem Netz- oder Nicht-Systemlaufwerk, meldet
        es beim Start ``Failed to translate 'E:\\…'`` -- harmlos, aber es steht
        dann im Protokoll und sieht nach einem Fehler aus.

        Deshalb wird ausdruecklich das Systemlaufwerk gesetzt, das WSL immer
        unter ``/mnt/c`` kennt. Fuer mkarchiso selbst spielt es keine Rolle:
        alle Pfade bekommt es als Argument.
        """
        import os

        drive = os.environ.get("SystemDrive", "C:")
        return drive + "\\"

    def sanitize_environment(self, env: dict[str, str]) -> dict[str, str]:
        """Entfernt PATH-Eintraege, die WSL nicht abbilden kann.

        ``wsl.exe`` uebersetzt den Windows-PATH in die Linux-Sicht. Liegt darin
        ein Netzlaufwerk, meldet es fuer jeden solchen Eintrag
        ``wsl: Failed to translate 'U:\\bin'``. Das ist folgenlos, landet aber
        im Bauprotokoll und sieht dort wie ein Fehler aus -- ausgerechnet in den
        ersten Zeilen, wo man nach Ursachen sucht.

        Entfernt werden nur Eintraege auf nicht-lokalen Laufwerken. Fuer
        mkarchiso spielt der Windows-PATH ohnehin keine Rolle.
        """
        import os

        raw = env.get("PATH")
        if not raw:
            return env
        kept = [entry for entry in raw.split(os.pathsep) if entry and _is_local_drive(entry)]
        cleaned = dict(env)
        cleaned["PATH"] = os.pathsep.join(kept)
        return cleaned

    def find_iso(self, out_dir: str, expected: str) -> str | None:
        posix_out = PurePosixPath(out_dir)
        if expected:
            candidate = str(posix_out / expected)
            if self.wsl.run(["test", "-f", candidate]).ok:
                return candidate
        # Sonst die neueste ISO im Ausgabeverzeichnis.
        result = self.wsl.run(
            ["sh", "-c", f"ls -1t {shell_quote(out_dir)}/*.iso 2>/dev/null | head -n1"]
        )
        found = result.stdout.strip()
        return found or None

    def fetch_iso(self, remote_iso: str, destination: Path) -> Path:
        """Kopiert die ISO aus der Verteilung nach Windows.

        Ueber ``cp`` innerhalb von Linux statt ueber den Netzwerkpfad
        ``\\\\wsl$\\…``: das ist deutlich schneller und umgeht die
        Groessenbeschraenkungen des Umleitungsdienstes.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        windows_target = self.wsl.to_linux_path(destination)
        result = self.wsl.run(
            ["cp", "--", remote_iso, windows_target], timeout=1800.0
        )
        if not result.ok:
            from .wsl import WslError

            raise WslError(
                f"Die fertige ISO konnte nicht nach {destination} kopiert werden.",
                result.stderr.strip(),
            )
        log.info("ISO nach Windows kopiert: %s", destination)
        return destination


_VALID_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_DRIVE_FIXED = 3


def _is_local_drive(path: str) -> bool:
    """Ob ein Pfad auf einem festen Laufwerk liegt.

    Netz- und Wechsellaufwerke kann WSL nicht auf die Linux-Seite abbilden.
    Ausserhalb von Windows ist die Frage gegenstandslos.
    """
    import os

    if os.name != "nt" or len(path) < 2 or path[1] != ":":
        return True
    try:
        import ctypes

        return ctypes.windll.kernel32.GetDriveTypeW(path[0] + ":\\") == _DRIVE_FIXED
    except Exception:
        # Im Zweifel behalten -- ein zu voller PATH ist harmloser als ein leerer.
        return True

