"""Pruefungen vor dem Start eines Builds.

Ein ISO-Build dauert je nach Auswahl zwanzig Minuten bis eine Stunde. Fehler,
die sich vorher erkennen lassen, jetzt zu melden ist ungleich freundlicher, als
den Benutzer eine halbe Stunde warten und dann scheitern zu lassen.

Geprueft wird deshalb alles, was ohne Ausfuehrung feststellbar ist: Werkzeuge,
Rechte, Plattenplatz, Dateisystem und ein bereits vorhandenes
Arbeitsverzeichnis.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..environment import Environment, detect_environment
from .errors import NotEnoughSpace, PreflightError

log = logging.getLogger(__name__)

# Erfahrungswerte. Das Arbeitsverzeichnis enthaelt zeitweise das entpackte
# System UND das komprimierte Abbild UND die ISO-Struktur.
BASE_WORK_GB = 8.0
SIZE_FACTOR = 4.0


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    fatal: bool = True


@dataclass(slots=True)
class PreflightReport:
    checks: list[Check] = field(default_factory=list)
    environment: Environment | None = None
    privilege_mode: str = "unavailable"
    estimated_work_gb: float = BASE_WORK_GB

    @property
    def blocking(self) -> list[Check]:
        return [check for check in self.checks if not check.ok and check.fatal]

    @property
    def warnings(self) -> list[Check]:
        return [check for check in self.checks if not check.ok and not check.fatal]

    @property
    def ok(self) -> bool:
        return not self.blocking

    def raise_if_blocked(self) -> None:
        if self.ok:
            return
        first = self.blocking[0]
        raise PreflightError(
            first.detail or f"{first.name} ist nicht erfuellt.",
            tuple(check.detail for check in self.blocking[1:]),
            technical="; ".join(f"{c.name}: {c.detail}" for c in self.blocking),
        )


def estimate_work_space_gb(installed_mb: int) -> float:
    """Wie viel Platz das Arbeitsverzeichnis braucht.

    Faustregel: das entpackte System liegt dort einmal vollstaendig, dazu das
    komprimierte Abbild und die ISO-Struktur. Vier mal die geschaetzte
    Installationsgroesse plus ein Sockel ist erfahrungsgemaess knapp genug, um
    zu warnen, und grosszuegig genug, um nicht zu nerven.
    """
    return BASE_WORK_GB + (installed_mb / 1024.0) * SIZE_FACTOR


def free_space_gb(path: Path) -> float | None:
    """Freier Platz an der naechsten existierenden Stelle des Pfades."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free / 1_073_741_824
    except OSError:
        return None


def run_preflight(
    work_dir: Path,
    out_dir: Path,
    *,
    installed_mb: int = 0,
    environment: Environment | None = None,
) -> PreflightReport:
    """Sammelt alle Befunde, ohne beim ersten Problem abzubrechen.

    Der Benutzer soll alles auf einmal sehen und nicht nach jeder Korrektur
    einen neuen Fehler praesentiert bekommen.
    """
    env = environment or detect_environment()
    report = PreflightReport(environment=env, privilege_mode=env.privilege_mode)
    needed = estimate_work_space_gb(installed_mb)
    report.estimated_work_gb = needed

    # -- Plattform ------------------------------------------------------------
    if sys.platform != "linux":
        report.checks.append(
            Check(
                "Betriebssystem",
                False,
                "Ein ISO-Build laeuft nur unter Linux -- archiso, pacman und "
                "mkarchiso sind Linux-Werkzeuge. Das erzeugte Profil laesst sich "
                "aber auf ein Arch-System uebertragen und dort bauen.",
            )
        )
        return report

    # -- Werkzeuge ------------------------------------------------------------
    missing = [tool.name for tool in env.missing_required]
    report.checks.append(
        Check(
            "Werkzeuge",
            not missing,
            (
                f"Es fehlen: {', '.join(missing)}.\n{env.install_hint()}"
                if missing
                else f"{len(env.tools)} geprueft"
            ),
        )
    )

    # -- Rechte ---------------------------------------------------------------
    if env.privilege_mode == "unavailable":
        report.checks.append(
            Check(
                "Rechte",
                False,
                "Weder ein Build ohne Administratorrechte noch pkexec sind "
                "verfuegbar. Entweder Sub-ID-Bereiche einrichten oder polkit "
                "installieren.",
            )
        )
    else:
        report.checks.append(
            Check("Rechte", True, f"Modus: {env.privilege_mode}", fatal=False)
        )
        if env.privilege_mode == "pkexec":
            report.checks.append(
                Check(
                    "Rechte ohne Root",
                    False,
                    "Der Build laeuft mit erhoehten Rechten ueber pkexec, weil "
                    "Sub-ID-Bereiche fehlen. Ohne Root ginge es mit: "
                    "sudo usermod --add-subuids 100000-165535 "
                    "--add-subgids 100000-165535 $USER",
                    fatal=False,
                )
            )

    # -- Plattenplatz ---------------------------------------------------------
    available = free_space_gb(work_dir)
    if available is None:
        report.checks.append(
            Check("Plattenplatz", False, f"{work_dir} ist nicht erreichbar.")
        )
    elif available < needed:
        report.checks.append(
            Check(
                "Plattenplatz",
                False,
                f"In {work_dir} sind {available:.1f} GB frei, gebraucht werden "
                f"etwa {needed:.0f} GB.",
            )
        )
    else:
        report.checks.append(
            Check("Plattenplatz", True, f"{available:.0f} GB frei, ~{needed:.0f} GB noetig", fatal=False)
        )

    # -- Dateisystem ----------------------------------------------------------
    # Das Arbeitsverzeichnis braucht erweiterte Attribute und echte
    # Benutzerkennungen. Auf einer FAT- oder NTFS-Partition scheitert der Build
    # mitten im Entpacken der Pakete.
    filesystem = _filesystem_of(work_dir)
    if filesystem and filesystem.lower() in ("vfat", "fat32", "exfat", "ntfs", "fuseblk"):
        report.checks.append(
            Check(
                "Dateisystem",
                False,
                f"{work_dir} liegt auf {filesystem}. Das Arbeitsverzeichnis braucht "
                f"ein Linux-Dateisystem (ext4, btrfs, xfs) -- sonst gehen "
                f"Dateirechte und Eigentuemer beim Entpacken verloren.",
            )
        )
    elif filesystem:
        report.checks.append(Check("Dateisystem", True, filesystem, fatal=False))

    # -- Vorhandenes Arbeitsverzeichnis --------------------------------------
    if work_dir.exists() and any(work_dir.iterdir()):
        report.checks.append(
            Check(
                "Arbeitsverzeichnis",
                False,
                f"{work_dir} ist nicht leer. mkarchiso setzt einen frueheren Lauf "
                f"fort und uebernimmt dabei dessen Baudatum -- das Ergebnis "
                f"koennte veraltete Teile enthalten. Besser vorher loeschen.",
                fatal=False,
            )
        )

    # -- Ausgabeverzeichnis ---------------------------------------------------
    probe = out_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not os.access(probe, os.W_OK):
        report.checks.append(
            Check("Ausgabeverzeichnis", False, f"Keine Schreibrechte in {probe}.")
        )

    log.info(
        "Vorabpruefung: %s (%d Beanstandungen, %d Hinweise)",
        "bestanden" if report.ok else "nicht bestanden",
        len(report.blocking),
        len(report.warnings),
    )
    return report


