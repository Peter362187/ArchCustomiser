"""Gemeinsame Basis aller Katalogseiten.

``QWizardPage`` ist hier nur ein duenner Wirt: der eigentliche Inhalt lebt in
einem gewoehnlichen ``QWidget``. Damit bleibt ein spaeterer Wechsel auf eine
andere Navigationsform (etwa freie Sprungnavigation) eine lokale Aenderung.

Die Seiten halten keinen eigenen Zustand. Beim Betreten zeichnen sie sich aus
dem Store neu -- das macht die Zurueck-Navigation korrekt, ohne Sonderfaelle.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWizardPage

from ...core.catalog import Category
from ...core.resolver import Issue
from .. import theme
from ..store import SelectionStore
from ..widgets.issue_banner import IssueBanner

log = logging.getLogger(__name__)


class CatalogPageBase(QWizardPage):
    """Basis fuer alle aus dem Katalog erzeugten Seiten."""

    def __init__(self, category: Category, store: SelectionStore) -> None:
        super().__init__()
        self.category = category
        self.store = store

        self.setTitle(category.title)
        if category.subtitle:
            self.setSubTitle(category.subtitle)

        self._root = QVBoxLayout(self)
        self._root.setSpacing(theme.SPACE_SM)

        self._local_issues: tuple[Issue, ...] = ()
        self.banner = IssueBanner()
        self.banner.fixRequested.connect(self.store.apply_fix)
        self._root.addWidget(self.banner)

        self.store.issuesChanged.connect(self._refresh_issues)

    # -- Qt-Haken -------------------------------------------------------------
    def category_id(self) -> str:
        return self.category.id

    def initializePage(self) -> None:
        self.sync_from_store()
        self._refresh_issues()

    def cleanupPage(self) -> None:
        # Absichtlich leer: der Store ist die Quelle der Wahrheit, nicht die
        # Seite. Qt wuerde hier sonst Eingaben zuruecksetzen.
        pass

    def isComplete(self) -> bool:
        return not any(issue.blocking for issue in self.store.issues(self.category.id))

    # -- von Unterklassen zu ueberschreiben -----------------------------------
    def sync_from_store(self) -> None:
        """Widgets an den Store angleichen."""

    # -- eigene Meldungen der Seite -------------------------------------------
    def set_local_issues(self, issues: tuple[Issue, ...]) -> None:
        """Meldungen, die nur diese Seite kennt.

        Feldfehler und ungueltige Paketnamen sperrten den Weiter-Knopf, ohne
        dass an prominenter Stelle stand, warum: die Begruendung hing an der
        betroffenen Zeile, und die lag im Formular womoeglich ausserhalb des
        sichtbaren Ausschnitts. Ueber diesen Weg landen sie zusaetzlich oben in
        der Hinweisleiste, wo der Weiter-Knopf auch ist.
        """
        self._local_issues = issues
        self._refresh_issues()

    # -- intern ---------------------------------------------------------------
    def _refresh_issues(self) -> None:
        issues = self.store.issues(self.category.id) + self._local_issues
        self.banner.set_issues(issues)
        self.completeChanged.emit()

    def add_help_link(self) -> None:
        if not self.category.help_url:
            return
        link = QLabel(
            f'<a href="{self.category.help_url}">Weitere Informationen im Arch-Wiki</a>'
        )
        link.setOpenExternalLinks(True)
        link.setFont(theme.small_font())
        self._root.addWidget(link)
