"""Auswahlseite -- rendert eine Katalogkategorie mit Optionen.

Diese eine Klasse erzeugt alle Auswahlschritte des Wizards: Desktop, Window
Manager, Kernel, Netzwerk, Audio, Programme, Treiber und Dienste. Der
Unterschied zwischen ihnen steht vollstaendig im YAML.

Ein Detail, das leicht falsch gemacht wird: Bei Einfachauswahl gilt die
Exklusivitaet fuer die **ganze Kategorie**, nicht je Gruppenkasten. Deshalb
liegen alle Auswahlknoepfe in *einer* ``QButtonGroup``, obwohl sie optisch auf
mehrere Kaesten verteilt sind -- sonst koennte man je Gruppe einen Desktop
auswaehlen.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QGroupBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.catalog import Category, Option, SelectionMode
from ...core.config import SelectionSource
from ..store import SelectionStore
from ..widgets.option_widget import OptionWidget
from .base import CatalogPageBase

log = logging.getLogger(__name__)


class _PredicateContext:
    """Auswertungskontext fuer ``visible_when``/``enabled_when`` einer Option."""

    __slots__ = ("store",)

    def __init__(self, store: SelectionStore) -> None:
        self.store = store

    def is_selected(self, ref: str) -> bool:
        return self.store.is_selected(ref)

    def has_capability(self, name: str) -> bool:
        return bool(self.store.resolution().capabilities.get(name))

    def field_value(self, binding: str):
        return self.store.field(binding)


class CatalogSelectionPage(CatalogPageBase):
    def __init__(self, category: Category, store: SelectionStore) -> None:
        super().__init__(category, store)
        self._widgets: dict[str, OptionWidget] = {}
        self._button_group: QButtonGroup | None = None
        self._build_ui()
        self.add_help_link()
        self.store.selectionChanged.connect(self._on_selection_changed)
        self.store.resolutionChanged.connect(self.sync_from_store)

    # -- Aufbau ---------------------------------------------------------------
    def _build_ui(self) -> None:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        exclusive = self.category.selection_mode is not SelectionMode.MULTI
        if exclusive:
            self._button_group = QButtonGroup(self)
            self._button_group.setExclusive(True)

        for group_id, options in self._grouped_options():
            target = outer
            if group_id is not None:
                box = QGroupBox(group_id.label)
                outer.addWidget(box)
                target = QVBoxLayout(box)
                target.setSpacing(6)

            grid = QGridLayout()
            grid.setSpacing(8)
            columns = max(1, self.category.columns)
            for position, option in enumerate(options):
                widget = self._make_widget(option)
                grid.addWidget(widget, position // columns, position % columns)
            if isinstance(target, QVBoxLayout):
                target.addLayout(grid)
            else:
                outer.addLayout(grid)

        outer.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(container)
        # Waagerecht darf nie gescrollt werden -- lange Beschreibungen brechen um.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._root.addWidget(scroll, 1)

    def _grouped_options(self):
        """Optionen nach Gruppen, jeweils nach ``order`` sortiert."""
        if not self.category.groups:
            return [(None, sorted(self.category.options, key=lambda o: (o.order, o.label)))]

        result = []
        for group in sorted(self.category.groups, key=lambda g: g.order):
            members = [option for option in self.category.options if option.group == group.id]
            if members:
                result.append((group, sorted(members, key=lambda o: (o.order, o.label))))
        ungrouped = [
            option
            for option in self.category.options
            if not option.group or option.group not in {g.id for g in self.category.groups}
        ]
        if ungrouped:
            result.append((None, sorted(ungrouped, key=lambda o: (o.order, o.label))))
        return result

    def _make_widget(self, option: Option) -> OptionWidget:
        widget = OptionWidget(option, self.category.selection_mode)
        widget.toggled.connect(self._on_option_toggled)
        if self._button_group is not None:
            self._button_group.addButton(widget.button)
        self._widgets[option.id] = widget
        return widget

    # -- Store-Anbindung ------------------------------------------------------
    def _on_option_toggled(self, option_id: str, checked: bool) -> None:
        ref = f"{self.category.id}.{option_id}"
        self.store.toggle(ref, checked, source=SelectionSource.USER)

    def _on_selection_changed(self, category_id: str) -> None:
        # Auch fremde Kategorien koennen diese Seite betreffen: eine
        # Desktop-Auswahl zieht Basiskomponenten mit und kann Optionen hier
        # verfuegbar oder unverfuegbar machen.
        self.sync_from_store()

    def sync_from_store(self) -> None:
        selected = self.store.selected(self.category.id)
        context = _PredicateContext(self.store)

        for option_id, widget in self._widgets.items():
            ref = f"{self.category.id}.{option_id}"
            widget.set_checked(option_id in selected)

            auto = self.store.is_auto(ref)
            widget.set_auto(auto, self._auto_reason(ref) if auto else "")

            option = widget.option
            if not auto:
                visible = option.visible_when.evaluate(context)
                enabled = visible and option.enabled_when.evaluate(context)
                widget.setVisible(visible or option_id in selected)
                widget.set_availability(
                    enabled,
                    "" if enabled else "Diese Option setzt eine andere Auswahl voraus.",
                )
        self.completeChanged.emit()

    def _auto_reason(self, ref: str) -> str:
        """Wer hat diese Option mitgezogen?"""
        causes = [
            other.label
            for other_ref in sorted(self.store.resolution().effective_refs)
            if (other := self.store.catalog.option(other_ref)) is not None
            and ref in other.implies
            and other_ref not in self.store.resolution().auto_refs
        ]
        if causes:
            return f"Automatisch ergaenzt, weil {', '.join(causes)} das benoetigt."
        return "Automatisch ergaenzt, weil eine andere Auswahl das benoetigt."
