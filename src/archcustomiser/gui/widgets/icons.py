"""Symbole aus den mitgelieferten SVG-Dateien.

``Option.icon`` und ``Category.icon`` gab es im Datenmodell seit jeher, der
Lader las sie, sechs YAML-Dateien setzten sie -- und im gesamten Programm
existierte kein einziger ``QIcon``-Aufruf. Die Werte lagen also da, ohne je
etwas zu bewirken.

Die Dateien sind einfarbig und nutzen ``currentColor``; Qt faerbt sie damit
passend zum Thema ein, statt ein festes Grau zu zeigen, das im Dunkelmodus
verschwindet.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from PySide6.QtGui import QIcon

from ...core.paths import package_root

log = logging.getLogger(__name__)


def icons_dir():
    return package_root() / "assets" / "icons"


@lru_cache(maxsize=64)
def load_icon(name: str) -> QIcon | None:
    """Laedt ein Symbol; gibt ``None`` zurueck, wenn es keines gibt.

    Bewusst kein Ersatzsymbol: ein Platzhalter neben echten Symbolen sieht nach
    einem Fehler aus. Fehlt eines, bleibt der Eintrag eben ohne.
    """
    if not name:
        return None
    pfad = icons_dir() / f"{name}.svg"
    if not pfad.is_file():
        log.debug("Symbol %r nicht gefunden (%s)", name, pfad)
        return None
    symbol = QIcon(str(pfad))
    return None if symbol.isNull() else symbol
