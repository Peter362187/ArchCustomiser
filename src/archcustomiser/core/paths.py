"""Plattformabhängige Verzeichnisse.

XDG unter Linux, LOCALAPPDATA unter Windows, ~/Library unter macOS.

Bewusst ohne Fremdbibliothek: das sind vier Zeilen Logik und eine Abhängigkeit
weniger, die auf dem Zielsystem paketiert werden müsste.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "archcustomiser"
APP_NAME_WIN = "ArchCustomiser"
# Auf macOS gilt derselbe Name in Grossschreibung -- und ausgeschriebene
# Verzeichnisse statt Punktverzeichnissen: die sind im Finder unsichtbar,
# und wer sein Profil oder das Protokoll suchen soll, findet es sonst nicht.
APP_NAME_MAC = "ArchCustomiser"


def _mac_base(*teile: str) -> Path:
    return Path.home().joinpath("Library", *teile) / APP_NAME_MAC


def _windows_base(env_var: str, fallback: str) -> Path:
    root = os.environ.get(env_var)
    if root:
        return Path(root)
    return Path.home() / "AppData" / fallback


def _xdg(env_var: str, fallback: str) -> Path:
    root = os.environ.get(env_var)
    if root:
        return Path(root)
    return Path.home() / fallback


def cache_dir() -> Path:
    """Rein derivative Daten. Löschen ist immer sicher."""
    if os.name == "nt":
        return _windows_base("LOCALAPPDATA", "Local") / APP_NAME_WIN / "Cache"
    if sys.platform == "darwin":
        return _mac_base("Caches")
    return _xdg("XDG_CACHE_HOME", ".cache") / APP_NAME


def config_dir() -> Path:
    """Benutzereinstellungen und Katalog-Overlays."""
    if os.name == "nt":
        return _windows_base("APPDATA", "Roaming") / APP_NAME_WIN
    if sys.platform == "darwin":
        return _mac_base("Application Support")
    return _xdg("XDG_CONFIG_HOME", ".config") / APP_NAME


def state_dir() -> Path:
    """Logs und sonstiger veränderlicher Zustand."""
    if os.name == "nt":
        return _windows_base("LOCALAPPDATA", "Local") / APP_NAME_WIN / "State"
    if sys.platform == "darwin":
        return _mac_base("Logs")
    return _xdg("XDG_STATE_HOME", ".local/state") / APP_NAME


def user_profiles_dir() -> Path:
    return config_dir() / "profiles"


def user_catalog_dir() -> Path:
    return config_dir() / "catalog"


def package_root() -> Path:
    """Wurzel des installierten Pakets (src/archcustomiser)."""
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Ausgelieferte Daten: data/catalog, profiles, assets.

    Sucht zuerst neben dem Paket (Wheel-Installation), dann im Repo-Layout.
    """
    candidates = [
        package_root() / "data",
        package_root().parent.parent / "data",
    ]
    for candidate in candidates:
        if (candidate / "catalog" / "catalog.yaml").is_file():
            return candidate
    return candidates[-1]


def bundled_profiles_dir() -> Path:
    candidates = [
        package_root() / "profiles",
        package_root().parent.parent / "profiles",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[-1]


def ensure_dir(path: Path, *, mode: int = 0o700) -> Path:
    """Legt ein Verzeichnis an; unter POSIX mit restriktiven Rechten."""
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            path.chmod(mode)
        except OSError:
            pass
    return path
