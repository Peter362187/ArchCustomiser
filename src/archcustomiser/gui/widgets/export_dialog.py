"""Dialoge rund um den Profilexport.

``ExportResultDialog`` zeigt, was entstanden ist, und -- wichtiger -- **wie es
weitergeht**. Ein Profilverzeichnis allein hilft niemandem; der Benutzer braucht
den mkarchiso-Aufruf, und zwar zum Kopieren.

``ErrorDialog`` setzt die Form aus Abschnitt 13 der Spezifikation um: Ursache,
moegliche Gruende, ``[Zurueck]`` und ``[Log anzeigen]``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.archiso import GeneratedProfile
from .. import theme

log = logging.getLogger(__name__)


class ExportResultDialog(QDialog):
    """Was wurde geschrieben, und was ist als Naechstes zu tun."""

    def __init__(
        self,
        profile: GeneratedProfile,
        target: Path,
        *,
        as_archive: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Profil erzeugt")
        self.setMinimumWidth(680)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        headline = QLabel(f"Das Profil fuer {profile.iso_filename} wurde erzeugt.")
        font = headline.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        headline.setFont(font)
        headline.setWordWrap(True)
        layout.addWidget(headline)

        facts = QLabel(
            f"{profile.tree.file_count} Dateien und "
            f"{profile.tree.symlink_count} Verknuepfungen\n{target}"
        )
        facts.setWordWrap(True)
        facts.setStyleSheet(f"color: {theme.muted()};")
        layout.addWidget(facts)

        if profile.warnings:
            notes = QPlainTextEdit("\n".join(f"- {w}" for w in profile.warnings))
            notes.setReadOnly(True)
            notes.setFixedHeight(110)
            layout.addWidget(QLabel("Hinweise:"))
            layout.addWidget(notes)

        layout.addWidget(QLabel("So geht es auf einem Arch-Linux-System weiter:"))

        steps = _next_steps(target, profile, as_archive=as_archive)
        self.commands = QPlainTextEdit(steps)
        self.commands.setReadOnly(True)
        self.commands.setFont(QFont("Consolas", 9))
        self.commands.setFixedHeight(120)
        layout.addWidget(self.commands)

        hints = [
            "Das Arbeitsverzeichnis braucht viel Platz -- fuer ein Desktop-Abbild "
            "mit Spielen sind 25 bis 40 GB realistisch -- und muss auf einem "
            "Linux-Dateisystem liegen."
        ]
        if as_archive:
            # Ein archiso-Profil enthaelt Verknuepfungen auf absolute Pfade des
            # spaeteren Systems (/usr/lib/systemd/...). Unter Windows lassen die
            # sich nicht anlegen; das offizielle archiso-Repository verhaelt sich
            # dabei genauso.
            hints.insert(
                0,
                "Das Archiv erst auf dem Linux-System entpacken. Unter Windows "
                "schlaegt das Entpacken fehl, weil ein archiso-Profil "
                "Verknuepfungen auf Linux-Pfade enthaelt -- das ist normal und "
                "kein Fehler des Archivs.",
            )
        hint = QLabel("\n\n".join(hints))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.muted()}; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        copy_button = QPushButton("Befehle kopieren")
        copy_button.clicked.connect(self._copy)
        buttons.addWidget(copy_button)
        buttons.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        buttons.addWidget(box)
        layout.addLayout(buttons)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.commands.toPlainText())


def _next_steps(target: Path, profile: GeneratedProfile, *, as_archive: bool) -> str:
    name = target.name
    if as_archive:
        folder = f"{profile.settings.iso_name}-profil"
        return (
            f"# 1. Archiv auf das Arch-System kopieren, dann dort:\n"
            f"tar xzf {name}\n"
            f"cd {folder}\n"
            f"\n"
            f"# 2. ISO bauen (Root wird nicht benoetigt):\n"
            f"mkarchiso -v -w ../work -o ../out .\n"
            f"\n"
            f"# Ergebnis: ../out/{profile.iso_filename}"
        )
    return (
        f"cd {target}\n"
        f"mkarchiso -v -w ../work -o ../out .\n"
        f"\n"
        f"# Ergebnis: ../out/{profile.iso_filename}"
    )


class ErrorDialog(QDialog):
    """Fehlermeldung nach Abschnitt 13 der Spezifikation."""

    def __init__(
        self,
        title: str,
        message: str,
        *,
        causes: tuple[str, ...] = (),
        technical: str = "",
        log_path: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(600)
        self.log_path = log_path

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        headline = QLabel(message)
        headline.setWordWrap(True)
        headline.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = headline.font()
        font.setBold(True)
        headline.setFont(font)
        layout.addWidget(headline)

        if causes:
            layout.addWidget(QLabel("Moegliche Ursachen:"))
            for cause in causes:
                item = QLabel(f"  •  {cause}")
                item.setWordWrap(True)
                layout.addWidget(item)

        self.details = QPlainTextEdit(technical)
        self.details.setReadOnly(True)
        self.details.setFont(QFont("Consolas", 9))
        self.details.setFixedHeight(120)
        self.details.setVisible(False)
        layout.addWidget(self.details)

        buttons = QHBoxLayout()
        if technical:
            self.detail_button = QPushButton("Einzelheiten anzeigen")
            self.detail_button.clicked.connect(self._toggle_details)
            buttons.addWidget(self.detail_button)
        if log_path is not None:
            log_button = QPushButton("Log anzeigen")
            log_button.clicked.connect(self._open_log)
            buttons.addWidget(log_button)
        buttons.addStretch(1)

        back = QPushButton("Zurueck")
        back.setDefault(True)
        back.clicked.connect(self.reject)
        buttons.addWidget(back)
        layout.addLayout(buttons)

    def _toggle_details(self) -> None:
        visible = not self.details.isVisible()
        self.details.setVisible(visible)
        self.detail_button.setText(
            "Einzelheiten verbergen" if visible else "Einzelheiten anzeigen"
        )
        self.adjustSize()

    def _open_log(self) -> None:
        if self.log_path is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path)))
