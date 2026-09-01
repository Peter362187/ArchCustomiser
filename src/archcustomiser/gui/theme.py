"""Farben, die in hellem und dunklem Design lesbar sind.

Qt-Stylesheets kennen ``palette(mid)``, aber dieser Wert ist in dunklen Themen
oft nur wenig heller als der Hintergrund -- Nebentexte werden dann praktisch
unlesbar. Deshalb wird hier einmal ermittelt, ob das aktive Design dunkel ist,
und daraus ein Satz Farben abgeleitet, der in beiden Faellen ausreichend
Kontrast hat.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


@lru_cache(maxsize=1)
def is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    window = app.palette().color(QPalette.ColorRole.Window)
    # Wahrgenommene Helligkeit, nicht der arithmetische Mittelwert.
    luminance = 0.299 * window.red() + 0.587 * window.green() + 0.114 * window.blue()
    return luminance < 128


def muted() -> str:
    """Nebentext: Beschreibungen, Hinweise, Statuszeile."""
    return "#a8a8a8" if is_dark() else "#5f6368"


def subtle() -> str:
    """Noch schwaecher, aber weiterhin lesbar: inaktive Schrittliste."""
    return "#8f8f8f" if is_dark() else "#767676"


def accent() -> str:
    return "#4fb3e8" if is_dark() else "#1064a0"


def success() -> str:
    return "#6cc070" if is_dark() else "#1e7a24"


def warning() -> str:
    return "#e0a53a" if is_dark() else "#8a5d00"


def danger() -> str:
    return "#f0736a" if is_dark() else "#b3261e"


def banner_colours(severity: str) -> tuple[str, str, str]:
    """(Hintergrund, Schrift, Randstreifen) fuer die Hinweisleiste."""
    if is_dark():
        table = {
            "error": ("#3a1f1d", "#f5b7b1", "#e74c3c"),
            "warning": ("#3a3320", "#f0d79a", "#f0ad4e"),
            "info": ("#1e2f3a", "#a9d5ee", "#1793d1"),
        }
    else:
        table = {
            "error": ("#fdecea", "#8b1a10", "#e74c3c"),
            "warning": ("#fef6e0", "#7a5900", "#f0ad4e"),
            "info": ("#eaf4fb", "#14567a", "#1793d1"),
        }
    return table.get(severity, table["info"])


def card_highlight() -> str:
    """Hintergrund einer automatisch ergaenzten Option."""
    return "rgba(79,179,232,0.13)" if is_dark() else "rgba(23,147,209,0.08)"


def format_size(size_bytes: int | None) -> str:
    """Groessenangabe, die auch bei kleinen Paketen sinnvoll bleibt.

    Ein Paket mit 400 KB als '0 MB' anzuzeigen sieht nach einem Fehler aus.
    """
    if not size_bytes:
        return ""
    megabytes = size_bytes / 1_048_576
    if megabytes < 0.1:
        return f"{size_bytes / 1024:.0f} KB"
    if megabytes < 10:
        return f"{megabytes:.1f} MB"
    return f"{megabytes:.0f} MB"
