"""Static checks of an expression in its place in a workflow.

Unknown names, operators and methods that don't apply to the operands, the result type the node needs, and (for a
Router) whether every possible result is a choice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from agnostic_cel.cel_types import (
    BOOL,
    BYTES,
    DOUBLE,
    DYN,
    INT,
    NULL,
    NUMERIC,
    STRING,
    UINT,
    CelType,
    list_of,
    map_of,
    unify,
)
from agnostic_cel.contexts import CONTEXTS, ContextName
from agnostic_cel.errors import CelSyntaxError, Span
from agnostic_cel.functions import FUNCTIONS
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

Severity = Literal["error", "warning", "info"]
_LITERAL_TYPES: Mapping[str, CelType] = {
    "bool": BOOL,
    "int": INT,
    "uint": UINT,
    "double": DOUBLE,
    "string": STRING,
    "bytes": BYTES,
    "null": NULL,
}


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: str
    message: str
    span: Span

    def as_dict(self) -> dict[str, object]:
        return {"severity": self.severity, "code": self.code, "message": self.message, "span": self.span.as_dict()}


@dataclass(frozen=True, slots=True)
class CheckResult:
    type: str | None
    """The inferred result type; ``None`` when the expression doesn't parse."""
    findings: tuple[Finding, ...]
    results: tuple[str, ...] | None = None
    """For a Router: every literal the expression can return, or ``None`` when some branch isn't a literal."""
    exhaustive: bool | None = None
    """For a Router: whether every result is a choice (``None`` when that can't be proved)."""
    summary: str = ""

    @property
    def ok(self) -> bool:
        return not any(finding.severity == "error" for finding in self.findings)


def check(source: str, context: ContextName, *, choices: Iterable[str] | None = None) -> CheckResult:
    try:
        tree = parse(source)
    except CelSyntaxError as exc:
        span = exc.span or Span(0, len(source))
        return CheckResult(None, (Finding("error", "syntax", exc.message, span),), summary=exc.message)
    checker = _Checker(context)
    inferred = checker.infer(tree)
    expected = CONTEXTS[context].result
    findings = checker.findings
    if not inferred.fits(expected):
        findings.append(
            Finding(
                "error",
                "result_type",
                f"Returns {inferred}, but a {CONTEXTS[context].label.lower()} needs {expected}.",
                tree.span,
            )
        )
    elif inferred.is_dyn:
        findings.append(
            Finding(
                "info",
                "result_unknown",
                f"The result type can't be told before it runs; make sure it returns {expected}.",
                tree.span,
            )
        )
    results: tuple[str, ...] | None = None
    exhaustive: bool | None = None
    if context == "router" and choices is not None:
        results, exhaustive = _router(tree, list(choices), findings)
    return CheckResult(
        str(inferred),
        tuple(findings),
        results,
        exhaustive,
        _summary(inferred, findings, context, exhaustive=exhaustive),
    )


def _router(tree: Node, choices: list[str], findings: list[Finding]) -> tuple[tuple[str, ...] | None, bool | None]:
    literals = _literal_results(tree)
    if literals is None:
        findings.append(
            Finding(
                "warning",
                "router_unproven",
                "Some results aren't literal names, so it can't be proved that every result matches a choice.",
                tree.span,
            )
        )
        return None, None
    names = {literal.value for literal in literals}
    exhaustive = True
    for literal in literals:
        if literal.value not in choices:
            exhaustive = False
            listed = ", ".join(f"`{choice}`" for choice in choices) or "none"
            findings.append(
                Finding(
                    "error",
                    "router_unknown_choice",
                    f"`{literal.value}` isn't a choice of this router (choices: {listed}).",
                    literal.span,
                )
            )
    findings.extend(
        Finding("info", "router_choice_unused", f"The selector never picks `{choice}`.", tree.span)
        for choice in choices
        if choice not in names
    )
    ordered = tuple(dict.fromkeys(str(literal.value) for literal in literals))
    return ordered, exhaustive


