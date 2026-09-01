"""Katalog: Datenmodell, YAML-Loader und Praedikat-Auswertung."""

from .loader import CatalogError, load_catalog
from .models import (
    Arity,
    BootContribution,
    CapabilitySpec,
    Catalog,
    Category,
    Choice,
    EnableIn,
    FieldSpec,
    FileEntry,
    Option,
    OptionGroup,
    PackageRef,
    PageType,
    SelectionMode,
    ServiceAction,
    ServiceRef,
    ServiceScope,
)
from .predicate import ALWAYS, EvaluationContext, Predicate, PredicateError

__all__ = [
    "ALWAYS",
    "Arity",
    "BootContribution",
    "CapabilitySpec",
    "Catalog",
    "CatalogError",
    "Category",
    "Choice",
    "EnableIn",
    "EvaluationContext",
    "FieldSpec",
    "FileEntry",
    "Option",
    "OptionGroup",
    "PackageRef",
    "PageType",
    "Predicate",
    "PredicateError",
    "SelectionMode",
    "ServiceAction",
    "ServiceRef",
    "ServiceScope",
    "load_catalog",
]
