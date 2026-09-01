"""Formularseite -- rendert Textfelder, Auswahllisten und Passwortfelder.

Erzeugt Grundkonfiguration, Benutzerkonto, Branding und ISO-Einstellungen aus
demselben Code. Ein neues Feld ist ein YAML-Eintrag.

Passwoerter: Felder mit ``secret: true`` schreiben ausschliesslich in den
SecretStore. Ihr Wert erreicht ``BuildConfig`` nie und kann damit strukturell
nicht in einem Profil landen. Beim Verlassen der Seite wird zusaetzlich
geprueft, ob Passwort und Wiederholung uebereinstimmen.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core import choices as choice_registry
from ...core import validation
from ...core.catalog import Category, FieldSpec
from .. import theme
from ..store import SelectionStore
from .base import CatalogPageBase

log = logging.getLogger(__name__)

VALIDATION_DELAY_MS = 250


class _FieldRow:
    """Ein Feld samt Eingabewidget und Meldungszeile."""

    __slots__ = ("spec", "widget", "message", "label", "container", "browse")

    def __init__(
        self,
        spec: FieldSpec,
        widget: QWidget,
        message: QLabel,
        label: QLabel,
        container: QWidget,
        browse: QPushButton | None = None,
    ) -> None:
        self.spec = spec
        self.widget = widget
        self.message = message
        self.label = label
        self.container = container
        self.browse = browse


class _PredicateContext:
    __slots__ = ("store",)

    def __init__(self, store: SelectionStore) -> None:
        self.store = store

    def is_selected(self, ref: str) -> bool:
        return self.store.is_selected(ref)

    def has_capability(self, name: str) -> bool:
        return bool(self.store.resolution().capabilities.get(name))

    def field_value(self, binding: str) -> Any:
        return self.store.field(binding)


class CatalogFormPage(CatalogPageBase):
    def __init__(self, category: Category, store: SelectionStore) -> None:
        super().__init__(category, store)
        self._rows: dict[str, _FieldRow] = {}
        self._valid: dict[str, bool] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(VALIDATION_DELAY_MS)
        self._timer.timeout.connect(self._validate_all)
        self._build_ui()
        self.store.fieldChanged.connect(lambda _binding: self._update_visibility())

    # -- Aufbau ---------------------------------------------------------------
    def _build_ui(self) -> None:
        container = QWidget()
        form = QFormLayout(container)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for spec in self.category.fields:
            widget, browse = self._make_widget(spec)
            message = QLabel("")
            message.setWordWrap(True)
            message.setStyleSheet("font-size: 11px;")
            message.hide()

            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)

            if browse is not None:
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(widget, 1)
                row.addWidget(browse, 0)
                cell_layout.addLayout(row)
            else:
                cell_layout.addWidget(widget)

            if spec.help:
                hint = QLabel(spec.help)
                hint.setWordWrap(True)
                hint.setStyleSheet(f"color: {theme.muted()}; font-size: 11px;")
                cell_layout.addWidget(hint)
            cell_layout.addWidget(message)

            label = QLabel(spec.label + (" *" if spec.required else ""))
            form.addRow(label, cell)
            self._rows[spec.id] = _FieldRow(spec, widget, message, label, cell, browse)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        self._root.addWidget(scroll, 1)

    def _make_widget(self, spec: FieldSpec) -> tuple[QWidget, QPushButton | None]:
        if spec.widget == "bool":
            widget = QCheckBox()
            widget.toggled.connect(lambda value, s=spec: self._on_changed(s, value))
            return widget, None

        if spec.widget == "int":
            spin = QSpinBox()
            spin.setRange(
                spec.minimum if spec.minimum is not None else 0,
                spec.maximum if spec.maximum is not None else 9999,
            )
            spin.valueChanged.connect(lambda value, s=spec: self._on_changed(s, value))
            return spin, None

        if spec.widget in ("combo", "editable_combo"):
            combo = QComboBox()
            combo.setEditable(spec.widget == "editable_combo")
            if spec.choices:
                for choice in spec.choices:
                    combo.addItem(choice.display, choice.value)
            elif spec.choices_from:
                for value in choice_registry.get_choices(spec.choices_from):
                    combo.addItem(value, value)
            if combo.isEditable():
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.lineEdit().textEdited.connect(
                    lambda text, s=spec: self._on_changed(s, text)
                )
            combo.currentIndexChanged.connect(
                lambda _index, s=spec, c=combo: self._on_changed(s, _combo_value(c))
            )
            return combo, None

        if spec.widget == "textarea":
            area = QTextEdit()
            area.setAcceptRichText(False)
            area.setFixedHeight(80)
            area.textChanged.connect(
                lambda s=spec, a=area: self._on_changed(s, a.toPlainText())
            )
            return area, None

        edit = QLineEdit()
        if spec.placeholder:
            edit.setPlaceholderText(spec.placeholder)
        if spec.widget == "password":
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.textEdited.connect(lambda text, s=spec: self._on_changed(s, text))

        browse = None
        if spec.widget == "path":
            browse = QPushButton("Durchsuchen ...")
            browse.clicked.connect(lambda _checked=False, s=spec: self._browse(s))
        return edit, browse

    # -- Ereignisse -----------------------------------------------------------
    def _on_changed(self, spec: FieldSpec, value: Any) -> None:
        if spec.secret:
            # Geht ausschliesslich in den SecretStore.
            self.store.set_secret(spec.binding, str(value))
        else:
            self.store.set_field(spec.binding, value)
        self._timer.start()

    def _browse(self, spec: FieldSpec) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self, spec.label, "", spec.file_filter or "Alle Dateien (*)"
        )
        if selected:
            row = self._rows[spec.id]
            if isinstance(row.widget, QLineEdit):
                row.widget.setText(selected)
            self._on_changed(spec, selected)

    # -- Anzeige --------------------------------------------------------------
    def sync_from_store(self) -> None:
        for spec_id, row in self._rows.items():
            spec = row.spec
            if spec.secret:
                continue   # Geheimnisse werden nie zurueckgeschrieben
            value = self.store.field(spec.binding, spec.default)
            widget = row.widget
            blocked = widget.blockSignals(True)
            try:
                if isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QSpinBox):
                    widget.setValue(int(value or 0))
                elif isinstance(widget, QComboBox):
                    _set_combo_value(widget, value)
                elif isinstance(widget, QTextEdit):
                    widget.setPlainText(str(value or ""))
                elif isinstance(widget, QLineEdit):
                    widget.setText(str(value or ""))
            finally:
                widget.blockSignals(blocked)
        self._update_visibility()
        self._validate_all()

    def _update_visibility(self) -> None:
        context = _PredicateContext(self.store)
        for row in self._rows.values():
            visible = row.spec.visible_when.evaluate(context)
            enabled = visible and row.spec.enabled_when.evaluate(context)
            row.container.setVisible(visible)
            row.label.setVisible(visible)
            row.container.setEnabled(enabled)

    def _validate_all(self) -> None:
        context = _PredicateContext(self.store)
        for row in self._rows.values():
            spec = row.spec
            active = spec.visible_when.evaluate(context) and spec.enabled_when.evaluate(context)
            if not active:
                self._valid[spec.id] = True
                row.message.hide()
                continue

            value = (
                self.store.secrets.get(spec.binding)
                if spec.secret
                else self.store.field(spec.binding, spec.default)
            )
            text = value.reveal() if spec.secret and value is not None else value

            if spec.required and not str(text or "").strip():
                self._show(row, f"{spec.label} wird benoetigt.", ok=False)
                self._valid[spec.id] = False
                continue

            if spec.confirm_field:
                other = self.store.secrets.get(
                    self._binding_of(spec.confirm_field)
                ) if spec.secret else None
                first = text or ""
                second = other.reveal() if other is not None else ""
                if first and first != second:
                    self._show(row, "Die beiden Eingaben stimmen nicht ueberein.", ok=False)
                    self._valid[spec.id] = False
                    continue

            if spec.validator:
                result = validation.validate(spec.validator, text)
                if not result.ok:
                    self._show(row, result.message, ok=result.is_warning)
                    self._valid[spec.id] = result.is_warning
                    continue

            row.message.hide()
            self._valid[spec.id] = True
        self.completeChanged.emit()

    def _binding_of(self, field_id: str) -> str:
        spec = self.category.field(field_id)
        return spec.binding if spec else f"{self.category.id}.{field_id}"

    @staticmethod
    def _show(row: _FieldRow, message: str, *, ok: bool) -> None:
        colour = theme.warning() if ok else theme.danger()
        row.message.setText(message)
        row.message.setStyleSheet(f"color:{colour}; font-size:11px;")
        row.message.show()

    def isComplete(self) -> bool:
        return all(self._valid.values()) and super().isComplete()


def _combo_value(combo: QComboBox) -> str:
    data = combo.currentData()
    if data is not None:
        return str(data)
    return combo.currentText()


def _set_combo_value(combo: QComboBox, value: Any) -> None:
    text = "" if value is None else str(value)
    index = combo.findData(text)
    if index < 0:
        index = combo.findText(text)
    if index >= 0:
        combo.setCurrentIndex(index)
    elif combo.isEditable():
        combo.setCurrentText(text)
