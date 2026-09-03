"""Wo ein Build ausgefuehrt wird.

Der Ablauf ist derselbe, gleich ob mkarchiso direkt auf diesem Rechner laeuft,
in einer WSL-Verteilung daneben oder in einem Container. Was sich unterscheidet,
kapselt dieses Modul -- und zwar vollstaendig:

* wie ein Aufruf zusammengesetzt wird (``mkarchiso …``, ``wsl -d … -e …`` oder
  ``podman run --privileged -v … …``),
* wie Verzeichnisse angelegt werden und wie sie auf der Gegenseite heissen,
* wie das Profil dorthin kommt (Verzeichnis, tar-Uebertragung oder Bind-Mount),
* wie geprueft, aufgeraeumt und abgebrochen wird.

Der Punkt dieser Trennung: der Controller kennt den Zieltyp nicht. Solange er
ihn kannte -- per ``isinstance`` an drei Stellen --, haette jedes weitere Ziel
die Zahl der Sonderfaelle vervielfacht. Ein Test haelt das jetzt fest.

Die drei Umsetzungen:

* ``LocalTarget`` -- ein Arch-System mit archiso.
* ``WslExecutionTarget`` -- Windows, ueber eine Arch-Verteilung in WSL.
* ``ContainerExecutionTarget`` -- jedes andere Linux und macOS, ueber podman
  oder docker mit dem archlinux-Abbild.
"""

from __future__ import annotations

import logging
import shutil
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Callable, Mapping, Protocol, Sequence

from .errors import MkarchisoMissing

if TYPE_CHECKING:
    from .preflight import PreflightReport
from ..archiso.quoting import shell_quote

log = logging.getLogger(__name__)

# Name des Profilverzeichnisses unterhalb des Arbeitsverzeichnisses.
PROFILE_DIRNAME = "profile"

# Variablennamen, die ueber eine Systemgrenze gehen duerfen.
_VALID_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class BuildPaths:
    """Profil-, Arbeits- und Ausgabeverzeichnis in der Schreibweise des Ziels.

    Bewusst Zeichenketten und keine ``Path``-Objekte: bei einem Bau in WSL oder
    in einem Container sind das Linux-Pfade, und ``pathlib`` machte unter
    Windows daraus einen Pfad mit Rueckwaertsschraegstrichen.
    """

    profile: str
    work: str
    out: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.profile, self.work, self.out)


