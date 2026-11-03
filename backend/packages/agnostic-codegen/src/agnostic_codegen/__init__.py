"""Python source for Agno component configs: generation, ruff formatting, span maps and line marks.

Code is a projection of the config document; generating it never imports or runs anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agnostic_codegen.convention import RegistryConvention, snake
from agnostic_codegen.formatting import LintMessage, RuffResult, format_and_lint
from agnostic_codegen.generate import Generated, Note, generate
from agnostic_codegen.marks import Mark, counts, line_marks, unified
from agnostic_codegen.spans import Span, span_map
from agnostic_spec.v3_1 import ComponentConfig


@dataclass(frozen=True, slots=True)
class Rendered:
    code: str
    filename: str
    spans: dict[str, Span]
    notes: list[Note]
    ruff: RuffResult
    marks: dict[int, Mark] = field(default_factory=dict)
    base_code: str | None = None


def filename_for(config: ComponentConfig, variable: str) -> str:
    folder = "teams" if config.kind == "team" else "agents"
    return f"{folder}/{variable}.py"


async def render(
    config: ComponentConfig,
    *,
    convention: RegistryConvention | None = None,
    base: ComponentConfig | None = None,
) -> Rendered:
    """Generate, format and lint ``config``; with ``base``, also mark the lines that differ from it."""
    convention = convention or RegistryConvention()
    generated = generate(config, convention)
    filename = filename_for(config, generated.variable)
    ruff = await format_and_lint(generated.code, filename=filename, first_party=convention.first_party)
    base_code: str | None = None
    marks: dict[int, Mark] = {}
    if base is not None:
        base_generated = generate(base, convention)
        base_ruff = await format_and_lint(base_generated.code, filename=filename, first_party=convention.first_party)
        base_code = base_ruff.code
        marks = line_marks(base_code, ruff.code)
    return Rendered(
        code=ruff.code,
        filename=filename,
        spans=span_map(ruff.code, generated.variable, generated.element_paths),
        notes=generated.notes,
        ruff=ruff,
        marks=marks,
        base_code=base_code,
    )


__all__ = [
    "Generated",
    "LintMessage",
    "Mark",
    "Note",
    "RegistryConvention",
    "Rendered",
    "RuffResult",
    "Span",
    "counts",
    "filename_for",
    "format_and_lint",
    "generate",
    "line_marks",
    "render",
    "snake",
    "span_map",
    "unified",
]
