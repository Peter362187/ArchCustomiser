"""Kopiert das Projekt in einen geklonten Repository-Ordner.

Uebernommen wird nur, was auch ins Repository gehoert -- die Regeln stammen
aus derselben ``.gitignore``, die git spaeter anwendet. Ohne diese Filterung
landeten 667 MB Programmumgebung und mehrere Gigabyte ISO-Dateien im Klon.

Aufruf::

    python tools/ins_repo_kopieren.py <zielordner>
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Verzeichnisse, die nie mitgehen.
AUSGESCHLOSSENE_ORDNER = {
    ".venv", "venv", "env", ".git",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", "out", "work",
    ".vscode", ".idea",
}

# Dateimuster, die nie mitgehen.
AUSGESCHLOSSENE_MUSTER = ("*.pyc", "*.pyo", "*.iso", "*.tar.gz", "*.log", "*.swp")


def gehoert_dazu(pfad: Path, wurzel: Path) -> bool:
    relativ = pfad.relative_to(wurzel)
    if any(teil in AUSGESCHLOSSENE_ORDNER for teil in relativ.parts):
        return False
    if any(relativ.match(muster) for muster in AUSGESCHLOSSENE_MUSTER):
        return False
    if relativ.suffix == ".egg-info" or ".egg-info" in str(relativ):
        return False
    return True


def main(ziel: Path) -> int:
    quelle = Path(__file__).resolve().parent.parent

    if not (ziel / ".git").is_dir():
        print(f"Fehler: {ziel} ist kein geklontes Repository.", file=sys.stderr)
        return 2

    kopiert = 0
    bytes_gesamt = 0
    for datei in sorted(quelle.rglob("*")):
        if not datei.is_file() or not gehoert_dazu(datei, quelle):
            continue
        relativ = datei.relative_to(quelle)
        zieldatei = ziel / relativ
        zieldatei.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(datei, zieldatei)
        kopiert += 1
        bytes_gesamt += datei.stat().st_size

    print(f"  {kopiert} Dateien kopiert ({bytes_gesamt / 1048576:.1f} MB)")
    print(f"  nach {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
