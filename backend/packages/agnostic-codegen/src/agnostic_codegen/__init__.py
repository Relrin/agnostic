"""Python source for Agno component configs, and configs from Python.

Generation, ruff formatting, span maps, line marks, parsing human-written code into configs, and edits that keep the
human's formatting.

Code is a projection of the config document, or (for code-backed components) the artifact itself; nothing here
imports or runs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agnostic_codegen.convention import RegistryConvention, snake
from agnostic_codegen.formatting import LintMessage, RuffResult, format_and_lint, lint
from agnostic_codegen.generate import Generated, Note
from agnostic_codegen.generate import generate as generate_component
from agnostic_codegen.marks import Mark, counts, line_marks, unified
from agnostic_codegen.parse import (
    CODE_ONLY,
    CodeDiagnostic,
    Lookup,
    Parsed,
    Reading,
    Resolver,
    owned_paths,
    parse_source,
    read_source,
)
from agnostic_codegen.spans import Span, span_map
from agnostic_codegen.transform import Transformed, transform
from agnostic_codegen.workflow import generate_workflow
from agnostic_spec.v3_1 import ComponentConfig, WorkflowConfig

FOLDERS = {"agent": "agents", "team": "teams", "workflow": "workflows"}


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
    return f"{FOLDERS[config.kind]}/{variable}.py"


def generate(config: ComponentConfig, convention: RegistryConvention | None = None) -> Generated:
    if isinstance(config, WorkflowConfig):
        return generate_workflow(config, convention)
    return generate_component(config, convention)


def spans_of(
    code: str, config: ComponentConfig, generated: Generated, convention: RegistryConvention
) -> dict[str, Span]:
    """Field paths → spans of the final code. Workflows are read back, so hoisted steps point at their definition."""
    if isinstance(config, WorkflowConfig):
        return parse_source(code, kind="workflow", convention=convention).spans
    return span_map(code, generated.variable, generated.element_paths)


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
        spans=spans_of(ruff.code, config, generated, convention),
        notes=generated.notes,
        ruff=ruff,
        marks=marks,
        base_code=base_code,
    )


__all__ = [
    "CODE_ONLY",
    "CodeDiagnostic",
    "Generated",
    "LintMessage",
    "Lookup",
    "Mark",
    "Note",
    "Parsed",
    "Reading",
    "RegistryConvention",
    "Rendered",
    "Resolver",
    "RuffResult",
    "Span",
    "Transformed",
    "counts",
    "filename_for",
    "format_and_lint",
    "generate",
    "line_marks",
    "lint",
    "owned_paths",
    "parse_source",
    "read_source",
    "render",
    "snake",
    "span_map",
    "spans_of",
    "transform",
    "unified",
]