class ExecutionTarget(Protocol):
    """Wohin ein Bauauftrag geht.

    Alles, was sich zwischen den Zielen unterscheidet, steht hier -- und nur
    hier. Der Controller hat frueher an drei Stellen per ``isinstance`` nach dem
    Zieltyp gefragt; bei zwei Zielen waren das drei Sonderfaelle, bei einem
    dritten Ziel waeren es neun geworden.
    """

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

    # -- Ablauf ---------------------------------------------------------------
    def prepare(self, iso_name: str, work_dir: Path, out_dir: Path) -> BuildPaths:
        """Legt die Verzeichnisse an und nennt sie in Zielschreibweise.

        ``work_dir`` und ``out_dir`` sind Wuensche des aufrufenden Rechners. Ein
        Ziel darf sie uebernehmen (lokal), ignorieren (WSL, wo drueben gebaut
        wird) oder einhaengen (Container). Genau deshalb muessen sie
        uebergeben werden *und* ignorierbar sein.
        """

    def deliver_profile(
        self,
        tree,
        paths: BuildPaths,
        *,
        iso_name: str,
        on_progress: "Callable[[float, str], None] | None" = None,
    ) -> None:
        """Bringt den Profilbaum dorthin, wo mkarchiso ihn findet."""

    def discard(
        self, paths: BuildPaths, *, keep_work_dir: bool, remove_output: bool
    ) -> None:
        """Raeumt auf.

        ``remove_output`` gilt nur dort, wo die Ausgabe nicht schon am Zielort
        liegt -- bei WSL etwa, wo die ISO erst herueberkopiert werden muss.
        Ziele, bei denen beides zusammenfaellt, ignorieren den Wert.
        """

    def preflight(
        self,
        work_dir: Path,
        out_dir: Path,
        *,
        installed_mb: int = 0,
        bootmodes: Sequence[str] = (),
    ) -> "PreflightReport":
        """Prueft dort, wo tatsaechlich gebaut wird.

        Bei einem Bau in WSL oder im Container waere eine Pruefung des
        aufrufenden Systems irrefuehrend: Werkzeuge, Plattenplatz und Rechte
        liegen alle drueben.
        """

    def cancel_run(
        self, process: "subprocess.Popen[bytes] | None", *, grace_seconds: float
    ) -> None:
        """Beendet den laufenden Bau -- dort, wo er wirklich laeuft.

        Den lokalen Prozess zu beenden reicht nur lokal. ``wsl.exe`` ist kein
        Signalweiterleiter: es zu beenden laesst mkarchiso in der Verteilung
        weiterlaufen. Bei einem Container traefe es nur den Client.
        """


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

    # -- Ablauf ---------------------------------------------------------------
    def prepare(self, iso_name: str, work_dir: Path, out_dir: Path) -> BuildPaths:
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._work_dir = work_dir
        return BuildPaths(
            profile=str(work_dir / PROFILE_DIRNAME),
            work=str(work_dir / "work"),
            out=str(out_dir),
        )

    def deliver_profile(
        self, tree, paths: BuildPaths, *, iso_name: str, on_progress=None
    ) -> None:
        from ..archiso import DirectorySink

        profile_dir = Path(paths.profile)
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
        DirectorySink(profile_dir, iso_name=iso_name, force=True).write(
            tree,
            progress=lambda done, total: (
                on_progress(
                    done / total if total else 1.0, f"{done} von {total} Dateien"
                )
                if on_progress is not None
                else None
            ),
        )

    def discard(
        self, paths: BuildPaths, *, keep_work_dir: bool, remove_output: bool
    ) -> None:
        # remove_output ist hier bedeutungslos: das Ausgabeverzeichnis IST der
        # Zielort, es zu loeschen waere ein Fehler.
        if keep_work_dir:
            return
        for pfad in (Path(paths.work), Path(paths.profile)):
            if not pfad.exists():
                continue
            try:
                shutil.rmtree(pfad)
                log.info("Aufgeraeumt: %s", pfad)
            except OSError as exc:
                # Ein misslungenes Aufraeumen darf einen erfolgreichen Build
                # nicht nachtraeglich zum Fehlschlag machen.
                log.warning("%s liess sich nicht loeschen: %s", pfad, exc)

    def preflight(self, work_dir, out_dir, *, installed_mb=0, bootmodes=()):
        from .preflight import run_preflight

        return run_preflight(
            work_dir, out_dir, installed_mb=installed_mb, bootmodes=bootmodes
        )

    def cancel_run(self, process, *, grace_seconds: float) -> None:
        """Erst freundlich, nach einer Frist hart.

        mkarchiso haengt oft in einem Unterprozess -- pacstrap oder mksquashfs --,
        der auf ein Signal nicht sofort reagiert.
        """
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        log.warning(
            "mkarchiso hat nach %.0f s nicht reagiert -- wird hart beendet.",
            grace_seconds,
        )
        try:
            process.kill()
        except OSError:
            pass