def _filesystem_of(path: Path) -> str:
    """Dateisystemtyp aus /proc/mounts -- ohne Fremdbibliothek.

    Gesucht wird der laengste passende Einhaengepunkt, weil verschachtelte
    Einhaengungen sonst falsch zugeordnet wuerden.
    """
    mounts = Path("/proc/mounts")
    if not mounts.is_file():
        return ""

    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        resolved = probe.resolve()
    except OSError:
        return ""

    best = ""
    best_length = -1
    try:
        for line in mounts.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mount_point, filesystem = parts[1], parts[2]
            try:
                point = Path(mount_point)
            except ValueError:
                continue
            if resolved == point or point in resolved.parents:
                if len(mount_point) > best_length:
                    best, best_length = filesystem, len(mount_point)
    except OSError:
        return ""
    return best


# ---------------------------------------------------------------------------
# Vorabpruefung fuer einen Bau in WSL
# ---------------------------------------------------------------------------


def run_wsl_preflight(
    wsl_target,
    out_dir: Path,
    *,
    installed_mb: int = 0,
) -> PreflightReport:
    """Prueft die WSL-Verteilung statt des Windows-Systems.

    Beim Bau in WSL liegen Werkzeuge, Plattenplatz und Rechte alle drueben.
    Das Windows-System zu pruefen waere irrefuehrend -- dort fehlt mkarchiso
    zwangslaeufig, ohne dass das ein Hindernis waere.
    """
    from .wsl import check_readiness

    needed = estimate_work_space_gb(installed_mb)
    report = PreflightReport(privilege_mode="rootless", estimated_work_gb=needed)
    readiness = check_readiness(wsl_target, needed_gb=needed)

    report.checks.append(
        Check(
            "Linux-Verteilung",
            readiness.is_arch,
            f"{wsl_target.distribution}"
            + ("" if readiness.is_arch else " -- kein Arch Linux"),
        )
    )
    if not readiness.is_arch:
        return report

    report.checks.append(
        Check(
            "archiso",
            readiness.has_archiso,
            "vorhanden"
            if readiness.has_archiso
            else "fehlt. In der Verteilung installieren mit:\n"
                 "sudo pacman -Syu --needed archiso",
        )
    )
    report.checks.append(
        Check("tar", readiness.has_tar, "vorhanden" if readiness.has_tar else "fehlt", )
    )

    if readiness.free_gb is not None:
        enough = readiness.free_gb >= needed
        report.checks.append(
            Check(
                "Plattenplatz",
                enough,
                f"{readiness.free_gb:.0f} GB frei in der Verteilung, "
                f"~{needed:.0f} GB noetig"
                + (
                    ""
                    if enough
                    else ". WSL legt seine virtuelle Platte auf C: ab -- dort muss "
                         "der Platz vorhanden sein."
                ),
            )
        )

    # Ohne Sub-IDs laeuft der Build mit erhoehten Rechten weiter, das ist kein
    # Hindernis -- aber der Hinweis spart eine Rueckfrage.
    report.checks.append(
        Check(
            "Rechte ohne Root",
            readiness.subid_ready,
            "eingerichtet"
            if readiness.subid_ready
            else "Sub-ID-Bereiche fehlen. Einmalig in der Verteilung:\n"
                 "sudo usermod --add-subuids 100000-165535 "
                 "--add-subgids 100000-165535 $USER",
            fatal=False,
        )
    )
    if not readiness.userns_ready:
        report.checks.append(
            Check(
                "User-Namespaces",
                False,
                "In dieser Verteilung sind User-Namespaces abgeschaltet.",
                fatal=False,
            )
        )

    # Das Ausgabeverzeichnis liegt auf der Windows-Seite.
    probe = out_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    writable = os.access(probe, os.W_OK)
    report.checks.append(
        Check(
            "Ausgabeverzeichnis",
            writable,
            str(out_dir) if writable else f"Keine Schreibrechte in {probe}.",
        )
    )
    return report
