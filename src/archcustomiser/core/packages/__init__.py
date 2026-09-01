"""Paketvalidierung gegen die echten Arch-Repositories.

Kein Per-Paket-Abfrageclient, sondern ein Index-Anbieter: die Sync-Datenbanken
werden einmal geladen und danach im Speicher durchsucht. Namen, Gruppen,
virtuelle Pakete und Tippfehler-Vorschlaege fallen dabei aus derselben Quelle
an -- ueber Einzelabfragen waeren Gruppen und virtuelle Pakete gar nicht
beantwortbar.
"""

from .backend import PackageConfig, RefreshPolicy
from .errors import (
    BackendUnavailable,
    CacheError,
    InvalidPackageName,
    MirrorError,
    NetworkUnavailable,
    PackageLayerError,
    RepositoryDataError,
    StaleDataError,
)
from .index import RepoIndex
from .models import (
    EntryKind,
    Freshness,
    IndexMetadata,
    PackageInfo,
    Resolution,
    ValidationReport,
)
from .names import is_valid, parse_list, validate_name
from .service import PackageService, default_backend

__all__ = [
    "BackendUnavailable",
    "CacheError",
    "EntryKind",
    "Freshness",
    "IndexMetadata",
    "InvalidPackageName",
    "MirrorError",
    "NetworkUnavailable",
    "PackageConfig",
    "PackageInfo",
    "PackageLayerError",
    "PackageService",
    "RefreshPolicy",
    "RepoIndex",
    "RepositoryDataError",
    "Resolution",
    "StaleDataError",
    "ValidationReport",
    "default_backend",
    "is_valid",
    "parse_list",
    "validate_name",
]
