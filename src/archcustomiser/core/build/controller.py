"""Der vollstaendige Ablauf vom Wizard zur fertigen ISO.

Fuenf Schritte, jeder mit eigenem Fortschrittsanteil:

1. **Vorabpruefung** -- Werkzeuge, Rechte, Plattenplatz, Dateisystem.
2. **Profil erzeugen** -- derselbe Generator wie beim Export.
3. **Profil schreiben** -- in ein temporaeres Verzeichnis unterhalb des
   Arbeitsverzeichnisses.
4. **mkarchiso** -- der lange Teil, rund 95 Prozent der Zeit.
5. **Aufraeumen** -- das Arbeitsverzeichnis, sofern gewuenscht.

Bewusst *ein* Ablauf und nicht zwei getrennte Knoepfe: die Profilerzeugung ist
Voraussetzung fuer den Build und dauert Millisekunden. Wer die ISO will, will
nicht vorher noch ein Verzeichnis auswaehlen.

Das Protokoll wird waehrend des Laufs geschrieben, nicht danach. Bei einem
Abbruch nach vierzig Minuten ist gerade das Protokoll das Einzige, was noch
hilft.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

from ..archiso import DirectorySink, GeneratedProfile, ProfileGenerator
from ..archiso.errors import ProfileError
from ..catalog import Catalog
from ..config import BuildConfig
from ..resolver import Resolution
from ..secrets import SecretStore
from .errors import BuildCancelled, BuildError, BuildFailed, PreflightError
from .preflight import PreflightReport, run_preflight
from .progress import ProgressState
from .runner import BuildResult, MkarchisoRunner
from .targets import ExecutionTarget, LocalTarget, WslExecutionTarget

log = logging.getLogger(__name__)

PROFILE_DIRNAME = "profile"


class Step(str, Enum):
    PREFLIGHT = "preflight"
    GENERATE = "generate"
    WRITE = "write"
    MKARCHISO = "mkarchiso"
    CLEANUP = "cleanup"


# Anteil jedes Schrittes am Gesamtfortschritt. mkarchiso dominiert so deutlich,
# dass alles andere zusammen unter fuenf Prozent bleibt.
WEIGHTS: dict[Step, tuple[float, float]] = {
    Step.PREFLIGHT: (0.00, 0.01),
    Step.GENERATE: (0.01, 0.02),
    Step.WRITE: (0.02, 0.04),
    Step.MKARCHISO: (0.04, 0.98),
    Step.CLEANUP: (0.98, 1.00),
}

StepCallback = Callable[[Step, str], None]
ProgressCallback = Callable[[float, str, str], None]   # (0..1, Titel, Detail)
LineCallback = Callable[[str], None]


@dataclass(slots=True)
class BuildOutcome:
    profile: GeneratedProfile | None = None
    result: BuildResult | None = None
    log_path: Path | None = None
    preflight: PreflightReport | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def iso_path(self) -> Path | None:
        return self.result.iso_path if self.result else None

    @property
    def succeeded(self) -> bool:
        return self.result is not None and self.result.succeeded


class BuildController:
    """Fuehrt den gesamten Ablauf aus. Synchron und ohne Qt."""

    def __init__(
        self,
        catalog: Catalog,
        config: BuildConfig,
        resolution: Resolution,
        secrets: SecretStore | None = None,
        *,
        runner_factory: Callable[..., MkarchisoRunner] | None = None,
        target: ExecutionTarget | None = None,
    ) -> None:
        self.catalog = catalog
        self.config = config
        self.resolution = resolution
        self.secrets = secrets
        # Einhaengepunkt fuer die Tests: der Ablauf laesst sich damit
        # vollstaendig pruefen, ohne mkarchiso zu haben.
        self.runner_factory = runner_factory or MkarchisoRunner
        # Wo gebaut wird: hier oder in einer WSL-Verteilung nebenan.
        self.target: ExecutionTarget = target or LocalTarget()
        self._wsl_paths = None
        self._output_fetched = False
        self._runner: MkarchisoRunner | None = None
        self._cancelled = False
        self._lines: list[str] = []

    # -- oeffentlich ----------------------------------------------------------
    def preflight(self, work_dir: Path, out_dir: Path) -> PreflightReport:
        """Prueft dort, wo tatsaechlich gebaut wird.

        Bei einem Bau in WSL waere eine Pruefung des Windows-Systems
        irrefuehrend: die Werkzeuge, der Plattenplatz und die Rechte liegen
        alle in der Verteilung.
        """
        if isinstance(self.target, WslExecutionTarget):
            from .preflight import run_wsl_preflight

            return run_wsl_preflight(
                self.target.wsl,
                out_dir,
                installed_mb=self.resolution.estimated_size_mb,
            )
        return run_preflight(
            work_dir, out_dir, installed_mb=self.resolution.estimated_size_mb
        )

    def run(
        self,
        work_dir: Path,
        out_dir: Path,
        *,
        keep_work_dir: bool = False,
        on_step: StepCallback | None = None,
        on_progress: ProgressCallback | None = None,
        on_line: LineCallback | None = None,
        skip_preflight: bool = False,
    ) -> BuildOutcome:
        outcome = BuildOutcome()
        started = time.monotonic()
        work_dir = Path(work_dir)
        out_dir = Path(out_dir)

        try:
            # 1 -- Vorabpruefung
            self._announce(on_step, on_progress, Step.PREFLIGHT, "Umgebung wird geprueft")
            report = self.preflight(work_dir, out_dir)
            outcome.preflight = report
            outcome.warnings.extend(check.detail for check in report.warnings)
            if not skip_preflight:
                report.raise_if_blocked()
            self._check_cancel()

            # 2 -- Profil erzeugen
            self._announce(on_step, on_progress, Step.GENERATE, "Profil wird erzeugt")
            profile = ProfileGenerator(
                self.catalog, self.config, self.resolution, self.secrets
            ).generate()
            outcome.profile = profile
            outcome.warnings.extend(profile.warnings)
            self._check_cancel()

            # 3 -- Profil dorthin bringen, wo gebaut wird
            self._announce(on_step, on_progress, Step.WRITE, "Profil wird uebertragen")
            build_paths = self._place_profile(profile, work_dir, out_dir, on_progress)
            self._check_cancel()

            # 4 -- der eigentliche Build
            self._announce(on_step, on_progress, Step.MKARCHISO, "ISO wird gebaut")
            profile_path, work_path, out_path = build_paths
            runner = self.runner_factory(
                profile_path,
                work_path,
                out_path,
                privilege_mode=report.privilege_mode,
                source_date_epoch=int(datetime.now(timezone.utc).timestamp()),
                target=self.target,
            )
            self._runner = runner
            result = runner.run(
                on_line=lambda line: self._record(line, on_line),
                on_progress=lambda state: self._mkarchiso_progress(on_progress, state),
                expected_iso=profile.iso_filename,
            )

            # Bei einem Bau in WSL liegt die ISO noch drueben. Erst nach dem
            # Holen gibt es einen Pfad auf diesem Rechner.
            if result.iso_location:
                result.iso_path = self.target.fetch_iso(
                    result.iso_location, out_dir / profile.iso_filename
                )
                # Erst jetzt darf die Kopie drueben weg.
                self._output_fetched = True
            outcome.result = result

            # 5 -- Aufraeumen
            self._announce(on_step, on_progress, Step.CLEANUP, "Aufraeumen")
            self._cleanup_all(work_dir, keep_work_dir=keep_work_dir)
            if on_progress is not None:
                on_progress(1.0, "Fertig", f"{result.size_mb:.0f} MB")

        except BuildCancelled:
            outcome.log_path = self._write_log(outcome, cancelled=True)
            raise
        except (BuildError, ProfileError) as exc:
            outcome.log_path = self._write_log(outcome, error=exc)
            raise
        else:
            outcome.log_path = self._write_log(
                outcome, duration=time.monotonic() - started
            )
            return outcome
        finally:
            self._runner = None

    def cancel(self) -> None:
        self._cancelled = True
        if self._runner is not None:
            self._runner.cancel()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # -- intern ---------------------------------------------------------------
    def _check_cancel(self) -> None:
        if self._cancelled:
            raise BuildCancelled()

    def _record(self, line: str, on_line: LineCallback | None) -> None:
        self._lines.append(line)
        if on_line is not None:
            on_line(line)

    def _announce(
        self,
        on_step: StepCallback | None,
        on_progress: ProgressCallback | None,
        step: Step,
        label: str,
    ) -> None:
        log.info("Schritt: %s -- %s", step.value, label)
        if on_step is not None:
            on_step(step, label)
        if on_progress is not None:
            on_progress(WEIGHTS[step][0], label, "")

    def _sub_progress(
        self,
        on_progress: ProgressCallback | None,
        step: Step,
        share: float,
        label: str,
        detail: str,
    ) -> None:
        if on_progress is None:
            return
        start, end = WEIGHTS[step]
        on_progress(start + (end - start) * min(1.0, max(0.0, share)), label, detail)

    def _mkarchiso_progress(
        self, on_progress: ProgressCallback | None, state: ProgressState
    ) -> None:
        if on_progress is None:
            return
        start, end = WEIGHTS[Step.MKARCHISO]
        on_progress(start + (end - start) * state.fraction, state.label, state.detail)

    def _place_profile(
        self,
        profile,
        work_dir: Path,
        out_dir: Path,
        on_progress: ProgressCallback | None,
    ) -> tuple[str, str, str]:
        """Bringt das Profil dorthin, wo mkarchiso es findet.

        Lokal: als Verzeichnis. In WSL: als Archiv hinueber und dort auspacken --
        auf einem Windows-Laufwerk gingen die symbolischen Verknuepfungen
        verloren, und das Abbild koennte keine Dienste aktivieren.
        """
        if isinstance(self.target, WslExecutionTarget):
            from .wsl_build import prepare_paths, transfer_profile

            paths = prepare_paths(self.target.wsl, profile.settings.iso_name)
            self._wsl_paths = paths
            if on_progress is not None:
                self._sub_progress(
                    on_progress, Step.WRITE, 0.3,
                    "Profil wird uebertragen", "Archiv wird gepackt",
                )
            transfer_profile(
                self.target.wsl, profile.tree, paths, profile.settings.iso_name
            )
            if on_progress is not None:
                self._sub_progress(
                    on_progress, Step.WRITE, 1.0,
                    "Profil wird uebertragen",
                    f"{profile.tree.symlink_count} Verknuepfungen uebernommen",
                )
            return paths.as_strings()

        profile_dir = work_dir / PROFILE_DIRNAME
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)
        DirectorySink(
            profile_dir, iso_name=profile.settings.iso_name, force=True
        ).write(
            profile.tree,
            progress=lambda done, total: self._sub_progress(
                on_progress, Step.WRITE, done / total if total else 1.0,
                "Profil wird geschrieben", f"{done} von {total} Dateien",
            ),
        )
        return str(profile_dir), str(work_dir / "work"), str(out_dir)

    def _cleanup_all(self, work_dir: Path, *, keep_work_dir: bool) -> None:
        if isinstance(self.target, WslExecutionTarget) and self._wsl_paths is not None:
            from .wsl_build import cleanup

            cleanup(
                self.target.wsl,
                self._wsl_paths,
                keep_work_dir=keep_work_dir,
                remove_output=self._output_fetched,
            )
            return
        if not keep_work_dir:
            self._cleanup(work_dir)

    def _cleanup(self, work_dir: Path) -> None:
        """Das Arbeitsverzeichnis loeschen.

        Bewusst selbst und nicht ueber ``mkarchiso -r``: der Schalter raeumt
        schon waehrend der ISO-Erzeugung auf und verweigert die Arbeit, wenn
        das Verzeichnis vorher existierte.
        """
        for name in ("work", PROFILE_DIRNAME):
            target = work_dir / name
            if not target.exists():
                continue
            try:
                shutil.rmtree(target)
                log.info("Aufgeraeumt: %s", target)
            except OSError as exc:
                # Ein misslungenes Aufraeumen darf einen erfolgreichen Build
                # nicht nachtraeglich zum Fehlschlag machen.
                log.warning("%s liess sich nicht loeschen: %s", target, exc)

    def _write_log(
        self,
        outcome: BuildOutcome,
        *,
        duration: float = 0.0,
        cancelled: bool = False,
        error: Exception | None = None,
    ) -> Path | None:
        from ..logging_setup import write_build_log

        if cancelled:
            status = "Abgebrochen"
        elif error is not None:
            status = f"Fehlgeschlagen: {error}"
        elif outcome.result is not None:
            status = (
                f"Erfolgreich in {duration / 60:.1f} Minuten\n"
                f"ISO:    {outcome.result.iso_path}\n"
                f"Groesse: {outcome.result.size_mb:.0f} MB"
            )
        else:
            status = "Unbekannt"

        sections = {"Ergebnis": status}
        if outcome.preflight is not None:
            sections["Vorabpruefung"] = "\n".join(
                f"  [{'ok  ' if c.ok else 'FEHL'}] {c.name}: {c.detail}"
                for c in outcome.preflight.checks
            )
        if outcome.profile is not None:
            sections["profiledef.sh"] = outcome.profile.tree.text("profiledef.sh")
        if outcome.warnings:
            sections["Hinweise"] = "\n".join(f"  - {w}" for w in outcome.warnings)
        if self._lines:
            # Die vollstaendige Ausgabe -- ohne sie ist ein Fehlschlag nach
            # vierzig Minuten nicht nachvollziehbar.
            sections["Ausgabe von mkarchiso"] = "\n".join(self._lines)

        name = outcome.profile.settings.iso_name if outcome.profile else "build"
        return write_build_log(name, sections)