class WslExecutionTarget:
    """mkarchiso laeuft in einer WSL-Verteilung.

    Alle Pfade sind hier Linux-Pfade. Sie duerfen nicht durch ``pathlib.Path``
    laufen -- unter Windows wuerde daraus ein Pfad mit
    Rueckwaertsschraegstrichen statt eines Linux-Pfades.
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

    # -- Ablauf ---------------------------------------------------------------
    def prepare(self, iso_name: str, work_dir: Path, out_dir: Path) -> BuildPaths:
        """Gebaut wird drueben, nicht hier.

        ``work_dir`` und ``out_dir`` sind Windows-Pfade und werden bewusst
        ignoriert: das Arbeitsverzeichnis muss auf einem Linux-Dateisystem
        liegen, sonst gehen beim Entpacken der Pakete Rechte und Eigentuemer
        verloren. Nur die fertige ISO wandert am Ende nach ``out_dir``.
        """
        from .wsl_build import prepare_paths

        self._paths = prepare_paths(self.wsl, iso_name)
        return BuildPaths(*self._paths.as_strings())

    def deliver_profile(
        self, tree, paths: BuildPaths, *, iso_name: str, on_progress=None
    ) -> None:
        """Als Archiv hinueber und dort auspacken.

        Nicht als Verzeichnis ueber den Netzwerkpfad: auf einem Windows-Laufwerk
        gingen die symbolischen Verknuepfungen verloren, und das Abbild koennte
        keine Dienste aktivieren.
        """
        from .wsl_build import transfer_profile

        if on_progress is not None:
            on_progress(0.3, "Archiv wird gepackt")
        transfer_profile(self.wsl, tree, self._paths, iso_name)
        if on_progress is not None:
            on_progress(
                1.0, f"{tree.symlink_count} Verknuepfungen uebernommen"
            )

    def discard(
        self, paths: BuildPaths, *, keep_work_dir: bool, remove_output: bool
    ) -> None:
        from .wsl_build import cleanup

        if getattr(self, "_paths", None) is None:
            return
        cleanup(
            self.wsl,
            self._paths,
            keep_work_dir=keep_work_dir,
            remove_output=remove_output,
        )

    def preflight(self, work_dir, out_dir, *, installed_mb=0, bootmodes=()):
        from .preflight import run_wsl_preflight

        # bootmodes wird jetzt durchgereicht. Frueher kannte die WSL-Fassung den
        # Wert gar nicht -- ein Bau mit uefi.grub ohne grub-mkstandalone lief
        # deshalb an, statt vorher zu blockieren.
        return run_wsl_preflight(
            self.wsl, out_dir, installed_mb=installed_mb, bootmodes=bootmodes
        )

    def cancel_run(self, process, *, grace_seconds: float) -> None:
        """Den Bau drueben beenden, nicht nur den Client hier.

        ``wsl.exe`` ist kein Signalweiterleiter. Es zu beenden schliesst zwar die
        Pipe -- mkarchiso laeuft in der Verteilung aber ungestoert weiter, denn
        pacstrap und mksquashfs haengen dort an init, nicht am Windows-Prozess.
        Nach einem Abbruch blieben so ein laufender Bau und mehrere Gigabyte
        Arbeitsverzeichnis in der virtuellen Platte zurueck.

        Deshalb zuerst drueben, dann hier. Die Reihenfolge ist wichtig: ist der
        Client erst tot, fuehrt kein Weg mehr hinein.
        """
        try:
            self.wsl.run(["pkill", "-TERM", "-f", "mkarchiso"], timeout=30.0)
        except Exception:
            log.warning("Abbruch in der Verteilung fehlgeschlagen", exc_info=True)

        if process is not None and process.poll() is None:
            frist = time.monotonic() + grace_seconds
            while time.monotonic() < frist:
                if process.poll() is not None:
                    break
                time.sleep(0.2)
            else:
                try:
                    self.wsl.run(["pkill", "-KILL", "-f", "mkarchiso"], timeout=30.0)
                except Exception:
                    log.debug("hartes Beenden fehlgeschlagen", exc_info=True)
            try:
                process.terminate()
            except OSError:
                pass



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



class ContainerExecutionTarget:
    """mkarchiso laeuft in einem Container mit dem archlinux-Abbild.

    Der Weg fuer jedes Linux, das kein Arch ist -- und ueber Docker Desktop auch
    fuer macOS. Der Gedanke ist derselbe wie bei WSL: nicht das Zielsystem
    arch-faehig machen, sondern ein Arch danebenstellen.

    Anders als bei WSL wird das Profil **nicht** uebertragen. Arbeits- und
    Ausgabeverzeichnis werden unter demselben Pfad in den Container eingehaengt;
    damit sind Host-Pfad und Containerpfad identisch, und fuenf der sieben
    Protokollmethoden sind woertlich die von ``LocalTarget``. Die 166 Zeilen
    Uebertragungscode aus ``wsl_build.py`` entfallen ersatzlos.
    """

    def __init__(self, container_target, *, privileged: bool = True) -> None:
        self.container = container_target
        self.privileged = privileged
        self.name = f"{container_target.engine}:archiso"
        self._work_dir: Path | None = None
        self._out_dir: Path | None = None
        self._container_name = ""

    # -- Aufruf ---------------------------------------------------------------
    def resolve_executable(self) -> str:
        # Im Abbild liegt es an der ueblichen Stelle; gepruefte Verfuegbarkeit
        # ist Sache der Vorabpruefung.
        return "mkarchiso"

    def _mount(self, pfad: Path) -> str:
        """Ein Bind-Mount, auf SELinux-Systemen mit Kennzeichnung.

        Ohne ``:Z`` scheitert der Bau auf Fedora mit "Permission denied", ohne
        dass im Container etwas darauf hindeutet. Auf allen anderen Systemen
        waere die Kennzeichnung wirkungslos bis stoerend, deshalb nur dort.
        """
        from .container import selinux_active

        endung = ":Z" if selinux_active() else ""
        return f"{pfad}:{pfad}{endung}"

    def wrap(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None
    ) -> list[str]:
        befehl = [
            self.container.engine, "run", "--rm",
            # Ohne festen Namen gibt es beim Abbrechen nichts zu toeten.
            "--name", self._container_name,
        ]
        if self.privileged:
            # pacstrap haengt acht Dateisysteme ein und braucht dafuer
            # CAP_SYS_ADMIN. Siehe container.py fuer die ganze Begruendung.
            befehl.append("--privileged")
        for verzeichnis in (self._work_dir, self._out_dir):
            if verzeichnis is not None:
                befehl += ["-v", self._mount(verzeichnis)]
        for schluessel, wert in sorted((env or {}).items()):
            if not _VALID_ENV_NAME.match(schluessel):
                raise ValueError(f"unzulaessiger Variablenname: {schluessel!r}")
            befehl += ["-e", f"{schluessel}={wert}"]
        return [*befehl, self.container.image, *[str(item) for item in argv]]

    def make_dirs(self, *paths: str) -> None:
        # Host-Pfade -- die Verzeichnisse entstehen hier, der Container sieht sie
        # durch den Mount.
        for pfad in paths:
            Path(pfad).mkdir(parents=True, exist_ok=True)

    def cwd(self) -> str | None:
        return None

    def sanitize_environment(self, env: dict[str, str]) -> dict[str, str]:
        # Der Container erbt nichts; die Variablen gehen ueber -e mit.
        return env

    def find_iso(self, out_dir: str, expected: str) -> str | None:
        return LocalTarget().find_iso(out_dir, expected)

    def fetch_iso(self, remote_iso: str, destination: Path) -> Path:
        # Ueber den Bind-Mount liegt sie bereits auf dem Host.
        return Path(remote_iso)

    # -- Ablauf ---------------------------------------------------------------
    def preflight(self, work_dir, out_dir, *, installed_mb=0, bootmodes=()):
        from .preflight import run_container_preflight

        return run_container_preflight(
            self.container, work_dir, out_dir,
            installed_mb=installed_mb, bootmodes=bootmodes,
        )

    def prepare(self, iso_name: str, work_dir: Path, out_dir: Path) -> BuildPaths:
        from .container import container_name

        work_dir = Path(work_dir)
        out_dir = Path(out_dir)
        # Der Bind-Mount unter demselben Pfad setzt POSIX-Pfade voraus. Unter
        # Windows staende auf der einen Seite ein Laufwerksbuchstabe und auf der
        # anderen ein Pfad unterhalb von /mnt -- eine Zuordnung, die Docker
        # Desktop selbst vornimmt und die hier nur Fehler produzierte. Windows
        # hat mit WSL ohnehin den besseren Weg.
        for verzeichnis in (work_dir, out_dir):
            if ":" in str(verzeichnis):
                raise ValueError(
                    "Das Container-Ziel arbeitet mit POSIX-Pfaden; "
                    f"{verzeichnis} laesst sich so nicht einhaengen. "
                    "Unter Windows ist WSL der vorgesehene Weg."
                )
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._work_dir = work_dir
        self._out_dir = out_dir
        self._container_name = container_name(iso_name)
        # Dieselben Pfade wie auf dem Host -- das ist der ganze Trick.
        return BuildPaths(
            profile=str(work_dir / PROFILE_DIRNAME),
            work=str(work_dir / "work"),
            out=str(out_dir),
        )

    def deliver_profile(
        self, tree, paths: BuildPaths, *, iso_name: str, on_progress=None
    ) -> None:
        # Woertlich der lokale Fall: das Verzeichnis ist ueber den Mount dasselbe.
        LocalTarget().deliver_profile(
            tree, paths, iso_name=iso_name, on_progress=on_progress
        )

    def discard(
        self, paths: BuildPaths, *, keep_work_dir: bool, remove_output: bool
    ) -> None:
        if self._container_name:
            try:
                self.container.remove(self._container_name)
            except Exception:
                log.debug("Container war schon weg", exc_info=True)
        # remove_output ist hier bedeutungslos: die Ausgabe liegt ueber den
        # Bind-Mount schon am Zielort.
        LocalTarget().discard(paths, keep_work_dir=keep_work_dir, remove_output=False)

    def cancel_run(self, process, *, grace_seconds: float) -> None:
        """Den Container beenden, nicht den Client.

        ``terminate()`` auf den podman-Prozess traefe nur den Client -- der
        Container mit dem laufenden pacstrap ueberlebt ihn im conmon-Baum.
        """
        if self._container_name:
            try:
                self.container.kill(self._container_name, signal="TERM")
            except Exception:
                log.warning("Container liess sich nicht beenden", exc_info=True)

        if process is not None and process.poll() is None:
            frist = time.monotonic() + grace_seconds
            while time.monotonic() < frist and process.poll() is None:
                time.sleep(0.2)
            if process.poll() is None and self._container_name:
                try:
                    self.container.remove(self._container_name)
                except Exception:
                    log.debug("hartes Entfernen fehlgeschlagen", exc_info=True)
            try:
                process.terminate()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Zielwahl
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TargetOption:
    """Ein moeglicher Bauweg auf diesem Rechner -- oder die Erklaerung, warum nicht."""

    kind: str                     # "lokal" | "wsl" | "container"
    label: str                    # eine Zeile fuer den Benutzer
    target: "ExecutionTarget | None" = None
    problem: str = ""             # gefuellt, wenn dieser Weg hier nicht geht
    remedy: str = ""              # was der Benutzer dagegen tun kann

    @property
    def usable(self) -> bool:
        return self.target is not None


def available_targets() -> list[TargetOption]:
    """Was auf diesem Rechner in Frage kommt -- nach Vorzug geordnet.

    Frueher entschied die Oberflaeche an ``sys.platform``: alles ausser Linux
    ging in den WSL-Dialog. Ein Mac-Benutzer las daraufhin zwei Bildschirme
    lang, er solle Windows neu starten.

    Die Frage ist aber nicht "welches Betriebssystem", sondern "was liegt hier
    vor". Genau das beantwortet diese Funktion -- und der Benutzer waehlt
    nichts, er bekommt den besten Weg und einen Satz dazu.

    Achtung: der Aufruf kann Sekunden dauern (``wsl.exe`` bis zu einer Minute,
    ``podman info`` einen Moment). Er gehoert deshalb in einen Hintergrundfaden.
    """
    import sys

    optionen: list[TargetOption] = []

    # 1. Direkt hier -- wenn dies ein Arch-System mit archiso ist. Der
    #    schnellste Weg, ohne jede Zwischenschicht.
    if sys.platform == "linux":
        optionen.append(_probe_local())

    # 2. Windows: WSL. Dort ist es der vorgesehene Weg, und ein Container
    #    brauchte Docker Desktop, das seinerseits auf WSL2 aufsetzt.
    if sys.platform == "win32":
        optionen.append(_probe_wsl())

    # 3. Container -- fuer jedes Linux, das kein Arch ist, und fuer macOS.
    #    Unter Windows nicht: dort gaebe es keine gueltige Pfadzuordnung.
    if sys.platform != "win32":
        optionen.append(_probe_container())

    return sorted(optionen, key=lambda o: not o.usable)


def _probe_local() -> TargetOption:
    from ..environment import detect_environment

    # Eine Erkennung darf die Zielwahl nie mitreissen: faellt sie aus, gilt
    # dieser Weg als nicht verfuegbar, und die anderen werden trotzdem geprueft.
    try:
        umgebung = detect_environment()
    except Exception:
        log.debug("Umgebungserkennung fehlgeschlagen", exc_info=True)
        return TargetOption(
            "lokal",
            "Direkt auf diesem Rechner",
            problem="Die Umgebung liess sich nicht pruefen.",
        )
    if umgebung.can_build:
        return TargetOption(
            "lokal",
            "Direkt auf diesem Rechner -- archiso ist vorhanden.",
            target=LocalTarget(),
        )
    if not umgebung.pacman_available:
        return TargetOption(
            "lokal",
            "Direkt auf diesem Rechner",
            problem="Dieses System ist kein Arch Linux.",
            remedy="",
        )
    fehlend = ", ".join(werkzeug.name for werkzeug in umgebung.missing_required)
    return TargetOption(
        "lokal",
        "Direkt auf diesem Rechner",
        problem=f"Es fehlen: {fehlend}.",
        remedy=umgebung.install_hint(),
    )


def _probe_wsl() -> TargetOption:
    from . import wsl

    try:
        status = wsl.detect()
    except Exception:
        log.debug("WSL-Erkennung fehlgeschlagen", exc_info=True)
        return TargetOption(
            "wsl", "Im Linux-Untersystem (WSL)", problem="WSL ist nicht erreichbar."
        )

    gefunden = status.find_arch() if status.installed else None
    if gefunden is not None:
        return TargetOption(
            "wsl",
            f"Im Linux-Untersystem ({gefunden.name}).",
            target=WslExecutionTarget(wsl.WslTarget(gefunden.name)),
        )
    return TargetOption(
        "wsl",
        "Im Linux-Untersystem (WSL)",
        problem=status.problem or "Es ist keine Arch-Verteilung eingerichtet.",
        remedy="wsl --install archlinux",
    )


def _probe_container() -> TargetOption:
    from .container import ContainerTarget, detect

    try:
        status = detect()
    except Exception:
        log.debug("Container-Erkennung fehlgeschlagen", exc_info=True)
        return TargetOption(
            "container", "In einem Container", problem="Nicht erreichbar."
        )

    if status.usable and status.engine:
        zusatz = "" if status.image_ready else " Das Abbild wird beim ersten Mal erzeugt."
        return TargetOption(
            "container",
            f"In einem Container mit {status.engine}.{zusatz}",
            target=ContainerExecutionTarget(ContainerTarget(status.engine)),
        )
    return TargetOption(
        "container",
        "In einem Container",
        problem=status.problem or "Es ist keine Container-Umgebung eingerichtet.",
        remedy=status.remedy or "sudo apt install podman",
    )


def best_target() -> TargetOption | None:
    """Der bevorzugte brauchbare Weg -- oder ``None``, wenn keiner geht."""
    for option in available_targets():
        if option.usable:
            return option
    return None
