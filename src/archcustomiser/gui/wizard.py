"""Der Wizard.

``QWizard`` statt eigener Navigation, aus drei Gruenden:

* ``nextId()`` und der interne Seitenverlauf erledigen das Ueberspringen
  unsichtbarer Kategorien und die korrekte Zurueck-Navigation. Ein Eigenbau
  muesste den Verlaufsstapel samt Randfaellen nachbilden.
* ``isComplete()`` und ``validatePage()`` sind zwei bereits vorhandene,
  semantisch verschiedene Pruefebenen -- die eine sperrt den Weiter-Knopf live,
  die andere prueft beim Verlassen.
* Tastaturbedienung, Fokusreihenfolge und Escape-Verhalten sind geschenkt.

Seiten werden zur Laufzeit nie hinzugefuegt oder entfernt -- das wuerde den
Seitenverlauf zerstoeren. Unsichtbare Kategorien werden stattdessen in
``nextId()`` uebersprungen.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
    QWizard,
)

from ..core.catalog import Catalog, Category
from ..core.paths import ensure_dir, user_profiles_dir
from ..core.plan import plan_as_text
from ..core.logging_setup import log_file_path
from ..core.profiles import ProfileError, ProfileService
from . import theme
from .packages_worker import PackageController
from .pages.base import CatalogPageBase
from .pages.factory import PageFactory
from .pages.summary import SummaryPage
from .profile_worker import ProfileExporter
from .store import SelectionStore
from .build_worker import BuildJob
from .widgets.build_dialog import BuildDialog
from .widgets.export_dialog import ErrorDialog, ExportResultDialog
from .widgets.preflight_dialog import PreflightDialog
from .widgets.wsl_dialog import WslSetupDialog

log = logging.getLogger(__name__)


class StepSidebar(QWidget):
    """Schrittliste am linken Rand, mit Fehlermarkierung."""

    def __init__(self, categories: tuple[Category, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(7)

        title = QLabel("Schritte")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        for category in categories:
            label = QLabel(category.title)
            label.setStyleSheet(f"color: {theme.subtle()};")
            layout.addWidget(label)
            self._labels[category.id] = label
        layout.addStretch(1)
        self.setFixedWidth(190)

    def set_current(self, category_id: str) -> None:
        for key, label in self._labels.items():
            if key == category_id:
                label.setStyleSheet("color: palette(text); font-weight: 600;")
            elif "✕" not in label.text():
                label.setStyleSheet(f"color: {theme.subtle()};")

    def set_error(self, category_id: str, has_error: bool) -> None:
        label = self._labels.get(category_id)
        if label is None:
            return
        base = label.text().replace(" ✕", "")
        label.setText(f"{base} ✕" if has_error else base)
        if has_error:
            label.setStyleSheet(f"color: {theme.danger()}; font-weight: 600;")


class BuildWizard(QWizard):
    """Der Hauptdialog."""

    def __init__(
        self,
        catalog: Catalog,
        store: SelectionStore,
        controller: PackageController,
        profiles: ProfileService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.catalog = catalog
        self.store = store
        self.controller = controller
        self.profiles = profiles

        self.setWindowTitle("Arch Linux ISO Builder")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        # Der Store ist die Quelle der Wahrheit, nicht die Seite. Ohne diese
        # Option wuerde Qt beim Zurueckblaettern Eingaben zuruecksetzen.
        self.setOption(QWizard.WizardOption.IndependentPages, True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.HaveCustomButton1, True)
        self.setOption(QWizard.WizardOption.HaveCustomButton2, True)
        self.setOption(QWizard.WizardOption.HaveCustomButton3, True)
        self.setButtonText(QWizard.WizardButton.CustomButton1, "Profil laden")
        self.setButtonText(QWizard.WizardButton.CustomButton2, "Profil speichern")
        self.setButtonText(QWizard.WizardButton.CustomButton3, "Profil exportieren")
        self.setButtonText(QWizard.WizardButton.NextButton, "Weiter >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Zurueck")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Beenden")
        self.setButtonText(QWizard.WizardButton.FinishButton, "ISO erstellen")
        self.setMinimumSize(1000, 720)

        self.customButtonClicked.connect(self._on_custom_button)

        self._exporter = ProfileExporter(catalog, self)
        self._exporter.finished.connect(self._on_export_finished)
        self._exporter.failed.connect(self._on_export_failed)

        self._pages: dict[str, CatalogPageBase] = {}
        self._order: list[Category] = []
        self._build_pages()

        self.sidebar = StepSidebar(tuple(self._order))
        self.setSideWidget(self.sidebar)

        self.currentIdChanged.connect(self._on_page_changed)
        self.store.issuesChanged.connect(self._refresh_sidebar)

    # -- Aufbau ---------------------------------------------------------------
    def _build_pages(self) -> None:
        factory = PageFactory(self.store, self.controller)
        for category in self.catalog.ordered_categories():
            if not category.visible:
                continue
            page = factory.create(category)
            if page is None:
                continue
            # Seiten-IDs kommen aus der Schrittnummer des Katalogs und sind
            # damit stabil, auch wenn eine Kategorie dazukommt.
            self.setPage(category.step, page)
            self._pages[category.id] = page
            self._order.append(category)
            if isinstance(page, CatalogPageBase):
                page.nextId = _make_next_id(self, category)   # type: ignore[method-assign]

    def visible_after(self, category: Category) -> int:
        """Naechste Kategorie, deren Bedingung erfuellt ist."""
        context = _WizardContext(self.store)
        started = False
        for candidate in self._order:
            if candidate.id == category.id:
                started = True
                continue
            if not started:
                continue
            if candidate.visible_when.evaluate(context):
                return candidate.step
        return -1

    # -- Ereignisse -----------------------------------------------------------
    def _on_page_changed(self, page_id: int) -> None:
        for category in self._order:
            if category.step == page_id:
                self.sidebar.set_current(category.id)
                break
        self._refresh_sidebar()

    def _refresh_sidebar(self) -> None:
        for category in self._order:
            has_error = any(
                issue.blocking for issue in self.store.issues(category.id)
            )
            self.sidebar.set_error(category.id, has_error)

    def _on_custom_button(self, which: int) -> None:
        if which == QWizard.WizardButton.CustomButton1:
            self._load_profile()
        elif which == QWizard.WizardButton.CustomButton2:
            self._save_profile()
        elif which == QWizard.WizardButton.CustomButton3:
            self._export(as_archive=True)

    # -- Profile --------------------------------------------------------------
    def _load_profile(self) -> None:
        start = self.profiles.builtin_dir
        selected, _filter = QFileDialog.getOpenFileName(
            self, "Profil laden", str(start), "Profile (*.yaml *.yml)"
        )
        if not selected:
            return
        try:
            result = self.profiles.load(Path(selected))
        except ProfileError as exc:
            QMessageBox.warning(self, "Profil konnte nicht geladen werden", str(exc))
            return

        if result.issues:
            details = "\n".join(
                f"- {issue.message}"
                + (f"\n  ({issue.action_taken})" if issue.action_taken else "")
                for issue in result.issues
            )
            QMessageBox.information(
                self,
                "Hinweise zum Profil",
                f"Das Profil wurde geladen. Dabei ist Folgendes aufgefallen:\n\n{details}",
            )

        self.store.replace_config(result.config)
        if result.secret_fields:
            QMessageBox.information(
                self,
                "Passwort erneut eingeben",
                "Profile enthalten keine Passwoerter. Bitte das Passwort im Schritt "
                "'Benutzerkonto' neu eingeben.",
            )
        self.restart()

    def _save_profile(self) -> None:
        ensure_dir(user_profiles_dir(), mode=0o755)
        suggested = self.profiles.default_path(
            self.store.config.profile_name or self.store.config.distro_name
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self, "Profil speichern", str(suggested), "Profile (*.yaml)"
        )
        if not selected:
            return
        path = Path(selected)
        try:
            self.profiles.save(
                self.store.config,
                path,
                resolution=self.store.resolution(),
            )
        except OSError as exc:
            QMessageBox.warning(self, "Speichern fehlgeschlagen", str(exc))
            return
        QMessageBox.information(
            self,
            "Profil gespeichert",
            f"Gespeichert unter:\n{path}\n\n"
            "Passwoerter werden bewusst nicht mitgespeichert.",
        )

    # -- Profil erzeugen ------------------------------------------------------
    def _export(self, as_archive: bool) -> None:
        """Erzeugt das archiso-Profil und schreibt es.

        Der eigentliche ISO-Build (mkarchiso starten) folgt spaeter und laeuft
        nur auf einem Arch-System. Was hier entsteht, ist alles, was mkarchiso
        dort braucht.
        """
        page = self.currentPage()
        plan = page.plan() if isinstance(page, SummaryPage) else None
        if plan is not None:
            log.info("Bauplan:\n%s", plan_as_text(plan))

        config = self.store.config
        if as_archive:
            suggested = str(Path.home() / f"{config.iso_name}-profil.tar.gz")
            selected, _filter = QFileDialog.getSaveFileName(
                self, "Profil als Archiv speichern", suggested, "tar-Archive (*.tar.gz)"
            )
        else:
            selected = QFileDialog.getExistingDirectory(
                self, "Zielverzeichnis fuer das Profil waehlen", str(Path.home())
            )
            if selected:
                # In ein leeres Unterverzeichnis schreiben statt direkt in das
                # gewaehlte -- sonst landet ein ganzes Profil mitten in einem
                # Ordner, in dem der Benutzer etwas anderes erwartet.
                selected = str(Path(selected) / f"{config.iso_name}-profil")
        if not selected:
            return

        self._exporter.export(
            config,
            self.store.resolution(),
            Path(selected),
            secrets=self.store.secrets,
            as_archive=as_archive,
        )
        self.setEnabled(False)

    def _on_export_finished(self, profile: object, path: object) -> None:
        self.setEnabled(True)
        assert isinstance(path, Path)
        dialog = ExportResultDialog(
            profile,          # type: ignore[arg-type]
            path,
            as_archive=path.suffix in (".gz", ".tgz"),
            parent=self,
        )
        dialog.exec()

    def _on_export_failed(self, error: object) -> None:
        self.setEnabled(True)
        from ..core.archiso.errors import (
            SymlinksUnsupportedError,
            TargetNotEmptyError,
        )

        causes: tuple[str, ...] = ()
        if isinstance(error, SymlinksUnsupportedError):
            causes = (
                "Windows erlaubt symbolische Verknuepfungen nur mit "
                "Entwicklermodus oder Administratorrechten.",
                "Der Weg ueber ein Archiv umgeht das vollstaendig.",
            )
        elif isinstance(error, TargetNotEmptyError):
            causes = (
                "Im Zielverzeichnis liegen Dateien, die nicht von diesem "
                "Programm stammen.",
                "Vorhandene Dateien werden grundsaetzlich nicht ueberschrieben.",
            )

        dialog = ErrorDialog(
            "Profil konnte nicht erzeugt werden",
            getattr(error, "user_message", str(error)),
            causes=causes,
            technical=getattr(error, "technical", ""),
            log_path=log_file_path(),
            parent=self,
        )
        dialog.exec()

    # -- ISO bauen ------------------------------------------------------------
    def accept(self) -> None:
        """'ISO erstellen'.

        Unter Linux laeuft der Bau direkt. Unter Windows kann er nicht direkt
        laufen -- archiso und pacman gibt es dort nicht. Statt einer
        Fehlermeldung fuehrt das Programm dann durch die Einrichtung eines
        Linux-Untersystems und baut anschliessend dort; die fertige ISO landet
        wieder im Windows-Ordner.
        """
        import sys as _sys

        page = self.currentPage()
        plan = page.plan() if isinstance(page, SummaryPage) else None
        if plan is not None:
            log.info("Bauplan:\n%s", plan_as_text(plan))

        target = None
        if _sys.platform != "linux":
            target = self._choose_wsl_target()
            if target is None:
                return

        self._start_build(target)

    def _choose_wsl_target(self):
        """Sucht eine Arch-Verteilung in WSL oder fuehrt zur Einrichtung."""
        from ..core.build import wsl
        from ..core.build.targets import WslExecutionTarget

        status = wsl.detect()
        if status.usable:
            preferred = status.preferred
            assert preferred is not None
            return WslExecutionTarget(wsl.WslTarget(preferred.name))

        dialog = WslSetupDialog(status, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        if dialog.export_requested:
            self._export(as_archive=True)
            return None
        name = dialog.distribution
        if not name:
            return None
        return WslExecutionTarget(wsl.WslTarget(name))

    def _start_build(self, target) -> None:
        config = self.store.config
        work_dir = Path(
            config.field_str("build.work_dir") or str(Path.home() / "archcustomiser" / "work")
        )
        out_dir = Path(
            config.field_str("build.output_dir") or str(Path.home() / "archcustomiser" / "out")
        )

        job = BuildJob(self.catalog, config, self.store.resolution(), self.store.secrets, self)
        if target is not None:
            job.controller.target = target
        report = job.preflight(work_dir, out_dir)

        if not report.ok and not self._can_build_here(report):
            self._offer_profile_export(report)
            return

        dialog = PreflightDialog(report, work_dir, out_dir, config.iso_filename, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self._build_job = job
        build = BuildDialog(
            job, work_dir, out_dir, keep_work_dir=dialog.keep_work_dir, parent=self
        )
        build.start()
        build.exec()

    @staticmethod
    def _can_build_here(report) -> bool:
        """Ob die Beanstandungen behebbar sind oder grundsaetzlicher Natur."""
        return not any(check.name == "Betriebssystem" for check in report.blocking)

    def _offer_profile_export(self, report) -> None:
        """Auf Nicht-Linux-Systemen den sinnvollen Weg anbieten.

        Einen Fehler zu melden und den Benutzer stehen zu lassen waere unnoetig:
        das Profil ist fertig, es fehlt nur die Maschine, die daraus baut.
        """
        detail = "\n".join(f"  - {check.detail}" for check in report.blocking)
        answer = QMessageBox.question(
            self,
            "ISO-Build hier nicht moeglich",
            f"{detail}\n\n"
            f"Stattdessen kann das fertige archiso-Profil als Archiv gespeichert "
            f"werden. Auf einem Arch-System entpacken und dort mit einem Befehl "
            f"die ISO bauen.\n\nProfil jetzt exportieren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._export(as_archive=True)


class _WizardContext:
    __slots__ = ("store",)

    def __init__(self, store: SelectionStore) -> None:
        self.store = store

    def is_selected(self, ref: str) -> bool:
        return self.store.is_selected(ref)

    def has_capability(self, name: str) -> bool:
        return bool(self.store.resolution().capabilities.get(name))

    def field_value(self, binding: str):
        return self.store.field(binding)


def _make_next_id(wizard: BuildWizard, category: Category):
    """Bindet ``nextId`` an die Sichtbarkeitsbedingungen des Katalogs."""

    def next_id() -> int:
        return wizard.visible_after(category)

    return next_id
