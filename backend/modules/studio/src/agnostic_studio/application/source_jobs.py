"""The CPU-bound work behind the code pane and the expression editor, as plain functions a worker process can run.

Each takes and returns plain data (strings, dicts, dataclasses), so it can cross into a worker process and back.
None of them imports or executes the code it reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agnostic_cel import CelError, CheckResult, ContextName, activation, check, evaluate, type_name
from agnostic_codegen import Lookup, Parsed, RegistryConvention, Transformed, parse_source, transform
from agnostic_spec.v3_1 import Kind


@dataclass(frozen=True, slots=True)
class Evaluation:
    result: Any
    type: str | None
    error: str | None = None
    start: int | None = None
    end: int | None = None
    """Where in the expression evaluation failed, when that is known."""


def parse_job(
    code: str, kind: Kind | None, component_id: str | None, convention: RegistryConvention, lookup: Lookup
) -> Parsed:
    return parse_source(code, kind=kind, component_id=component_id, convention=convention, resolver=lookup)


def transform_job(
    code: str,
    after: dict[str, Any],
    kind: Kind,
    component_id: str | None,
    convention: RegistryConvention,
    lookup: Lookup,
) -> Transformed:
    return transform(code, after, kind=kind, component_id=component_id, convention=convention, resolver=lookup)


def check_job(expression: str, context: ContextName, choices: list[str] | None) -> CheckResult:
    return check(expression, context, choices=choices)


def evaluate_job(
    expression: str, context: ContextName, sample: dict[str, Any], choices: list[str] | None
) -> Evaluation:
    try:
        value = evaluate(expression, activation(context, sample, choices=choices))
    except CelError as exc:
        span = exc.span
        return Evaluation(None, None, exc.message, span.start if span else None, span.end if span else None)
    return Evaluation(value, type_name(value))
