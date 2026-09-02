"""Die eine Stelle, an der Gestaltung festgelegt wird.

Vorher gab es hier nur sieben Farbfunktionen; alles andere -- Abstaende,
Schriftgroessen, Schriftarten -- stand an rund zwanzig verstreuten
``setStyleSheet``-Aufrufen. ``font-size: 11px`` kam neunmal woertlich vor,
``QFont("Consolas", 9)`` sechsmal. Beides ist aus zwei Gruenden falsch:

* **Feste Pixelgroessen ignorieren die Schriftskalierung des Systems.** Wer
  Windows auf 125 % gestellt hat -- weil er sonst schlecht liest --, bekam
  weiterhin 11-Pixel-Text, waehrend die Rahmen darum herum mitwuchsen.
* **Consolas gibt es unter Linux nicht.** Ausgerechnet auf der Zielplattform,
  auf der gebaut wird, fiel Qt damit auf eine beliebige Ersatzschrift zurueck.

Deshalb hier: Abstaende als benannte Stufen, Schriftgroessen *relativ* zur
Systemschrift, und die Monospace-Schrift ueber ``QFontDatabase``.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Abstaende
# ---------------------------------------------------------------------------

# Eine Skala statt frei erfundener Werte. Vorher kamen in den Layouts 3, 4, 6,
# 7, 8, 9, 10, 12, 14 und 18 vor -- ohne dass ein Unterschied dahinterstand.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 18
SPACE_XL = 24


# ---------------------------------------------------------------------------
# Farben
# ---------------------------------------------------------------------------

_dark: bool | None = None


def is_dark() -> bool:
    """Ob das aktive Design dunkel ist.

    Das Ergebnis wird gemerkt, laesst sich aber ueber ``refresh()`` verwerfen.
    Frueher hing hier ein ``lru_cache`` ohne Ausweg: wechselte Windows zur
    Laufzeit auf ein dunkles Design, blieben die Farben fuer helle Themen
    eingefroren.
    """
    global _dark
    if _dark is None:
        app = QApplication.instance()
        if app is None:
            return False
        window = app.palette().color(QPalette.ColorRole.Window)
        # Wahrgenommene Helligkeit, nicht der arithmetische Mittelwert.
        _dark = (
            0.299 * window.red() + 0.587 * window.green() + 0.114 * window.blue()
        ) < 128
    return _dark


def refresh() -> None:
    """Nach einem Designwechsel aufrufen."""
    global _dark
    _dark = None


def _pick(dunkel: str, hell: str) -> str:
    return dunkel if is_dark() else hell


def text() -> str:
    """Normaler Fliesstext."""
    return _pick("#e6e6e6", "#1c1c1c")


def muted() -> str:
    """Nebentext: Beschreibungen, Hinweise, Statuszeile."""
    return _pick("#a8a8a8", "#5f6368")


def subtle() -> str:
    """Noch schwaecher, aber weiterhin lesbar: inaktive Schrittliste."""
    return _pick("#8f8f8f", "#767676")


def accent() -> str:
    return _pick("#4fb3e8", "#1064a0")


def success() -> str:
    return _pick("#6cc070", "#1e7a24")


def warning() -> str:
    return _pick("#e0a53a", "#8a5d00")


def danger() -> str:
    return _pick("#f0736a", "#b3261e")


def surface() -> str:
    """Hintergrund abgesetzter Flaechen -- Karten, Seitenleiste."""
    return _pick("#2b2b2b", "#f4f5f7")


def border() -> str:
    return _pick("#454545", "#d6d8dc")


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


def badge_colours(tone: str) -> tuple[str, str]:
    """(Hintergrund, Schrift) fuer ein Abzeichen an einer Optionskarte.

    Diese Palette stand frueher fest verdrahtet in ``option_widget.py`` und war
    die einzige Stelle der Anwendung, die den Dunkelmodus ignorierte. Weiss auf
    ``#c98a00`` erfuellte ausserdem kein AA-Kontrastverhaeltnis.
    """
    if is_dark():
        table = {
            "accent": ("#14425c", "#9fd7f5"),
            "warn": ("#4a3a10", "#f0d79a"),
            "neutral": ("#3c3c3c", "#cfcfcf"),
        }
    else:
        table = {
            "accent": ("#dceefa", "#0d4a6b"),
            "warn": ("#faeecd", "#6b4c00"),
            "neutral": ("#e6e7e9", "#41454b"),
        }
    return table.get(tone, table["neutral"])


def card_highlight() -> str:
    """Hintergrund einer automatisch ergaenzten Option."""
    return "rgba(79,179,232,0.13)" if is_dark() else "rgba(23,147,209,0.08)"


# ---------------------------------------------------------------------------
# Schrift
# ---------------------------------------------------------------------------


def base_point_size() -> float:
    """Die Schriftgroesse des Systems -- Bezugspunkt fuer alles andere."""
    app = QApplication.instance()
    if app is None:
        return 9.0
    size = app.font().pointSizeF()
    # Auf manchen Systemen ist nur die Pixelgroesse gesetzt.
    return size if size > 0 else 9.0


def _system_font() -> QFont:
    app = QApplication.instance()
    return QFont(app.font()) if app is not None else QFont()


def small_font() -> QFont:
    """Nebentext. Ersetzt die neun woertlichen ``font-size: 11px``."""
    font = _system_font()
    font.setPointSizeF(max(base_point_size() - 1.0, 7.0))
    return font


def headline_font(level: int = 1) -> QFont:
    """Ueberschrift. ``level`` 1 ist gross, 2 etwas kleiner.

    Ersetzt das fuenffach kopierte Muster aus ``setBold(True)`` plus
    ``setPointSize(pointSize() + 1)``.
    """
    font = _system_font()
    font.setBold(True)
    font.setPointSizeF(base_point_size() + (2.0 if level <= 1 else 1.0))
    return font


def mono_font() -> QFont:
    """Feste Zeichenbreite -- fuer Befehle, Pfade und Protokolle.

    Ueber ``QFontDatabase`` statt ueber einen Schriftnamen: ``Consolas`` gibt es
    unter Linux nicht, und Qt fiel dort auf eine beliebige Ersatzschrift
    zurueck -- ausgerechnet auf der Plattform, auf der gebaut wird.
    """
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSizeF(max(base_point_size() - 0.5, 7.0))
    return font


# ---------------------------------------------------------------------------
# Sonstiges
# ---------------------------------------------------------------------------


def format_size(size_bytes: int | None) -> str:
    """Groessenangabe, die auch bei kleinen Paketen sinnvoll bleibt.

    Ein Paket mit 400 KB als '0 MB' anzuzeigen sieht nach einem Fehler aus.
    """
    if not size_bytes:
        return ""
    if size_bytes < 1024:
        # Eine Konfigurationsdatei mit 40 Bytes als "0 KB" anzuzeigen sieht
        # nach einem Fehler aus -- genauso wie 400 KB als "0 MB".
        return f"{size_bytes} B"
    megabytes = size_bytes / 1_048_576
    if megabytes < 0.1:
        return f"{size_bytes / 1024:.0f} KB"
    if megabytes < 10:
        return f"{megabytes:.1f} MB"
    return f"{megabytes:.0f} MB"


def application_stylesheet() -> str:
    """Das Grundgeruest, einmal fuer die ganze Anwendung.

    Alles, was ueber Objektnamen und Widget-Klassen erreichbar ist, gehoert
    hierher statt an einzelne ``setStyleSheet``-Aufrufe -- sonst wandert die
    Gestaltung wieder in die Seiten zurueck.
    """
    randfarbe = border()
    nebentext = muted()
    return "\n".join(
        [
            "QGroupBox {",
            f"    border: 1px solid {randfarbe};",
            "    border-radius: 6px;",
            f"    margin-top: {SPACE_MD}px;",
            f"    padding-top: {SPACE_MD}px;",
            "    font-weight: 600;",
            "}",
            "QGroupBox::title {",
            "    subcontrol-origin: margin;",
            "    subcontrol-position: top left;",
            f"    left: {SPACE_MD}px;",
            f"    padding: 0 {SPACE_XS}px;",
            f"    color: {nebentext};",
            "}",
            "QFrame#optionCard {",
            f"    border: 1px solid {randfarbe};",
            "    border-radius: 6px;",
            "}",
            "QFrame#optionCard:hover {",
            f"    border-color: {accent()};",
            "}",
            "QLabel#hint {",
            f"    color: {nebentext};",
            "}",
        ]
    )
