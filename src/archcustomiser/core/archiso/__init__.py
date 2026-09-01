"""Erzeugung von archiso-Profilen.

Das Profil entsteht als ``ProfileTree`` im Speicher und wird erst danach
geschrieben -- als Verzeichnis (POSIX) oder als tar-Archiv (ueberall).
"""

from .errors import (
    DuplicateEntryError,
    HashingUnavailable,
    MissingAssetError,
    ProfileError,
    SinkError,
    SymlinksUnsupportedError,
    TargetNotEmptyError,
    UnsafePathError,
    UnsafeValueError,
)
from .generator import GeneratedProfile, ProfileGenerator
from .settings import ArchisoSettings, build_settings
from .sinks import DirectorySink, TarSink
from .tree import ProfileTree, TreeFile, TreeSymlink

__all__ = [
    "ArchisoSettings",
    "DirectorySink",
    "DuplicateEntryError",
    "GeneratedProfile",
    "HashingUnavailable",
    "MissingAssetError",
    "ProfileError",
    "ProfileGenerator",
    "ProfileTree",
    "SinkError",
    "SymlinksUnsupportedError",
    "TarSink",
    "TargetNotEmptyError",
    "TreeFile",
    "TreeSymlink",
    "UnsafePathError",
    "UnsafeValueError",
    "build_settings",
]
