"""The expression tree. Every node knows the slice of the source it was read from."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agnostic_cel.errors import Span

LiteralKind = Literal["bool", "int", "uint", "double", "string", "bytes", "null"]
ComprehensionKind = Literal["all", "exists", "exists_one", "map", "filter"]


@dataclass(frozen=True, slots=True)
class Node:
    span: Span


@dataclass(frozen=True, slots=True)
class Lit(Node):
    kind: LiteralKind
    value: object


@dataclass(frozen=True, slots=True)
class Ident(Node):
    name: str


@dataclass(frozen=True, slots=True)
class Select(Node):
    """``operand.field``."""

    operand: Node
    field: str


@dataclass(frozen=True, slots=True)
class Index(Node):
    """``operand[index]``."""

    operand: Node
    index: Node


@dataclass(frozen=True, slots=True)
class Call(Node):
    """``function(args)`` or, with a target, ``target.function(args)``."""

    function: str
    args: tuple[Node, ...]
    target: Node | None = None


@dataclass(frozen=True, slots=True)
class Has(Node):
    """``has(operand.field)``: whether a map has the key."""

    operand: Node
    field: str


@dataclass(frozen=True, slots=True)
class Comprehension(Node):
    """``range.all(var, predicate)`` and the other macros over a list (its items) or a map (its keys)."""

    kind: ComprehensionKind
    range: Node
    var: str
    predicate: Node | None
    """``all``/``exists``/``exists_one``/``filter`` test it; ``map`` with three arguments filters by it."""
    transform: Node | None = None
    """``map``'s result expression."""


@dataclass(frozen=True, slots=True)
class ListExpr(Node):
    items: tuple[Node, ...]


@dataclass(frozen=True, slots=True)
class MapExpr(Node):
    entries: tuple[tuple[Node, Node], ...]


@dataclass(frozen=True, slots=True)
class Unary(Node):
    op: Literal["!", "-"]
    operand: Node


@dataclass(frozen=True, slots=True)
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass(frozen=True, slots=True)
class Conditional(Node):
    """``condition ? then : otherwise``."""

    condition: Node
    then: Node
    otherwise: Node


def ternary_chain(node: Node) -> list[Node]:
    """``a ? x : b ? y : z`` as its branches' heads: ``[a ? x, b ? y, z]`` read as the top-level ``:`` splits.

    Returns the conditionals and the final branch, outermost first; a non-conditional is a chain of one.
    """
    chain: list[Node] = []
    current = node
    while isinstance(current, Conditional):
        chain.append(current)
        current = current.otherwise
    chain.append(current)
    return chain
