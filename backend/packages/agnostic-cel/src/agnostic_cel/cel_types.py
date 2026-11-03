"""CEL's types as the checker reasons about them. ``dyn`` stands for anything, so it fits everywhere."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CelType:
    name: str
    params: tuple[CelType, ...] = ()

    def __str__(self) -> str:
        if not self.params:
            return self.name
        return f"{self.name}<{', '.join(str(param) for param in self.params)}>"

    @property
    def is_dyn(self) -> bool:
        return self.name == "dyn"

    @property
    def element(self) -> CelType:
        """A list's items, a map's values; ``dyn`` for anything else."""
        if self.name == "list":
            return self.params[0]
        if self.name == "map":
            return self.params[1]
        return DYN

    @property
    def key(self) -> CelType:
        return self.params[0] if self.name == "map" else DYN

    def fits(self, other: CelType) -> bool:
        """Whether a value of this type can stand where ``other`` is expected (or the reverse is unknown)."""
        if self.is_dyn or other.is_dyn:
            return True
        if self.name != other.name or len(self.params) != len(other.params):
            return False
        return all(mine.fits(theirs) for mine, theirs in zip(self.params, other.params, strict=True))


DYN = CelType("dyn")
BOOL = CelType("bool")
INT = CelType("int")
UINT = CelType("uint")
DOUBLE = CelType("double")
STRING = CelType("string")
BYTES = CelType("bytes")
NULL = CelType("null_type")
NUMERIC = (INT, UINT, DOUBLE)


def list_of(item: CelType) -> CelType:
    return CelType("list", (item,))


def map_of(key: CelType, value: CelType) -> CelType:
    return CelType("map", (key, value))


def unify(first: CelType, second: CelType) -> CelType:
    """The type both branches share, ``dyn`` when they differ."""
    if first == second:
        return first
    if first.name == second.name and first.params and len(first.params) == len(second.params):
        return CelType(first.name, tuple(unify(a, b) for a, b in zip(first.params, second.params, strict=True)))
    return DYN
