"""A tree-walking evaluator for the same subset, used when the instance can't evaluate an expression itself.

It follows CEL's semantics where agno's evaluator (cel-python) does: no implicit int/double arithmetic, errors
absorbed by ``&&``/``||`` when the other side decides, a missing map key is an error. It only ever computes a value:
there are no side effects, and a step budget bounds the work an expression can do.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast

from agnostic_cel.errors import CelEvalError, CelSyntaxError
from agnostic_cel.nodes import (
    Binary,
    Call,
    Comprehension,
    Conditional,
    Has,
    Ident,
    Index,
    ListExpr,
    Lit,
    MapExpr,
    Node,
    Select,
    Unary,
)
from agnostic_cel.parser import parse

MAX_STEPS = 20_000
MAX_REGEX = 500
INT_MIN, INT_MAX = -(2**63), 2**63 - 1
UINT_MAX = 2**64 - 1


class Uint(int):
    """An unsigned CEL integer; plain ``int`` is CEL's signed ``int``."""

    __slots__ = ()


def evaluate(source: str, variables: Mapping[str, Any]) -> object:
    """Raises :class:`CelSyntaxError` for a bad expression and :class:`CelEvalError` when evaluation fails."""
    tree = parse(source)
    return _Evaluator(dict(variables)).eval(tree)


def type_name(value: object) -> str:  # noqa: PLR0911
    if value is None:
        return "null_type"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, Uint):
        return "uint"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "map"
    return type(value).__name__


