"""Qt-Anbindung der Profilerzeugung.

Der Generator ist synchron und Qt-frei. Hier bekommt er einen Worker-Thread:
ein grosses Profil hat mehrere hundert Dateien, und die Oberflaeche darf
waehrenddessen nicht einfrieren.

Dasselbe Muster wie in ``packages_worker.py`` -- ein ``QRunnable`` auf dem
globalen ``QThreadPool``, Ergebnisse ausschliesslich ueber Signale.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ..core.archiso import DirectorySink, GeneratedProfile, ProfileGenerator, TarSink
from ..core.archiso.errors import ProfileError
from ..core.catalog import Catalog
from ..core.config import BuildConfig
from ..core.resolver import Resolution
from ..core.secrets import SecretStore

log = logging.getLogger(__name__)


class _Signals(QObject):
    progress = Signal(int, int)          # (erledigt, gesamt)
    finished = Signal(object, object)    # (GeneratedProfile, Path)
    failed = Signal(object)              # ProfileError


class _ExportTask(QRunnable):
    def __init__(
        self,
        catalog: Catalog,
        config: BuildConfig,
        resolution: Resolution,
        secrets: SecretStore | None,
        target: Path,
        as_archive: bool,
        force: bool,
    ) -> None:
        super().__init__()
        self.catalog = catalog
        self.config = config
        self.resolution = resolution
        self.secrets = secrets
        self.target = target
        self.as_archive = as_archive
        self.force = force
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        try:
            profile = ProfileGenerator(
                self.catalog, self.config, self.resolution, self.secrets
            ).generate()

            if self.as_archive:
                sink = TarSink(self.target, root_name=f"{profile.settings.iso_name}-profil")
            else:
                sink = DirectorySink(
                    self.target, iso_name=profile.settings.iso_name, force=self.force
                )
            written = sink.write(
                profile.tree,
                progress=lambda done, total: self.signals.progress.emit(done, total),
            )
            _write_build_log(profile, written)
            self.signals.finished.emit(profile, written)
        except ProfileError as exc:
            log.warning("Profilerzeugung fehlgeschlagen: %s", exc.technical)
            self.signals.failed.emit(exc)
        except Exception as exc:                     # darf die Anwendung nie mitreissen
            log.exception("Unerwarteter Fehler bei der Profilerzeugung")
            self.signals.failed.emit(ProfileError(str(exc), repr(exc)))


class ProfileExporter(QObject):
    """Erzeugt und schreibt ein Profil im Hintergrund."""

    progress = Signal(int, int)
    finished = Signal(object, object)
    failed = Signal(object)

    def __init__(self, catalog: Catalog, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def export(
        self,
        config: BuildConfig,
        resolution: Resolution,
        target: Path,
        *,
        secrets: SecretStore | None = None,
        as_archive: bool = True,
        force: bool = False,
    ) -> None:
        if self._running:
            return
        self._running = True

        task = _ExportTask(
            self.catalog, config, resolution, secrets, target, as_archive, force
        )
        task.signals.progress.connect(self.progress)
        task.signals.finished.connect(self._on_finished)
        task.signals.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(task)

    def preview(
        self,
        config: BuildConfig,
        resolution: Resolution,
        secrets: SecretStore | None = None,
    ) -> GeneratedProfile:
        """Erzeugt den Baum, ohne etwas zu schreiben.

        Laeuft im Aufruferthread: der Baum entsteht rein im Speicher und ist in
        wenigen Millisekunden fertig -- ein Thread waere hier nur zusaetzliche
        Komplexitaet.
        """
        return ProfileGenerator(self.catalog, config, resolution, secrets).generate()

    def _on_finished(self, profile: object, path: object) -> None:
        self._running = False
        self.finished.emit(profile, path)

    def _on_failed(self, error: object) -> None:
        self._running = False
        self.failed.emit(error)


def _write_build_log(profile: GeneratedProfile, target: Path) -> None:
    """Protokolliert den Lauf in einer eigenen Datei.

    Damit laesst sich ein einzelner Erzeugungslauf weitergeben, ohne das ganze
    Programmprotokoll mitzuschicken -- und beim spaeteren echten ISO-Build
    haengt die mkarchiso-Ausgabe hier einfach hinten an.
    """
    from ..core.logging_setup import write_build_log

    entries = []
    for path in profile.tree.paths():
        link = profile.tree.symlink(path)
        if link is not None:
            entries.append(f"  l {path} -> {link.target}")
        else:
            entries.append(f"  f {path}  ({profile.tree.files[path].size} B)")

    try:
        write_build_log(
            profile.settings.iso_name,
            {
                "Ergebnis": (
                    f"Ziel:      {target}\n"
                    f"ISO waere: {profile.iso_filename}\n"
                    f"Umfang:    {profile.tree.describe()}"
                ),
                "Ergaenzte Pakete": "\n".join(
                    f"  + {entry.name}: {entry.reason}" for entry in profile.added_packages
                )
                or "  (keine)",
                "Hinweise": "\n".join(f"  - {w}" for w in profile.warnings) or "  (keine)",
                "Erzeugte Dateien": "\n".join(entries),
                "profiledef.sh": profile.tree.text("profiledef.sh"),
                "Naechster Schritt": f"  {profile.build_command()}",
            },
        )
    except Exception:
        # Ein fehlgeschlagenes Protokoll darf den Export nicht scheitern lassen.
        log.warning("Build-Protokoll konnte nicht geschrieben werden", exc_info=True)
