"""Strukturierte Prädikate für Katalogbedingungen.

Bewusst KEIN ``eval`` und keine Ausdruckssprache: der Katalog ist erweiterbar
und kann aus einem Benutzer-Overlay stammen. Eine Mini-Sprache aus verschachtelten
Dicts ist ausdrucksstark genug für ``visible_when``/``enabled_when`` und kann
strukturell keinen Code ausführen.

Grammatik::

    predicate := leaf | {"all_of": [predicate, ...]}
                      | {"any_of": [predicate, ...]}
                      | {"none_of": [predicate, ...]}
    leaf      := "<kategorie>.<option>"   -- Option ist ausgewählt
               | "cap:<name>"             -- Capability wird bereitgestellt
               | "field:<binding>=<wert>" -- Formularfeld hat diesen Wert
               | "field:<binding>"        -- Formularfeld ist gesetzt/wahr

Ein Dict darf mehrere Schlüssel tragen; sie werden UND-verknüpft.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

_OPERATORS = ("all_of", "any_of", "none_of")


class PredicateError(ValueError):
    """Syntaktisch ungültiges Prädikat im Katalog."""


class EvaluationContext(Protocol):
    """Was ein Prädikat über den aktuellen Zustand wissen darf."""

    def is_selected(self, ref: str) -> bool: ...
    def has_capability(self, name: str) -> bool: ...
    def field_value(self, binding: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class Predicate:
    """Vorgeparstes Prädikat. ``None`` als Rohwert bedeutet 'immer wahr'."""

    raw: Any

    def evaluate(self, context: EvaluationContext) -> bool:
        return _evaluate(self.raw, context)

    def references(self) -> frozenset[str]:
        """Alle Options-Refs, die dieses Prädikat liest.

        Der Store nutzt das, um nur betroffene Seiten neu zu zeichnen.
        """
        found: set[str] = set()
        _collect(self.raw, found)
        return frozenset(found)

    @property
    def is_always_true(self) -> bool:
        return self.raw is None


ALWAYS = Predicate(None)


def parse(raw: Any, *, where: str = "<katalog>") -> Predicate:
    """Validiert die Struktur sofort, damit Fehler beim Laden auffallen."""
    if raw is None:
        return ALWAYS
    _validate(raw, where)
    return Predicate(raw)


def _validate(node: Any, where: str) -> None:
    if isinstance(node, str):
        if not node.strip():
            raise PredicateError(f"{where}: leeres Prädikat")
        return
    if isinstance(node, bool):
        return
    if isinstance(node, list):
        for item in node:
            _validate(item, where)
        return
    if isinstance(node, dict):
        unknown = set(node) - set(_OPERATORS)
        if unknown:
            raise PredicateError(
                f"{where}: unbekannte Prädikat-Operatoren {sorted(unknown)}; "
                f"erlaubt sind {list(_OPERATORS)}"
            )
        if not node:
            raise PredicateError(f"{where}: leeres Prädikat-Objekt")
        for key, value in node.items():
            if not isinstance(value, list):
                raise PredicateError(f"{where}: '{key}' erwartet eine Liste")
            for item in value:
                _validate(item, where)
        return
    raise PredicateError(f"{where}: Prädikat muss Text, Liste oder Objekt sein, nicht {type(node).__name__}")


def _evaluate(node: Any, context: EvaluationContext) -> bool:
    if node is None:
        return True
    if isinstance(node, bool):
        return node
    if isinstance(node, str):
        return _evaluate_leaf(node, context)
    if isinstance(node, list):
        # Nackte Liste = all_of, das ist die intuitive Lesart.
        return all(_evaluate(item, context) for item in node)
    if isinstance(node, dict):
        results = []
        if "all_of" in node:
            results.append(all(_evaluate(i, context) for i in node["all_of"]))
        if "any_of" in node:
            results.append(any(_evaluate(i, context) for i in node["any_of"]))
        if "none_of" in node:
            results.append(not any(_evaluate(i, context) for i in node["none_of"]))
        return all(results)
    return False


def _evaluate_leaf(leaf: str, context: EvaluationContext) -> bool:
    leaf = leaf.strip()
    if leaf.startswith("cap:"):
        return context.has_capability(leaf[4:].strip())
    if leaf.startswith("field:"):
        expression = leaf[6:].strip()
        if "=" in expression:
            binding, _, expected = expression.partition("=")
            actual = context.field_value(binding.strip())
            return _loose_equal(actual, expected.strip())
        return bool(context.field_value(expression))
    return context.is_selected(leaf)


def _loose_equal(actual: Any, expected: str) -> bool:
    """YAML kennt keine Typen im Prädikat-String -- also nachsichtig vergleichen."""
    if isinstance(actual, bool):
        return expected.lower() in ("true", "yes", "1") if actual else expected.lower() in ("false", "no", "0")
    if actual is None:
        return expected.lower() in ("", "none", "null")
    return str(actual) == expected


def _collect(node: Any, found: set[str]) -> None:
    if isinstance(node, str):
        leaf = node.strip()
        if not leaf.startswith(("cap:", "field:")):
            found.add(leaf)
    elif isinstance(node, list):
        for item in node:
            _collect(item, found)
    elif isinstance(node, dict):
        for value in node.values():
            if isinstance(value, list):
                for item in value:
                    _collect(item, found)
