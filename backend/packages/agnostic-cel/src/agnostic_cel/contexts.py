"""What an expression can see, per place in a workflow. Mirrors how agno builds the activation it evaluates with."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from agnostic_cel.cel_types import BOOL, DYN, INT, STRING, CelType, list_of, map_of
from agnostic_cel.functions import FUNCTIONS, MACROS

ContextName = Literal["condition", "router", "loop"]


@dataclass(frozen=True, slots=True)
class Variable:
    name: str
    type: CelType
    doc: str
    example: object


@dataclass(frozen=True, slots=True)
class Context:
    name: ContextName
    label: str
    result: CelType
    variables: tuple[Variable, ...]

    def variable(self, name: str) -> Variable | None:
        return next((variable for variable in self.variables if variable.name == name), None)


_STEP_INPUT = (
    Variable("input", STRING, "The workflow's input as text.", "I was charged twice, need a refund"),
    Variable(
        "previous_step_content",
        STRING,
        "What the previous step returned, as text (JSON for structured output).",
        "Category: BILLING",
    ),
    Variable(
        "previous_step_outputs",
        map_of(STRING, STRING),
        "Every earlier step's output by step name.",
        {"Classify ticket": "Category: BILLING"},
    ),
    Variable("additional_data", map_of(STRING, DYN), "Extra data passed with the run.", {}),
    Variable("session_state", map_of(STRING, DYN), "The session's state.", {}),
)

CONTEXTS: Mapping[ContextName, Context] = {
    "condition": Context("condition", "Condition evaluator", BOOL, _STEP_INPUT),
    "router": Context(
        "router",
        "Router selector",
        STRING,
        (
            *_STEP_INPUT,
            Variable("step_choices", list_of(STRING), "The names of the router's choices.", []),
        ),
    ),
    "loop": Context(
        "loop",
        "Loop end condition",
        BOOL,
        (
            Variable("current_iteration", INT, "The iteration that just finished, from 1.", 1),
            Variable("max_iterations", INT, "The loop's iteration limit.", 3),
            Variable("all_success", BOOL, "Whether every step of this iteration succeeded.", example=True),
            Variable("last_step_content", STRING, "What the iteration's last step returned, as text.", "APPROVED"),
            Variable(
                "step_outputs",
                map_of(STRING, STRING),
                "This iteration's outputs by step name.",
                {"Draft reply": "Hi! ...", "Review tone": "APPROVED"},
            ),
        ),
    ),
}


def activation(context: ContextName, sample: Mapping[str, Any], *, choices: list[str] | None = None) -> dict[str, Any]:
    """The variables agno would pass, from a sample a person typed.

    Text where agno passes text, ``{}`` and ``""`` where nothing was given, and the router's real choice names.
    """
    values: dict[str, Any] = {}
    for variable in CONTEXTS[context].variables:
        given = sample.get(variable.name)
        if variable.name == "step_choices":
            values[variable.name] = list(choices if choices is not None else given or [])
        elif variable.type == STRING:
            values[variable.name] = _text(given)
        elif variable.type.name == "map":
            mapping: dict[str, Any] = dict(given) if isinstance(given, Mapping) else {}  # pyright: ignore[reportUnknownArgumentType]
            if variable.type.element == STRING:
                mapping = {str(key): _text(item) for key, item in mapping.items()}
            values[variable.name] = mapping
        elif variable.type == BOOL:
            values[variable.name] = bool(given) if given is not None else bool(variable.example)
        elif variable.type == INT:
            values[variable.name] = int(given) if isinstance(given, int | float | str) and str(given) else 0
        else:
            values[variable.name] = given
    if context == "loop" and "max_iterations" not in sample:
        values["max_iterations"] = 3
    return values


def describe() -> dict[str, Any]:
    """Everything the expression editor needs for completion and hover docs."""
    return {
        "contexts": {
            name: {
                "label": context.label,
                "result": str(context.result),
                "variables": [
                    {
                        "name": variable.name,
                        "type": str(variable.type),
                        "doc": variable.doc,
                        "example": variable.example,
                    }
                    for variable in context.variables
                ],
            }
            for name, context in CONTEXTS.items()
        },
        "functions": [
            {"name": function.name, "signature": function.signature, "doc": function.doc, "method": function.is_method}
            for function in FUNCTIONS.values()
        ],
        "macros": [{"name": name, "doc": doc} for name, doc in MACROS.items()],
    }


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, default=str)
    return str(value)
