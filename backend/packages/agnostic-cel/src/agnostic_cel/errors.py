"""What can go wrong with an expression, located by character offsets into its source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    """Exclusive, like a slice."""

    def as_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


class CelError(Exception):
    def __init__(self, message: str, span: Span | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.span = span


class CelSyntaxError(CelError):
    """The source isn't a CEL expression (or uses something outside the subset agno workflows need)."""


class CelEvalError(CelError):
    """Evaluation failed: no such key, no matching overload, division by zero, a budget ran out."""