class _Evaluator:
    def __init__(self, variables: dict[str, Any]) -> None:
        self.scopes: list[dict[str, Any]] = [variables]
        self.steps = 0

    def eval(self, node: Node) -> Any:  # noqa: ANN401, C901, PLR0911, PLR0912
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise CelEvalError("The expression did too much work and was stopped.", node.span)
        if isinstance(node, Lit):
            return Uint(node.value) if node.kind == "uint" else node.value  # pyright: ignore[reportArgumentType]
        if isinstance(node, Ident):
            for scope in reversed(self.scopes):
                if node.name in scope:
                    return scope[node.name]
            raise CelEvalError(f"undeclared reference to '{node.name}'", node.span)
        if isinstance(node, Select):
            return self._key(self.eval(node.operand), node.field, node)
        if isinstance(node, Has):
            operand = self.eval(node.operand)
            if not isinstance(operand, dict):
                raise CelEvalError(f"has() needs a map, not {type_name(operand)}", node.span)
            return node.field in operand
        if isinstance(node, Index):
            return self._index(self.eval(node.operand), self.eval(node.index), node)
        if isinstance(node, Call):
            return self._call(node)
        if isinstance(node, Comprehension):
            return self._comprehension(node)
        if isinstance(node, ListExpr):
            return [self.eval(item) for item in node.items]
        if isinstance(node, MapExpr):
            return {self.eval(key): self.eval(value) for key, value in node.entries}
        if isinstance(node, Unary):
            return self._unary(node)
        if isinstance(node, Binary):
            return self._binary(node)
        if isinstance(node, Conditional):
            condition = self.eval(node.condition)
            if not isinstance(condition, bool):
                raise CelEvalError(f"no matching overload for '_?_:_' applied to {type_name(condition)}", node.span)
            return self.eval(node.then if condition else node.otherwise)
        raise CelEvalError(f"Can't evaluate {type(node).__name__}.", node.span)

    def _key(self, operand: object, key: object, node: Node) -> Any:  # noqa: ANN401
        if not isinstance(operand, dict):
            raise CelEvalError(f"{type_name(operand)} has no field '{key}'", node.span)
        mapping: dict[Any, Any] = operand  # pyright: ignore[reportUnknownVariableType]
        for candidate, value in mapping.items():
            if _equals(candidate, key):
                return value
        raise CelEvalError(f"no such key: '{key}'", node.span)

    def _index(self, operand: object, index: object, node: Index) -> Any:  # noqa: ANN401
        if isinstance(operand, list):
            if not isinstance(index, int) or isinstance(index, bool):
                raise CelEvalError(f"a list index must be int, not {type_name(index)}", node.index.span)
            items: list[Any] = operand  # pyright: ignore[reportUnknownVariableType]
            if not 0 <= index < len(items):
                raise CelEvalError(f"index {index} out of range", node.index.span)
            return items[index]
        return self._key(operand, index, node)

    def _call(self, node: Call) -> Any:  # noqa: ANN401, C901, PLR0911
        args = [self.eval(arg) for arg in node.args]
        target = self.eval(node.target) if node.target is not None else None
        name = node.function
        if node.target is not None and name in {"contains", "startsWith", "endsWith", "matches"}:
            if not isinstance(target, str) or len(args) != 1 or not isinstance(args[0], str):
                raise CelEvalError(f"no matching overload for '{name}'", node.span)
            value: str = args[0]
            if name == "contains":
                return value in target
            if name == "startsWith":
                return target.startswith(value)
            if name == "endsWith":
                return target.endswith(value)
            return self._matches(target, value, node)
        if name == "matches" and node.target is None and len(args) == 2:  # noqa: PLR2004
            if not all(isinstance(arg, str) for arg in args):
                raise CelEvalError("no matching overload for 'matches'", node.span)
            return self._matches(str(args[0]), str(args[1]), node)
        if name == "size":
            subject = target if node.target is not None else (args[0] if len(args) == 1 else None)
            if isinstance(subject, str | bytes | list | dict):
                return len(subject)  # pyright: ignore[reportUnknownArgumentType]
            raise CelEvalError(f"no matching overload for 'size' applied to {type_name(subject)}", node.span)
        if node.target is None and len(args) == 1 and name in {"int", "uint", "double", "string", "bool", "dyn"}:
            return _convert(name, args[0], node)
        raise CelEvalError(f"unknown function '{name}'", node.span)

    def _matches(self, text: str, pattern: str, node: Node) -> bool:
        if len(pattern) > MAX_REGEX:
            raise CelEvalError(f"The pattern is longer than {MAX_REGEX} characters.", node.span)
        try:
            return re.search(pattern, text) is not None
        except re.error as exc:
            raise CelEvalError(f"invalid regular expression: {exc}", node.span) from exc

    def _comprehension(self, node: Comprehension) -> Any:  # noqa: ANN401, C901, PLR0912
        subject = self.eval(node.range)
        if isinstance(subject, dict):
            items: list[Any] = list(subject)  # pyright: ignore[reportUnknownArgumentType]
        elif isinstance(subject, list):
            items = list(subject)  # pyright: ignore[reportUnknownArgumentType]
        else:
            raise CelEvalError(f"'{node.kind}' needs a list or a map, not {type_name(subject)}", node.range.span)
        matched: list[Any] = []
        results: list[Any] = []
        for item in items:
            self.scopes.append({node.var: item})
            try:
                keep = True
                if node.predicate is not None:
                    keep = self.eval(node.predicate)
                    if not isinstance(keep, bool):
                        raise CelEvalError("the predicate must return bool", node.predicate.span)
                if keep:
                    matched.append(item)
                    if node.kind == "map" and node.transform is not None:
                        results.append(self.eval(node.transform))
            finally:
                self.scopes.pop()
            if node.kind == "all" and not keep:
                return False
            if node.kind == "exists" and keep:
                return True
        if node.kind == "all":
            return True
        if node.kind == "exists":
            return False
        if node.kind == "exists_one":
            return len(matched) == 1
        return results if node.kind == "map" else matched

    def _unary(self, node: Unary) -> Any:  # noqa: ANN401
        operand = self.eval(node.operand)
        if node.op == "!":
            if not isinstance(operand, bool):
                raise CelEvalError(f"no matching overload for '!_' applied to {type_name(operand)}", node.span)
            return not operand
        if isinstance(operand, bool | Uint) or not isinstance(operand, int | float):
            raise CelEvalError(f"no matching overload for '-_' applied to {type_name(operand)}", node.span)
        return _checked(-operand, node)

    def _binary(self, node: Binary) -> Any:  # noqa: ANN401
        op = node.op
        if op in {"&&", "||"}:
            return self._logical(node)
        left = self.eval(node.left)
        right = self.eval(node.right)
        if op == "==":
            return _equals(left, right)
        if op == "!=":
            return not _equals(left, right)
        if op == "in":
            if isinstance(right, list | dict):
                members: list[Any] = list(right)  # pyright: ignore[reportUnknownArgumentType]
                return any(_equals(left, member) for member in members)
            raise CelEvalError(f"no matching overload for '@in' applied to {type_name(right)}", node.span)
        if op in {"<", "<=", ">", ">="}:
            return _compare(op, left, right, node)
        return _arithmetic(op, left, right, node)

    def _logical(self, node: Binary) -> bool:
        decisive = node.op == "||"
        failure: CelEvalError | None = None
        for side in (node.left, node.right):
            try:
                value = self.eval(side)
            except CelEvalError as exc:
                failure = failure or exc
                continue
            if not isinstance(value, bool):
                failure = failure or CelEvalError(
                    f"no matching overload for '_{node.op}_' applied to {type_name(value)}", side.span
                )
                continue
            if value is decisive:
                return decisive
        if failure is not None:
            raise failure
        return not decisive


