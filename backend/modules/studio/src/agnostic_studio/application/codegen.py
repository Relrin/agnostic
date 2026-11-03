"""The generated-code view of a config: Python, span map, gutter marks against a base version, notes and ruff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from pydantic import ValidationError

from agnostic_codegen import Rendered, render
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import ValidationFailedError
from agnostic_spec.v3_1 import Kind as SpecKind
from agnostic_spec.v3_1 import parse, shape_errors
from agnostic_studio.application.access import READ_SCOPE, StudioAccess


@dataclass(frozen=True, slots=True)
class CodeNote:
    path: str
    kind: str
    line: int
    col_start: int
    col_end: int
    message: str
    entry: str | None = None
    """The registry entry the note is about (a tool name)."""


@dataclass(frozen=True, slots=True)
class CodeView:
    rendered: Rendered
    notes: list[CodeNote]


class Codegen:
    def __init__(self, access: StudioAccess) -> None:
        self._access = access

    async def render(
        self,
        principal: Principal,
        ref: str,
        kind: SpecKind,
        config: dict[str, Any],
        base: dict[str, Any] | None = None,
    ) -> CodeView:
        await self._access.instance(principal, ref, READ_SCOPE)
        try:
            parsed = parse(kind, config)
            parsed_base = parse(kind, base) if base is not None else None
        except ValidationError as exc:
            raise ValidationFailedError(
                "The config doesn't have the shape AgentOS stores, so there is no code for it.",
                extra={"diagnostics": [item.as_dict() for item in shape_errors(kind, config)]},
            ) from exc
        rendered = await render(parsed, base=parsed_base)
        notes: list[CodeNote] = []
        for note in rendered.notes:
            span = rendered.spans.get(note.path)
            if span is None:
                continue
            if note.kind == "approval":
                notes.append(
                    CodeNote(
                        path=note.path,
                        kind="approval",
                        line=span.line,
                        col_start=span.col_start,
                        col_end=span.col_end,
                        message=f"`{note.message}` requires approval. Runs pause in Approvals until someone holding "
                        "`approvals:write` resolves them.",
                        entry=note.message,
                    )
                )
            else:
                notes.append(CodeNote(note.path, note.kind, span.line, span.col_start, span.col_end, note.message))
        return CodeView(rendered, notes)


def spans_dict(view: CodeView) -> dict[str, dict[str, int]]:
    return {path: span.as_dict() for path, span in view.rendered.spans.items()}


def marks_dict(view: CodeView) -> dict[str, str]:
    return {str(line): cast("str", mark) for line, mark in view.rendered.marks.items()}
