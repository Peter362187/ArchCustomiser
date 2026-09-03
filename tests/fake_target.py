"""Ein aufzeichnendes ``ExecutionTarget`` fuer die Tests.

Dieser Baustein fehlte. ``FakeWsl`` in ``test_wsl.py`` ersetzt ``WslTarget``,
also die Ebene *unter* dem Protokoll, und wird dort immer in ein echtes
``WslExecutionTarget`` gewickelt. Ein drittes Ziel liess sich damit nicht
nachbilden -- ein Container hat keine ``wsl.exe``-artige Schnittstelle.

Die Folge war eine Luecke: der ``BuildController`` wurde nie mit einem anderen
Ziel als ``LocalTarget`` geprueft. Alle zielabhaengigen Schritte -- Profil
ablegen, aufraeumen, abbrechen -- waren ueber den Controller ungetestet, genau
die Stellen also, die beim Umbau auf drei Ziele wandern mussten.

``FakeTarget`` schreibt jeden Aufruf in ``self.calls`` mit. Damit laesst sich
pruefen, *dass* der Controller den richtigen Schritt am Ziel ausloest, ohne dass
irgendwo ein Prozess starten muss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from archcustomiser.core.build.preflight import PreflightReport
from archcustomiser.core.build.targets import BuildPaths


class FakeTarget:
    """Erfuellt das Protokoll vollstaendig und tut dabei nichts."""

    def __init__(
        self,
        name: str = "fake",
        *,
        report: PreflightReport | None = None,
        iso: str | None = None,
    ) -> None:
        self.name = name
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._report = report or PreflightReport()
        self._iso = iso
        self.paths: BuildPaths | None = None

    # -- Aufzeichnung ---------------------------------------------------------
    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def called(self, name: str) -> bool:
        return any(eintrag[0] == name for eintrag in self.calls)

    def call(self, name: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
        """Argumente des ersten Aufrufs -- wirft, wenn er nie kam."""
        for eintrag in self.calls:
            if eintrag[0] == name:
                return eintrag[1], eintrag[2]
        raise AssertionError(f"{name} wurde nie aufgerufen; da war: {self.order()}")

    def order(self) -> list[str]:
        return [eintrag[0] for eintrag in self.calls]

    # -- Protokoll ------------------------------------------------------------
    def resolve_executable(self) -> str:
        self._record("resolve_executable")
        return "/usr/bin/mkarchiso"

    def wrap(self, argv, *, env=None) -> list[str]:
        self._record("wrap", list(argv), env=env)
        return [str(item) for item in argv]

    def make_dirs(self, *paths: str) -> None:
        self._record("make_dirs", *paths)

    def cwd(self) -> str | None:
        return None

    def sanitize_environment(self, env: dict[str, str]) -> dict[str, str]:
        return env

    def find_iso(self, out_dir: str, expected: str) -> str | None:
        self._record("find_iso", out_dir, expected)
        return self._iso

    def fetch_iso(self, remote_iso: str, destination: Path) -> Path:
        self._record("fetch_iso", remote_iso, destination)
        return destination

    def preflight(self, work_dir, out_dir, *, installed_mb=0, bootmodes=()) -> PreflightReport:
        self._record(
            "preflight", work_dir, out_dir,
            installed_mb=installed_mb, bootmodes=tuple(bootmodes),
        )
        return self._report

    def prepare(self, iso_name: str, work_dir: Path, out_dir: Path) -> BuildPaths:
        self._record("prepare", iso_name, work_dir, out_dir)
        self.paths = BuildPaths(
            profile=f"/fake/{iso_name}/profile",
            work=f"/fake/{iso_name}/work",
            out=f"/fake/{iso_name}/out",
        )
        return self.paths

    def deliver_profile(self, tree, paths, *, iso_name, on_progress=None) -> None:
        self._record("deliver_profile", paths, iso_name=iso_name)
        if on_progress is not None:
            on_progress(1.0, "nachgebildet")

    def discard(self, paths, *, keep_work_dir: bool, remove_output: bool) -> None:
        self._record(
            "discard", paths, keep_work_dir=keep_work_dir, remove_output=remove_output
        )

    def cancel_run(self, process, *, grace_seconds: float) -> None:
        self._record("cancel_run", process, grace_seconds=grace_seconds)