def _equals(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, int | float) and isinstance(right, int | float):
        return left == right
    if type_name(left) != type_name(right):
        return False
    if isinstance(left, list) and isinstance(right, list):
        mine: list[Any] = left  # pyright: ignore[reportUnknownVariableType]
        theirs: list[Any] = right  # pyright: ignore[reportUnknownVariableType]
        return len(mine) == len(theirs) and all(_equals(a, b) for a, b in zip(mine, theirs, strict=True))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equals(left[key], right[key]) for key in left)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return left == right


def _compare(op: str, left: object, right: object, node: Node) -> bool:
    numeric = all(isinstance(side, int | float) and not isinstance(side, bool) for side in (left, right))
    same = type_name(left) == type_name(right) and isinstance(left, str | bytes | bool | int | float)
    if not (numeric or same):
        raise CelEvalError(
            f"no matching overload for '_{op}_' applied to ({type_name(left)}, {type_name(right)})", node.span
        )
    a: Any = left
    b: Any = right
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def _arithmetic(op: str, left: object, right: object, node: Node) -> object:  # noqa: C901, PLR0911
    kind = type_name(left)
    if kind != type_name(right):
        raise CelEvalError(f"no matching overload for '_{op}_' applied to ({kind}, {type_name(right)})", node.span)
    if op == "+":
        if isinstance(left, str | bytes | list) and isinstance(right, str | bytes | list):
            return left + right  # pyright: ignore[reportOperatorIssue, reportUnknownVariableType]
        if kind in {"int", "uint", "double"}:
            total = _number(cast("object", left)) + _number(right)
            return _checked(total, node, unsigned=kind == "uint", floating=kind == "double")
    elif kind in {"int", "uint", "double"}:
        a, b = _number(left), _number(right)
        if op in {"/", "%"} and b == 0 and kind != "double":
            raise CelEvalError("division by zero" if op == "/" else "modulus by zero", node.span)
        if op == "-":
            return _checked(a - b, node, unsigned=kind == "uint", floating=kind == "double")
        if op == "*":
            return _checked(a * b, node, unsigned=kind == "uint", floating=kind == "double")
        if op == "/":
            if kind == "double":
                return a / b if b else (float("inf") if a > 0 else float("-inf") if a < 0 else float("nan"))
            quotient = abs(int(a)) // abs(int(b))
            return _checked(quotient if (a >= 0) == (b > 0) else -quotient, node, unsigned=kind == "uint")
        if op == "%" and kind != "double":
            remainder = abs(int(a)) % abs(int(b))
            return _checked(remainder if a >= 0 else -remainder, node, unsigned=kind == "uint")
    raise CelEvalError(f"no matching overload for '_{op}_' applied to ({kind}, {kind})", node.span)


def _number(value: object) -> int | float:
    assert isinstance(value, int | float)
    return value


def _checked(value: float, node: Node, *, unsigned: bool = False, floating: bool = False) -> object:
    if floating or isinstance(value, float):
        return float(value)
    if unsigned:
        if not 0 <= value <= UINT_MAX:
            raise CelEvalError("unsigned integer overflow", node.span)
        return Uint(value)
    if not INT_MIN <= value <= INT_MAX:
        raise CelEvalError("integer overflow", node.span)
    return int(value)


def _convert(name: str, value: object, node: Node) -> object:  # noqa: C901, PLR0911
    try:
        if name == "dyn":
            return value
        if name == "string":
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, bytes):
                return value.decode("utf-8")
            if isinstance(value, str | int | float):
                return str(value)
        elif name == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value in {"true", "false", "True", "False", "1", "0", "t", "f"}:
                return value in {"true", "True", "1", "t"}
        elif name in {"int", "uint"} and isinstance(value, str | int | float) and not isinstance(value, bool):
            return _checked(int(value), node, unsigned=name == "uint")
        elif name == "double" and isinstance(value, str | int | float) and not isinstance(value, bool):
            return float(value)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CelEvalError(f"can't convert {type_name(value)} to {name}: {exc}", node.span) from exc
    raise CelEvalError(f"no matching overload for '{name}' applied to {type_name(value)}", node.span)


__all__ = ["CelEvalError", "CelSyntaxError", "Uint", "evaluate", "type_name"]
