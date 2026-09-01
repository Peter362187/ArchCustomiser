"""Hinweisleiste am Kopf einer Wizard-Seite.

Zeigt Fehler, Warnungen und Hinweise des Resolvers. Traegt ein Problem einen
maschinell anwendbaren Vorschlag, erscheint daneben eine Schaltflaeche -- der
Benutzer muss den Widerspruch dann nicht selbst aufloesen.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.resolver import Fix, Issue
from .. import theme


class IssueBanner(QWidget):
    """Liste der Probleme einer Seite."""

    fixRequested = Signal(object)   # Fix

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self.hide()

    def set_issues(self, issues: tuple[Issue, ...]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not issues:
            self.hide()
            return

        # Fehler zuerst -- was den Weiter-Knopf blockiert, gehoert nach oben.
        order = {"error": 0, "warning": 1, "info": 2}
        for issue in sorted(issues, key=lambda i: order.get(i.severity, 3)):
            self._layout.addWidget(self._make_row(issue))
        self.show()

    def _make_row(self, issue: Issue) -> QFrame:
        background, foreground, border = theme.banner_colours(issue.severity)
        frame = QFrame()
        frame.setStyleSheet(
            f"background:{background}; color:{foreground};"
            f"border-left:3px solid {border}; border-radius:3px;"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(9, 6, 9, 6)
        row.setSpacing(8)

        label = QLabel(issue.message)
        label.setWordWrap(True)
        label.setStyleSheet(f"color:{foreground}; background:transparent; border:none;")
        row.addWidget(label, 1)

        if issue.fix is not None:
            button = QPushButton(issue.fix.label)
            button.setCursor(frame.cursor())
            fix: Fix = issue.fix
            button.clicked.connect(lambda _checked=False, f=fix: self.fixRequested.emit(f))
            row.addWidget(button, 0)
        return frame
