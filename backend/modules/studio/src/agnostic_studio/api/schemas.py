"""Request and response bodies of the studio endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_evals.facade import GateCheck
from agnostic_spec import Diagnostic
from agnostic_studio.application.codegen import CodeView, marks_dict, spans_dict
from agnostic_studio.application.components import ComponentDetail, IndexRow, VersionView
from agnostic_studio.application.drafts import Diff, revision
from agnostic_studio.application.publishing import PublishCheck, PublishResult
from agnostic_studio.application.validation import ValidationReport
from agnostic_studio.domain.diff import FieldChange
from agnostic_studio.domain.promotion import Promotion
from agnostic_studio.domain.registry import RegistryEntry, tool_entry
from agnostic_studio.domain.templates import Template
from agnostic_studio.domain.usage import UsedBy

type KindIn = Literal["agent", "team"]
type KindQuery = Literal["agent", "team", "workflow"]


# ---------------------------------------------------------------- registry


class DetailOut(BaseModel):
    key: str
    value: str


class AvailabilityOut(BaseModel):
    kind: Literal["available", "unavailable", "registered"]
    title: str
    text: str


class FunctionOut(BaseModel):
    name: str
    description: str | None
    parameters: dict[str, Any] | None
    signature: str | None
    requires_confirmation: bool


class SourceOut(BaseModel):
    module: str | None
    file: str | None
    line: int | None


class UsedByOut(BaseModel):
    component_id: str
    component_kind: str
    component_name: str
    versions: list[str]
    versions_text: str

    @classmethod
    def of(cls, item: UsedBy) -> UsedByOut:
        return cls(
            component_id=item.component_id,
            component_kind=item.component_kind,
            component_name=item.component_name,
            versions=list(item.versions),
            versions_text=item.versions_text,
        )


class RegistryEntryOut(BaseModel):
    type: str
    name: str
    id: str | None
    description: str | None
    blurb: str
    meta: str
    status: Literal["registered", "discovered"]
    details: list[DetailOut]
    code: str | None
    code_label: str | None
    requires_approval: bool
    approval_type: str | None
    studio_available: bool
    availability: AvailabilityOut
    functions: list[FunctionOut]
    source: SourceOut | None
    used_by_count: int
    config_value: Any = Field(
        description="What a config stores when a builder picks this entry (a model ref, tool dicts, a knowledge ref…)."
    )

    @classmethod
    def of(cls, entry: RegistryEntry, used_by: list[UsedBy]) -> RegistryEntryOut:
        return cls(
            type=entry.type,
            name=entry.name,
            id=entry.id,
            description=entry.description,
            blurb=entry.blurb,
            meta=entry.meta,
            status=entry.status,
            details=[DetailOut(key=key, value=value) for key, value in entry.details],
            code=entry.code,
            code_label=entry.code_label,
            requires_approval=entry.requires_approval,
            approval_type=entry.approval_type,
            studio_available=entry.studio_available,
            availability=AvailabilityOut(
                kind=entry.availability.kind, title=entry.availability.title, text=entry.availability.text
            ),
            functions=[
                FunctionOut(
                    name=item.name,
                    description=item.description,
                    parameters=item.parameters,
                    signature=item.signature,
                    requires_confirmation=item.requires_confirmation,
                )
                for item in entry.functions
            ],
            source=SourceOut(module=entry.source.module, file=entry.source.file, line=entry.source.line)
            if entry.source is not None and (entry.source.module or entry.source.file)
            else None,
            used_by_count=len(used_by),
            config_value=config_value(entry),
        )


def config_value(entry: RegistryEntry) -> Any:  # noqa: ANN401, PLR0911
    match entry.type:
        case "tool":
            return tool_entry(entry)
        case "model":
            model_id = str(entry.metadata.get("model_id") or entry.name)
            provider = entry.metadata.get("provider")
            return {"id": model_id, "provider": provider} if provider else {"id": model_id}
        case "knowledge" | "learning":
            return {"name": entry.name}
        case "schema":
            return entry.name
        case "memory_manager":
            return {"registry_id": entry.id or entry.name}
        case "agent":
            return {"type": "agent", "agent_id": entry.id or entry.name}
        case "team":
            return {"type": "team", "team_id": entry.id or entry.name}
        case _:
            return None


class RegistryOut(BaseModel):
    instance: str
    entries: list[RegistryEntryOut]
    counts: dict[str, int]
    total: int
    bridge: bool


class RegistryEntryDetailOut(BaseModel):
    entry: RegistryEntryOut
    used_by: list[UsedByOut]


# ---------------------------------------------------------------- components & versions


class StudioComponentOut(BaseModel):
    id: str
    kind: KindQuery
    name: str
    description: str | None
    current_version: int | None
    source: Literal["studio", "code"]
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None


class ComponentRowOut(BaseModel):
    component: StudioComponentOut
    editable: bool
    latest_version: int | None
    draft_version: int | None
    draft_updated_at: datetime | None
    owner_group_id: str | None
    labels: list[str]
    runs_7d: int | None = Field(default=None, description="Runs in the last 7 days, when the instance reports them.")

    @classmethod
    def of(cls, row: IndexRow) -> ComponentRowOut:
        return cls(
            component=studio_component_out(row.component),
            editable=row.editable,
            latest_version=row.latest_version,
            draft_version=row.draft.version if row.draft else None,
            draft_updated_at=(row.draft.updated_at or row.draft.created_at) if row.draft else None,
            owner_group_id=row.meta.owner_group_id if row.meta else None,
            labels=list(row.meta.labels) if row.meta else [],
        )


def studio_component_out(component: Any) -> StudioComponentOut:  # noqa: ANN401
    return StudioComponentOut(
        id=component.id,
        kind=component.kind,
        name=component.name,
        description=component.description,
        current_version=component.current_version,
        source=component.source,
        created_at=component.created_at,
        updated_at=component.updated_at,
        deleted_at=component.deleted_at,
    )


class VersionOut(BaseModel):
    version: int
    stage: Literal["draft", "published"]
    tag: str
    current: bool
    label: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime | None
    revision: str
    author_name: str | None
    updated_by_name: str | None
    saved_at: datetime | None
    published_by_name: str | None
    published_at: datetime | None
    eval_status: str | None
    change_summary: str | None
    based_on_version: int | None
    promoted_from: dict[str, Any] | None
    links: list[dict[str, Any]]
    config: dict[str, Any] | None

    @classmethod
    def of(cls, view: VersionView, *, with_config: bool = True) -> VersionOut:
        version, meta = view.version, view.meta
        return cls(
            version=version.version,
            stage=version.stage,
            tag=f"v{version.version} draft" if version.stage == "draft" else f"v{version.version}",
            current=view.current,
            label=version.label,
            notes=version.notes or (meta.notes if meta else None),
            created_at=version.created_at,
            updated_at=version.updated_at,
            revision=revision(version, meta),
            author_name=meta.author_name if meta else None,
            updated_by_name=meta.updated_by_name if meta else None,
            saved_at=meta.updated_at if meta else None,
            published_by_name=meta.published_by_name if meta else None,
            published_at=meta.published_at if meta else None,
            eval_status=meta.eval_status if meta else None,
            change_summary=meta.change_summary if meta else None,
            based_on_version=meta.based_on_version if meta else None,
            promoted_from=meta.promoted_from if meta else None,
            links=version.links,
            config=version.config if with_config else None,
        )


class ComponentDetailOut(BaseModel):
    component: StudioComponentOut
    editable: bool
    versions: list[VersionOut]
    draft: VersionOut | None
    current: VersionOut | None
    owner_group_id: str | None
    labels: list[str]

    @classmethod
    def of(cls, detail: ComponentDetail) -> ComponentDetailOut:
        draft, current = detail.draft, detail.current
        return cls(
            component=studio_component_out(detail.component),
            editable=detail.editable,
            versions=[VersionOut.of(view, with_config=False) for view in detail.versions],
            draft=VersionOut.of(draft) if draft else None,
            current=VersionOut.of(current) if current else None,
            owner_group_id=detail.meta.owner_group_id if detail.meta else None,
            labels=list(detail.meta.labels) if detail.meta else [],
        )


class CreateIn(BaseModel):
    kind: KindIn
    name: str = Field(min_length=1, max_length=200)
    mode: Literal["blank", "template", "duplicate", "import"] = "blank"
    component_id: str | None = Field(default=None, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str | None = Field(default=None, max_length=2000)
    template_id: str | None = None
    source_id: str | None = None
    source_version: int | None = Field(default=None, ge=1)
    config: dict[str, Any] | None = None
    model: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class MetaPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    owner_group_id: str | None = None
    clear_owner: bool = False
    labels: list[str] | None = Field(default=None, max_length=20)


class SaveDraftIn(BaseModel):
    config: dict[str, Any]
    revision: str | None = Field(default=None, description="The revision the editor loaded; a mismatch is a 409.")
    pins: dict[str, int] | None = Field(default=None, description="Team members pinned at a version, by component id.")
    notes: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(default=None, max_length=100)


class NewDraftIn(BaseModel):
    from_version: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=2000)


class TemplateOut(BaseModel):
    id: str
    kind: KindIn
    label: str
    description: str
    config: dict[str, Any]

    @classmethod
    def of(cls, template: Template) -> TemplateOut:
        return cls(
            id=template.id,
            kind=template.kind,
            label=template.label,
            description=template.description,
            config=dict(template.config),
        )


# ---------------------------------------------------------------- validation, code, diffs


class DiagnosticOut(BaseModel):
    path: str
    severity: Literal["error", "warning", "info"]
    code: str
    message: str

    @classmethod
    def of(cls, item: Diagnostic) -> DiagnosticOut:
        return cls(path=item.path, severity=item.severity, code=item.code, message=item.message)


class LayerOut(BaseModel):
    id: str
    label: str
    status: Literal["ok", "failed", "warning", "skipped"]
    hint: str | None
    diagnostics: list[DiagnosticOut]


class ValidationOut(BaseModel):
    ok: bool
    summary: str
    layers: list[LayerOut]

    @classmethod
    def of(cls, report: ValidationReport) -> ValidationOut:
        return cls(
            ok=report.ok,
            summary=report.summary,
            layers=[
                LayerOut(
                    id=layer.id,
                    label=layer.label,
                    status=layer.status,
                    hint=layer.hint,
                    diagnostics=[DiagnosticOut.of(item) for item in layer.diagnostics],
                )
                for layer in report.layers
            ],
        )


class ValidateIn(BaseModel):
    kind: KindIn
    config: dict[str, Any]


class CodegenIn(BaseModel):
    kind: KindIn
    config: dict[str, Any]
    base_config: dict[str, Any] | None = Field(default=None, description="Mark the lines that differ from this config.")


class SpanOut(BaseModel):
    line: int
    col_start: int
    col_end: int
    end_line: int


class CodeNoteOut(BaseModel):
    path: str
    kind: str
    line: int
    col_start: int
    col_end: int
    message: str
    entry: str | None


class LintMessageOut(BaseModel):
    code: str
    message: str
    line: int
    column: int


class RuffOut(BaseModel):
    available: bool
    status: str
    formatted: bool
    messages: list[LintMessageOut]


class CodegenOut(BaseModel):
    code: str
    filename: str
    spans: dict[str, SpanOut]
    marks: dict[str, Literal["added", "modified"]]
    notes: list[CodeNoteOut]
    ruff: RuffOut
    base_code: str | None

    @classmethod
    def of(cls, view: CodeView) -> CodegenOut:
        rendered = view.rendered
        return cls(
            code=rendered.code,
            filename=rendered.filename,
            spans={path: SpanOut(**span) for path, span in spans_dict(view).items()},
            marks={line: mark for line, mark in marks_dict(view).items() if mark in {"added", "modified"}},  # pyright: ignore[reportArgumentType]
            notes=[
                CodeNoteOut(
                    path=note.path,
                    kind=note.kind,
                    line=note.line,
                    col_start=note.col_start,
                    col_end=note.col_end,
                    message=note.message,
                    entry=note.entry,
                )
                for note in view.notes
            ],
            ruff=RuffOut(
                available=rendered.ruff.available,
                status=rendered.ruff.status,
                formatted=rendered.ruff.formatted,
                messages=[
                    LintMessageOut(code=item.code, message=item.message, line=item.line, column=item.column)
                    for item in rendered.ruff.messages
                ],
            ),
            base_code=rendered.base_code,
        )


class FieldChangeOut(BaseModel):
    path: str
    field: str
    op: Literal["added", "removed", "changed"]
    before: Any = None
    after: Any = None

    @classmethod
    def of(cls, change: FieldChange) -> FieldChangeOut:
        return cls(path=change.path, field=change.field, op=change.op, before=change.before, after=change.after)


class DiffCountsOut(BaseModel):
    added: int
    changed: int
    removed: int


class DiffOut(BaseModel):
    component_id: str
    from_version: int
    to_version: int
    changes: list[FieldChangeOut]
    counts: DiffCountsOut
    summary: str
    code_before: str
    code_after: str
    unified: str
    lines_added: int
    lines_removed: int

    @classmethod
    def of(cls, item: Diff) -> DiffOut:
        return cls(
            component_id=item.component.id,
            from_version=item.from_version,
            to_version=item.to_version,
            changes=[FieldChangeOut.of(change) for change in item.changes],
            counts=DiffCountsOut(added=item.counts.added, changed=item.counts.changed, removed=item.counts.removed),
            summary=item.summary,
            code_before=item.code_before,
            code_after=item.code_after,
            unified=item.unified,
            lines_added=item.lines_added,
            lines_removed=item.lines_removed,
        )


# ---------------------------------------------------------------- publish


class GateCheckOut(BaseModel):
    gate_id: str
    dataset_id: str
    dataset_name: str | None
    eval_type: str
    min_average: float
    value: float | None
    batch_id: str | None
    state: Literal["off", "no_result", "would_block", "passes"]
    consequence: str
    blocks: bool

    @classmethod
    def of(cls, gate: GateCheck) -> GateCheckOut:
        return cls(
            gate_id=gate.gate_id,
            dataset_id=gate.dataset_id,
            dataset_name=gate.dataset_name,
            eval_type=gate.eval_type,
            min_average=gate.min_average,
            value=gate.value,
            batch_id=gate.batch_id,
            state=gate.state,
            consequence=gate.consequence,
            blocks=gate.blocks,
        )


class PublishCheckOut(BaseModel):
    version: int
    stage: Literal["draft", "published"]
    validation: ValidationOut
    gates: list[GateCheckOut]
    blocked_by_gates: bool
    can_publish: bool
    can_override: bool
    outcome: str
    summary: str
    changes: list[FieldChangeOut]

    @classmethod
    def of(cls, check: PublishCheck) -> PublishCheckOut:
        return cls(
            version=check.version.version,
            stage=check.version.stage,
            validation=ValidationOut.of(check.validation),
            gates=[GateCheckOut.of(gate) for gate in check.gates],
            blocked_by_gates=check.blocked_by_gates,
            can_publish=check.can_publish,
            can_override=check.can_override,
            outcome=check.outcome,
            summary=check.summary,
            changes=[FieldChangeOut.of(change) for change in check.changes],
        )


class PublishIn(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)
    override_reason: str | None = Field(
        default=None, max_length=1000, description="Publish past failed eval gates (needs evals:gates:override)."
    )


class PublishOut(BaseModel):
    version: VersionOut
    outcome: str
    overridden: bool
    gates: list[GateCheckOut]

    @classmethod
    def of(cls, result: PublishResult) -> PublishOut:
        return cls(
            version=VersionOut.of(result.version),
            outcome=result.outcome,
            overridden=result.overridden,
            gates=[GateCheckOut.of(gate) for gate in result.gates],
        )


class SetCurrentIn(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class SetCurrentOut(BaseModel):
    version: VersionOut
    outcome: str


# ---------------------------------------------------------------- promotion & test runs


class PromoteIn(BaseModel):
    target: str = Field(description="Instance id or slug to promote to.")
    version: int | None = Field(default=None, ge=1, description="Defaults to the current version.")
    include_children: bool = True


class PromotionApplyIn(BaseModel):
    publish: bool = False


class PromotionOut(BaseModel):
    id: str
    from_instance: str
    to_instance: str
    component_id: str
    component_kind: str
    from_version: int
    to_version: int | None
    include_children: bool
    status: Literal["dry_run", "blocked", "applied", "published", "failed"]
    report: dict[str, Any]
    created_by_name: str
    created_at: datetime
    applied_at: datetime | None

    @classmethod
    def of(cls, promotion: Promotion) -> PromotionOut:
        return cls(
            id=promotion.id,
            from_instance=promotion.from_instance,
            to_instance=promotion.to_instance,
            component_id=promotion.component_id,
            component_kind=promotion.component_kind,
            from_version=promotion.from_version,
            to_version=promotion.to_version,
            include_children=promotion.include_children,
            status=promotion.status,
            report=dict(promotion.report),
            created_by_name=promotion.created_by_name,
            created_at=promotion.created_at,
            applied_at=promotion.applied_at,
        )


class TestRunIn(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    version: int = Field(ge=1)
    session_id: str | None = None
