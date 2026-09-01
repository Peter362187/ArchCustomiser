"""Vorabprüfung vor dem ISO-Build.

Zeigt alle Befunde auf einmal. Wer nach jeder Korrektur den naechsten Fehler
praesentiert bekommt, gibt beim dritten Mal auf.

Der Dialog laesst den Build nur zu, wenn nichts Blockierendes uebrig ist --
mit einer Ausnahme: Warnungen darf der Benutzer uebergehen, denn manche davon
(etwa ein bereits vorhandenes Arbeitsverzeichnis) sind bewusst so gewollt.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.build import PreflightReport
from .. import theme


class PreflightDialog(QDialog):
    """Zeigt die Befunde und fragt, ob gebaut werden soll."""

    def __init__(
        self,
        report: PreflightReport,
        work_dir: Path,
        out_dir: Path,
        iso_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("ISO erstellen")
        self.setMinimumWidth(700)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        headline = QLabel(f"Es wird gebaut: {iso_name}")
        font = headline.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        headline.setFont(font)
        layout.addWidget(headline)

        paths = QLabel(
            f"Arbeitsverzeichnis:  {work_dir}\nAusgabeverzeichnis: {out_dir}"
        )
        paths.setStyleSheet(f"color: {theme.muted()};")
        paths.setWordWrap(True)
        layout.addWidget(paths)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Pruefung", "Ergebnis"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 200)
        self.tree.setAlternatingRowColors(True)
        for check in report.checks:
            symbol = "ok" if check.ok else ("Hinweis" if not check.fatal else "FEHLER")
            item = QTreeWidgetItem([f"{symbol}  {check.name}", check.detail])
            colour = (
                theme.success() if check.ok
                else (theme.warning() if not check.fatal else theme.danger())
            )
            item.setForeground(0, _brush(colour))
            item.setToolTip(1, check.detail)
            self.tree.addTopLevelItem(item)
        layout.addWidget(self.tree, 1)

        note = QLabel(
            f"Der Build dauert je nach Auswahl 20 Minuten bis ueber eine Stunde "
            f"und braucht rund {report.estimated_work_gb:.0f} GB im "
            f"Arbeitsverzeichnis."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.muted()}; font-size: 11px;")
        layout.addWidget(note)

        self.keep_work = QCheckBox("Arbeitsverzeichnis nach dem Build behalten (zur Fehlersuche)")
        layout.addWidget(self.keep_work)

        buttons = QDialogButtonBox()
        self.start_button = buttons.addButton(
            "ISO erstellen", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if not report.ok:
            self.start_button.setEnabled(False)
            problem = QLabel(
                "Der Build kann so nicht starten. Die rot markierten Punkte "
                "muessen zuerst behoben werden."
            )
            problem.setWordWrap(True)
            problem.setStyleSheet(f"color: {theme.danger()};")
            layout.insertWidget(layout.count() - 1, problem)

    @property
    def keep_work_dir(self) -> bool:
        return self.keep_work.isChecked()


def _brush(colour: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(colour))
