"""The functions and methods available to workflow expressions, with the docs the editor shows on hover."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agnostic_cel.cel_types import BOOL, BYTES, DOUBLE, DYN, INT, STRING, UINT, CelType


@dataclass(frozen=True, slots=True)
class Overload:
    receiver: CelType | None
    """``None`` for a global function such as ``size(x)``."""
    params: tuple[CelType, ...]
    result: CelType


@dataclass(frozen=True, slots=True)
class Function:
    name: str
    overloads: tuple[Overload, ...]
    signature: str
    doc: str

    @property
    def is_method(self) -> bool:
        return any(overload.receiver is not None for overload in self.overloads)


_LIST = CelType("list", (DYN,))
_MAP = CelType("map", (DYN, DYN))

FUNCTIONS: Mapping[str, Function] = {
    function.name: function
    for function in (
        Function(
            "contains",
            (Overload(STRING, (STRING,), BOOL),),
            "string.contains(substring) -> bool",
            "Whether the string contains `substring` (case-sensitive).",
        ),
        Function(
            "startsWith",
            (Overload(STRING, (STRING,), BOOL),),
            "string.startsWith(prefix) -> bool",
            "Whether the string starts with `prefix`.",
        ),
        Function(
            "endsWith",
            (Overload(STRING, (STRING,), BOOL),),
            "string.endsWith(suffix) -> bool",
            "Whether the string ends with `suffix`.",
        ),
        Function(
            "matches",
            (Overload(STRING, (STRING,), BOOL), Overload(None, (STRING, STRING), BOOL)),
            "string.matches(regex) -> bool",
            "Whether the regular expression matches anywhere in the string (RE2 syntax).",
        ),
        Function(
            "size",
            (
                Overload(STRING, (), INT),
                Overload(BYTES, (), INT),
                Overload(_LIST, (), INT),
                Overload(_MAP, (), INT),
                Overload(None, (DYN,), INT),
            ),
            "size(value) -> int",
            "Characters in a string, bytes in bytes, items in a list or entries in a map.",
        ),
        Function("int", (Overload(None, (DYN,), INT),), "int(value) -> int", "Converts a number or a string to int."),
        Function(
            "uint", (Overload(None, (DYN,), UINT),), "uint(value) -> uint", "Converts a number or a string to uint."
        ),
        Function(
            "double",
            (Overload(None, (DYN,), DOUBLE),),
            "double(value) -> double",
            "Converts a number or a string to double.",
        ),
        Function(
            "string",
            (Overload(None, (DYN,), STRING),),
            "string(value) -> string",
            "Converts a number, bool or bytes to its text.",
        ),
        Function(
            "bool",
            (Overload(None, (DYN,), BOOL),),
            "bool(value) -> bool",
            'Converts "true" or "false" to bool.',
        ),
        Function("dyn", (Overload(None, (DYN,), DYN),), "dyn(value) -> dyn", "Turns off type checks for the value."),
    )
}

MACROS: Mapping[str, str] = {
    "has": "has(map.key) -> bool · Whether the map has the key.",
    "all": "list.all(x, predicate) -> bool · Whether the predicate holds for every item (a map's keys).",
    "exists": "list.exists(x, predicate) -> bool · Whether the predicate holds for at least one item.",
    "exists_one": "list.exists_one(x, predicate) -> bool · Whether the predicate holds for exactly one item.",
    "map": "list.map(x, expression) -> list · The expression for every item; map(x, filter, expression) filters first.",
    "filter": "list.filter(x, predicate) -> list · The items the predicate holds for.",
}
