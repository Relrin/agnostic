"""CEL (Common Expression Language) as Agno workflows use it.

Condition evaluators, Router selectors and Loop end conditions get a parser, a type and exhaustiveness checker per
node context, and a small evaluator.

The instance's own evaluator (agno's, through the bridge) is the authority on what an expression returns; this
package is what the control plane can say without it. Nothing here imports or executes user code.
"""

from __future__ import annotations

from agnostic_cel.cel_types import CelType
from agnostic_cel.checker import CheckResult, Finding, check
from agnostic_cel.contexts import CONTEXTS, Context, ContextName, Variable, activation, describe
from agnostic_cel.errors import CelError, CelEvalError, CelSyntaxError, Span
from agnostic_cel.evaluate import Uint, evaluate, type_name
from agnostic_cel.nodes import Conditional, Node, ternary_chain
from agnostic_cel.parser import parse

__all__ = [
    "CONTEXTS",
    "CelError",
    "CelEvalError",
    "CelSyntaxError",
    "CelType",
    "CheckResult",
    "Conditional",
    "Context",
    "ContextName",
    "Finding",
    "Node",
    "Span",
    "Uint",
    "Variable",
    "activation",
    "check",
    "describe",
    "evaluate",
    "parse",
    "ternary_chain",
    "type_name",
]
