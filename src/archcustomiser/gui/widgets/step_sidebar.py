"""Die Schrittliste am linken Rand.

Vorher eine Reihe schlichter ``QLabel``: keine Nummerierung, kein Hinweis auf
den Fortschritt, kein Klick -- und ein irrefuehrendes Detail. Schritte, die
uebersprungen werden, standen unveraendert in der Liste. Wer keine grafische
Sitzung gewaehlt hat, bekommt die Seite "Grafiktreiber" nie zu sehen; sie stand
aber weiter da, und der Benutzer wartete auf einen Schritt, der nicht kommt.

Hier gibt es deshalb fuenf Zustaende, die sich sichtbar unterscheiden:

* **erledigt** -- schon besucht, ohne Beanstandung. Mit Haken, anklickbar.
* **aktuell** -- die gerade gezeigte Seite.
* **offen** -- kommt noch.
* **uebersprungen** -- unter der aktuellen Auswahl nicht zutreffend. Ausgegraut
  und durchgestrichen, damit klar ist: der kommt nicht.
* **fehlerhaft** -- blockiert das Weitergehen.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.catalog import Category
from .. import theme
from .common import HintLabel
from .icons import load_icon


class StepState(Enum):
    OPEN = "offen"
    CURRENT = "aktuell"
    DONE = "erledigt"
    SKIPPED = "uebersprungen"
    ERROR = "fehlerhaft"


# Ein Zeichensatz fuer Zustaende, ueberall derselbe. Die Anwendung sprach hier
# frueher drei Sprachen: "○ → ✓" im Baudialog, "✕" in der Schrittliste und die
# ausgeschriebenen Woerter "ok/Hinweis/FEHLER" in der Vorabpruefung.
MARK_DONE = "✓"
MARK_ERROR = "✕"
MARK_SKIPPED = "–"
MARK_CURRENT = "▸"
MARK_OPEN = "○"
MARK_WARNING = "!"

_MARKS = {
    StepState.DONE: MARK_DONE,
    StepState.ERROR: MARK_ERROR,
    StepState.SKIPPED: MARK_SKIPPED,
    StepState.CURRENT: MARK_CURRENT,
    StepState.OPEN: MARK_OPEN,
}


class StepSidebar(QWidget):
    """Schrittliste mit Fortschritt und Sprungmoeglichkeit."""

    stepClicked = Signal(str)          # category_id

    def __init__(
        self, categories: tuple[Category, ...], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QToolButton] = {}
        self._states: dict[str, StepState] = {}
        self._numbers: dict[str, int] = {}
        self._titles: dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_MD, theme.SPACE_LG, theme.SPACE_MD, theme.SPACE_LG
        )
        layout.setSpacing(theme.SPACE_XS)

        self.heading = QLabel("Schritte")
        self.heading.setFont(theme.headline_font(2))
        layout.addWidget(self.heading)

        self.progress = HintLabel("")
        layout.addWidget(self.progress)
        layout.addSpacing(theme.SPACE_SM)

        for position, category in enumerate(categories, start=1):
            self._numbers[category.id] = position
            self._titles[category.id] = category.title

            button = QToolButton()
            button.setText(f"{position}. {category.title}")
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            symbol = load_icon(category.icon)
            if symbol is not None:
                button.setIcon(symbol)
            button.setAutoRaise(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            # Linksbuendig -- eine mittig gesetzte Liste liest sich schlecht.
            button.setStyleSheet("QToolButton { text-align: left; }")
            button.clicked.connect(
                lambda _checked=False, key=category.id: self.stepClicked.emit(key)
            )
            layout.addWidget(button)
            self._buttons[category.id] = button
            self._states[category.id] = StepState.OPEN

        layout.addStretch(1)

        self.notice = HintLabel("")
        self.notice.setStyleSheet(f"color: {theme.warning()};")
        self.notice.hide()
        layout.addWidget(self.notice)

        # Breite an der laengsten Beschriftung ausrichten statt fest auf 190 px:
        # bei groesserer Systemschrift wurden die Titel sonst abgeschnitten.
        self.setMinimumWidth(self._natural_width())
        self._repaint_all()

    # -- oeffentlich ----------------------------------------------------------
    def set_states(self, states: dict[str, StepState]) -> None:
        """Alle Zustaende auf einmal setzen.

        Bewusst als Ganzes und nicht einzeln: die Zustaende haengen voneinander
        ab (was uebersprungen wird, was schon erledigt ist), und eine
        Teilaktualisierung hinterliess frueher Widersprueche -- ein rot
        markierter Schritt etwa blieb rot, nachdem der Fehler behoben war.
        """
        self._states = dict(states)
        self._repaint_all()

    def set_notice(self, text: str) -> None:
        """Eine Randnotiz unter der Schrittliste.

        Fuer Auskuenfte, die die ganze Sitzung betreffen und nirgends sonst
        hingehoeren -- etwa, dass die Paketdaten nicht geladen werden konnten.
        """
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def set_clickable(self, category_ids: set[str]) -> None:
        for key, button in self._buttons.items():
            button.setEnabled(key in category_ids)

    # -- intern ---------------------------------------------------------------
    def _repaint_all(self) -> None:
        erledigt = sum(
            1 for state in self._states.values() if state is StepState.DONE
        )
        zutreffend = sum(
            1 for state in self._states.values() if state is not StepState.SKIPPED
        )
        self.progress.setText(f"{erledigt} von {zutreffend} erledigt")

        for key, button in self._buttons.items():
            self._repaint(key, button)

    def _repaint(self, key: str, button: QToolButton) -> None:
        state = self._states.get(key, StepState.OPEN)
        nummer = self._numbers[key]
        titel = self._titles[key]
        button.setText(f"{_MARKS[state]} {nummer}. {titel}")

        if state is StepState.CURRENT:
            stil = f"color: {theme.text()}; font-weight: 600;"
            button.setToolTip("")
        elif state is StepState.ERROR:
            stil = f"color: {theme.danger()}; font-weight: 600;"
            button.setToolTip("Hier fehlt noch etwas.")
        elif state is StepState.DONE:
            stil = f"color: {theme.success()};"
            button.setToolTip("Erledigt -- zum Springen anklicken.")
        elif state is StepState.SKIPPED:
            stil = f"color: {theme.subtle()}; text-decoration: line-through;"
            button.setToolTip(
                "Trifft auf die aktuelle Auswahl nicht zu und wird uebersprungen."
            )
        else:
            stil = f"color: {theme.subtle()};"
            button.setToolTip("")

        button.setStyleSheet(f"QToolButton {{ text-align: left; {stil} }}")

    def _natural_width(self) -> int:
        metrik = self.fontMetrics()
        breiteste = max(
            (
                metrik.horizontalAdvance(f"{MARK_DONE} {self._numbers[key]}. {titel}")
                for key, titel in self._titles.items()
            ),
            default=140,
        )
        # Platz fuer das Symbol daneben einrechnen, sonst schneidet die
        # Beschriftung genau um dessen Breite ab.
        symbolbreite = 16 + theme.SPACE_SM
        return breiteste + symbolbreite + theme.SPACE_XL * 2
