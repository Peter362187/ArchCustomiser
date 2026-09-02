"""Darstellung einer einzelnen Katalogoption.

Eine Karte mit Titel, Beschreibung und Abzeichen, innen entweder ein
Auswahlknopf (Einfachauswahl) oder ein Haken (Mehrfachauswahl).

Drei Zustaende, die sich sichtbar unterscheiden muessen:

* **normal** -- anklickbar.
* **automatisch** -- durch eine andere Auswahl mitgezogen. Wird angehakt und
  gesperrt dargestellt, mit einer Begruendung im Tooltip. Ohne diese
  Kennzeichnung waere unklar, warum SDDM plötzlich ausgewaehlt ist.
* **nicht verfuegbar** -- ausgegraut statt versteckt. Eine Option, die
  verschwindet, verwirrt mehr als eine, die dabeisteht und erklaert, was ihr
  fehlt.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.catalog import Option, SelectionMode
from .. import theme


class Badge(QLabel):
    """Kleines farbiges Etikett, z.B. 'Empfohlen'."""

    def __init__(self, text: str, tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        # Die Palette lag frueher hier fest verdrahtet und war die einzige
        # Stelle der Anwendung, die den Dunkelmodus ignorierte -- weisse Schrift
        # auf hellem Orange erfuellte ausserdem kein AA-Kontrastverhaeltnis.
        background, foreground = theme.badge_colours(tone)
        font = theme.small_font()
        font.setBold(True)
        self.setFont(font)
        self.setStyleSheet(
            f"background: {background}; color: {foreground}; border-radius: 7px;"
            f" padding: 1px {theme.SPACE_SM}px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class OptionWidget(QFrame):
    """Karte fuer genau eine Option."""

    toggled = Signal(str, bool)   # (option_id, angehakt)

    def __init__(
        self,
        option: Option,
        mode: SelectionMode,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.option = option
        self._auto = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("optionCard")

        self.button: QAbstractButton = (
            QCheckBox() if mode is SelectionMode.MULTI else QRadioButton()
        )
        self.button.setText(option.label)
        font = self.button.font()
        font.setBold(True)
        self.button.setFont(font)
        self.button.toggled.connect(self._on_toggled)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        header.addWidget(self.button)
        if option.recommended:
            header.addWidget(Badge("Empfohlen", "accent"))
        if option.est_size_mb:
            header.addWidget(Badge(f"~{option.est_size_mb} MB"))
        if "multilib" in option.repos:
            header.addWidget(Badge("multilib", "warn"))
        if option.deprecated:
            header.addWidget(Badge("veraltet", "warn"))
        header.addStretch(1)

        self.lock_label = Badge("automatisch", "neutral")
        self.lock_label.hide()
        header.addWidget(self.lock_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM
        )
        layout.setSpacing(theme.SPACE_XS)
        layout.addLayout(header)

        if option.description:
            self.description = QLabel(option.description)
            self.description.setWordWrap(True)
            self.description.setFont(theme.small_font())
            self.description.setStyleSheet(f"color: {theme.muted()};")
            self.description.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            layout.addWidget(self.description)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setFont(theme.small_font())
        self.note.setStyleSheet(f"color: {theme.danger()};")
        self.note.hide()
        layout.addWidget(self.note)

        # Alle Karten gleich hoch. Ohne das entsteht im Raster ein sichtbares
        # Zickzack, weil manche Optionen eine einzeilige Beschreibung haben,
        # andere eine zweizeilige und wieder andere gar keine.
        self.setMinimumHeight(self._uniform_height())

    @staticmethod
    def _uniform_height() -> int:
        """Platz fuer die Titelzeile plus zwei Zeilen Beschreibung.

        Gemessen statt geraten, damit die Hoehe der Schriftskalierung des
        Systems folgt.
        """
        titel = QFontMetrics(theme.headline_font(2)).lineSpacing()
        klein = QFontMetrics(theme.small_font()).lineSpacing()
        return titel + 2 * klein + theme.SPACE_SM * 2 + theme.SPACE_XS * 2

    # -- Zustand --------------------------------------------------------------
    def set_checked(self, checked: bool) -> None:
        """Setzt den Haken, ohne ein Signal auszuloesen."""
        if self.button.isChecked() == checked:
            return
        blocked = self.button.blockSignals(True)
        try:
            self.button.setChecked(checked)
        finally:
            self.button.blockSignals(blocked)

    def is_checked(self) -> bool:
        return self.button.isChecked()

    def set_auto(self, auto: bool, reason: str = "") -> None:
        self._auto = auto
        self.lock_label.setVisible(auto)
        self.button.setEnabled(not auto)
        self.setToolTip(
            reason
            or (
                "Diese Option wurde automatisch ergaenzt, weil eine andere Auswahl "
                "sie benoetigt."
                if auto
                else self.option.docs
            )
        )
        self.setStyleSheet(
            f"#optionCard {{ background: {theme.card_highlight()}; }}" if auto else ""
        )

    def set_availability(self, enabled: bool, reason: str = "") -> None:
        if self._auto:
            return
        self.button.setEnabled(enabled)
        self.setEnabled(True)   # Tooltip soll lesbar bleiben
        if not enabled and reason:
            self.setToolTip(reason)
            self.note.setText(reason)
            self.note.show()
        else:
            self.note.hide()

    def _on_toggled(self, checked: bool) -> None:
        self.toggled.emit(self.option.id, checked)