def _literal_results(node: Node) -> list[Lit] | None:
    if isinstance(node, Lit) and node.kind == "string":
        return [node]
    if isinstance(node, Conditional):
        then = _literal_results(node.then)
        otherwise = _literal_results(node.otherwise)
        return None if then is None or otherwise is None else [*then, *otherwise]
    return None


def _summary(inferred: CelType, findings: list[Finding], context: ContextName, *, exhaustive: bool | None) -> str:
    errors = [finding for finding in findings if finding.severity == "error"]
    if errors:
        return errors[0].message
    if context != "router" or (exhaustive is None and not any(f.code == "router_unproven" for f in findings)):
        return f"Returns {inferred}"
    if exhaustive:
        return f"Returns {inferred} · every result matches a choice"
    return f"Returns {inferred} · can't prove every result matches a choice"


@dataclass
class _Checker:
    context: ContextName
    findings: list[Finding] = field(default_factory=list[Finding])
    scopes: list[dict[str, CelType]] = field(default_factory=list[dict[str, CelType]])

    def error(self, code: str, message: str, span: Span) -> CelType:
        self.findings.append(Finding("error", code, message, span))
        return DYN

    def infer(self, node: Node) -> CelType:  # noqa: C901, PLR0911, PLR0912
        if isinstance(node, Lit):
            return _LITERAL_TYPES[node.kind]
        if isinstance(node, Ident):
            return self._ident(node)
        if isinstance(node, Select):
            return self._select(self.infer(node.operand), node.field, node.span)
        if isinstance(node, Has):
            operand = self.infer(node.operand)
            if not (operand.is_dyn or operand.name == "map"):
                self.error("has_operand", f"`has` needs a map, but this is {operand}.", node.span)
            return BOOL
        if isinstance(node, Index):
            return self._index(node)
        if isinstance(node, Call):
            return self._call(node)
        if isinstance(node, Comprehension):
            return self._comprehension(node)
        if isinstance(node, ListExpr):
            items = [self.infer(item) for item in node.items]
            item = items[0] if items else DYN
            for other in items[1:]:
                item = unify(item, other)
            return list_of(item)
        if isinstance(node, MapExpr):
            keys = [self.infer(key) for key, _ in node.entries]
            values = [self.infer(value) for _, value in node.entries]
            return map_of(_common(keys), _common(values))
        if isinstance(node, Unary):
            return self._unary(node)
        if isinstance(node, Binary):
            return self._binary(node)
        if isinstance(node, Conditional):
            condition = self.infer(node.condition)
            if not condition.fits(BOOL):
                self.error("condition_type", f"The condition before `?` is {condition}, not bool.", node.condition.span)
            return unify(self.infer(node.then), self.infer(node.otherwise))
        return DYN

    def _ident(self, node: Ident) -> CelType:
        for scope in reversed(self.scopes):
            if node.name in scope:
                return scope[node.name]
        variable = CONTEXTS[self.context].variable(node.name)
        if variable is not None:
            return variable.type
        known = ", ".join(f"`{variable.name}`" for variable in CONTEXTS[self.context].variables)
        return self.error("unknown_variable", f"`{node.name}` isn't defined here. Available: {known}.", node.span)

    def _select(self, operand: CelType, name: str, span: Span) -> CelType:
        if operand.is_dyn:
            return DYN
        if operand.name == "map":
            if not operand.key.fits(STRING):
                return self.error("select_key", f"`.{name}` needs string keys, but the keys are {operand.key}.", span)
            return operand.element
        return self.error("select_operand", f"{operand} has no fields, so `.{name}` doesn't apply.", span)

    def _index(self, node: Index) -> CelType:
        operand = self.infer(node.operand)
        index = self.infer(node.index)
        if operand.is_dyn:
            return DYN
        if operand.name == "list":
            if not index.fits(INT) and not index.fits(UINT):
                self.error("index_type", f"A list is indexed by int, not {index}.", node.index.span)
            return operand.element
        if operand.name == "map":
            if not index.fits(operand.key):
                self.error("index_type", f"This map's keys are {operand.key}, not {index}.", node.index.span)
            return operand.element
        return self.error("index_operand", f"{operand} can't be indexed.", node.span)

    def _call(self, node: Call) -> CelType:
        function = FUNCTIONS.get(node.function)
        receiver = self.infer(node.target) if node.target is not None else None
        args = [self.infer(arg) for arg in node.args]
        if function is None:
            return self.error("unknown_function", f"`{node.function}` isn't a function CEL knows here.", node.span)
        for overload in function.overloads:
            if (overload.receiver is None) != (receiver is None) or len(overload.params) != len(args):
                continue
            if receiver is not None and overload.receiver is not None and not receiver.fits(overload.receiver):
                continue
            if all(arg.fits(param) for arg, param in zip(args, overload.params, strict=True)):
                return overload.result
        on = f" on {receiver}" if receiver is not None else ""
        given = ", ".join(str(arg) for arg in args) or "no arguments"
        return self.error(
            "no_overload",
            f"`{node.function}` doesn't apply{on} with ({given}). Use {function.signature}.",
            node.span,
        )

    def _comprehension(self, node: Comprehension) -> CelType:
        range_type = self.infer(node.range)
        if range_type.is_dyn:
            item = DYN
        elif range_type.name == "list":
            item = range_type.element
        elif range_type.name == "map":
            item = range_type.key
        else:
            self.error("macro_range", f"`{node.kind}` works on a list or a map, not {range_type}.", node.range.span)
            item = DYN
        self.scopes.append({node.var: item})
        try:
            if node.predicate is not None:
                predicate = self.infer(node.predicate)
                if not predicate.fits(BOOL):
                    self.error("macro_predicate", f"The predicate is {predicate}, not bool.", node.predicate.span)
            if node.kind == "map":
                assert node.transform is not None
                return list_of(self.infer(node.transform))
        finally:
            self.scopes.pop()
        if node.kind == "filter":
            return list_of(item)
        return BOOL

    def _unary(self, node: Unary) -> CelType:
        operand = self.infer(node.operand)
        if node.op == "!":
            if not operand.fits(BOOL):
                self.error("no_overload", f"`!` needs bool, not {operand}.", node.span)
            return BOOL
        if not operand.is_dyn and operand not in (INT, DOUBLE):
            return self.error("no_overload", f"`-` needs int or double, not {operand}.", node.span)
        return operand

    def _binary(self, node: Binary) -> CelType:  # noqa: C901, PLR0911, PLR0912
        left = self.infer(node.left)
        right = self.infer(node.right)
        op = node.op
        if op in {"&&", "||"}:
            for side, inferred in ((node.left, left), (node.right, right)):
                if not inferred.fits(BOOL):
                    self.error("no_overload", f"`{op}` needs bool on both sides; this side is {inferred}.", side.span)
            return BOOL
        if op in {"==", "!="}:
            return BOOL
        if op == "in":
            if right.is_dyn:
                return BOOL
            if (right.name == "list" and left.fits(right.element)) or (right.name == "map" and left.fits(right.key)):
                return BOOL
            return self.error("no_overload", f"`{left} in {right}` doesn't apply.", node.span)
        if op in {"<", "<=", ">", ">="}:
            if left.is_dyn or right.is_dyn or (left == right and left in (*NUMERIC, STRING, BYTES, BOOL)):
                return BOOL
            if left in NUMERIC and right in NUMERIC:
                return BOOL
            return self.error("no_overload", f"`{op}` can't compare {left} with {right}.", node.span)
        if left.is_dyn or right.is_dyn:
            return DYN if left.is_dyn and right.is_dyn else (right if left.is_dyn else left)
        if op == "+" and left == right and (left in (*NUMERIC, STRING, BYTES) or left.name == "list"):
            return left
        if op in {"-", "*", "/"} and left == right and left in NUMERIC:
            return left
        if op == "%" and left == right and left in (INT, UINT):
            return left
        hint = (
            " CEL doesn't mix int and double; convert with double(…) or int(…)."
            if {left, right} <= set(NUMERIC)
            else ""
        )
        return self.error("no_overload", f"`{op}` doesn't apply to {left} and {right}.{hint}", node.span)


def _common(types: list[CelType]) -> CelType:
    if not types:
        return DYN
    common = types[0]
    for other in types[1:]:
        common = unify(common, other)
    return common
