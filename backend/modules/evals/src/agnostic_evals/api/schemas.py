"""Request and response bodies of the evals endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_evals.application.access import BridgeSupport
from agnostic_evals.application.batches import BatchComparison, BatchDetail, EvaluationRow, Evaluations, summary_of
from agnostic_evals.application.datasets import DatasetDetail
from agnostic_evals.application.gates import GateView
from agnostic_evals.domain.compare import CaseChange
from agnostic_evals.domain.importing import CaseDraft, tool_calls
from agnostic_evals.domain.model import Batch, Case, Dataset, Item
from agnostic_evals.domain.scoring import Summary, headline

type EvalTypeIn = Literal["accuracy", "agent_as_judge", "reliability", "performance"]


class CaseIn(BaseModel):
    input: str = Field(min_length=1, max_length=20_000)
    expected_output: str | None = Field(default=None, max_length=20_000)
    criteria: str | None = Field(default=None, max_length=5_000)
    expected_tool_calls: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict[str, Any])

    def to_draft(self) -> CaseDraft:
        return CaseDraft(
            input=self.input.strip(),
            expected_output=(self.expected_output or "").strip() or None,
            criteria=(self.criteria or "").strip() or None,
            expected_tool_calls=tool_calls(self.expected_tool_calls),
            metadata=dict(self.metadata),
        )


class CasePatch(BaseModel):
    input: str | None = Field(default=None, min_length=1, max_length=20_000)
    expected_output: str | None = Field(default=None, max_length=20_000)
    criteria: str | None = Field(default=None, max_length=5_000)
    expected_tool_calls: list[str] | None = Field(default=None, max_length=50)


class CaseOut(BaseModel):
    id: str
    position: int
    input: str
    expected_output: str | None
    criteria: str | None
    expected_tool_calls: list[str] | None
    metadata: dict[str, Any]

    @classmethod
    def of(cls, case: Case) -> CaseOut:
        return cls(
            id=case.id,
            position=case.position,
            input=case.input,
            expected_output=case.expected_output,
            criteria=case.criteria,
            expected_tool_calls=list(case.expected_tool_calls) if case.expected_tool_calls else None,
            metadata=dict(case.metadata),
        )


class CasesIn(BaseModel):
    cases: list[CaseIn] = Field(min_length=1, max_length=1000)


class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    eval_type: EvalTypeIn
    tags: list[str] = Field(default_factory=list[str], max_length=20)
    cases: list[CaseIn] = Field(default_factory=list[CaseIn], max_length=1000)


class DatasetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str
    eval_type: EvalTypeIn
    tags: list[str]
    version: int
    case_count: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, dataset: Dataset) -> DatasetOut:
        return cls(
            id=dataset.id,
            name=dataset.name,
            description=dataset.description,
            eval_type=dataset.eval_type,
            tags=list(dataset.tags),
            version=dataset.version,
            case_count=dataset.case_count,
            created_by=dataset.created_by,
            created_at=dataset.created_at,
            updated_at=dataset.updated_at,
        )


class DatasetDetailOut(DatasetOut):
    cases: list[CaseOut]

    @classmethod
    def detail(cls, value: DatasetDetail) -> DatasetDetailOut:
        return cls(**DatasetOut.of(value.dataset).model_dump(), cases=[CaseOut.of(case) for case in value.cases])


class ImportIn(BaseModel):
    format: Literal["csv", "jsonl"]
    content: str = Field(min_length=1, max_length=5_000_000)
    replace: bool = Field(default=False, description="Replace every case instead of appending")


class ImportOut(BaseModel):
    imported: int


class JudgeIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=100)


class BatchIn(BaseModel):
    dataset_id: str
    component_kind: Literal["agent", "team"]
    component_id: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1, description="A pinned or draft version; empty = current")
    judge: JudgeIn | None = None
    name: str | None = Field(default=None, max_length=255)
    params: dict[str, Any] = Field(
        default_factory=dict[str, Any],
        description="num_iterations, warmup_runs, threshold, allow_additional_tool_calls",
    )


class SummaryOut(BaseModel):
    runs: int
    completed: int
    errors: int
    avg: float | None
    mean: float | None
    min: float | None
    max: float | None
    std_dev: float | None
    passed: int
    failed: int
    pass_ratio: float | None
    avg_latency_ms: float | None
    below_threshold: int
    gate_value: float | None

    @classmethod
    def of(cls, summary: Summary) -> SummaryOut:
        return cls(**summary.to_dict(), pass_ratio=summary.pass_ratio, gate_value=summary.gate_value)


class JudgeOut(BaseModel):
    model_id: str
    provider: str


class BatchOut(BaseModel):
    id: str
    instance_id: str
    name: str
    dataset_id: str
    dataset_name: str
    case_count: int
    eval_type: EvalTypeIn
    component_kind: Literal["agent", "team"]
    component_id: str
    version: int | None
    draft: bool
    version_label: str = Field(description="current, v3 or v4 draft")
    judge: JudgeOut | None
    via_bridge: bool
    params: dict[str, Any]
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: float
    started_by: str
    started_by_name: str
    started_at: datetime
    finished_at: datetime | None
    summary: SummaryOut | None
    result: str = Field(description="The table's result text: 9.10 avg, 8 / 10 pass, Failed 1 of 6, 3.2 s avg")
    error: str | None

    @classmethod
    def of(cls, batch: Batch) -> BatchOut:
        summary = summary_of(batch)
        return cls(
            id=batch.id,
            instance_id=batch.instance_id,
            name=batch.name,
            dataset_id=batch.dataset_id,
            dataset_name=batch.dataset_name,
            case_count=batch.case_count,
            eval_type=batch.eval_type,
            component_kind=batch.target.kind,
            component_id=batch.target.component_id,
            version=batch.target.version,
            draft=batch.target.draft,
            version_label=batch.target.label,
            judge=JudgeOut(model_id=batch.judge.model_id, provider=batch.judge.provider) if batch.judge else None,
            via_bridge=batch.via_bridge,
            params=dict(batch.params),
            status=batch.status,
            progress=batch.progress,
            started_by=batch.started_by,
            started_by_name=batch.started_by_name,
            started_at=batch.started_at,
            finished_at=batch.finished_at,
            summary=SummaryOut.of(summary) if summary else None,
            result=headline(batch.eval_type, summary) if summary else batch.status.capitalize(),
            error=batch.error,
        )


class ItemOut(BaseModel):
    id: str
    case_id: str
    position: int
    input: str
    expected: str | None
    status: Literal["pending", "running", "done", "error", "cancelled"]
    score: float | None
    passed: bool | None
    reason: str | None
    actual: str | None
    latency_ms: float | None
    eval_run_id: str | None
    trace_id: str | None
    error: str | None

    @classmethod
    def of(cls, item: Item) -> ItemOut:
        outcome = item.outcome
        return cls(
            id=item.id,
            case_id=item.case_id,
            position=item.position,
            input=item.input,
            expected=item.expected,
            status=item.status,
            score=outcome.score if outcome else None,
            passed=outcome.passed if outcome else None,
            reason=outcome.reason if outcome else None,
            actual=outcome.actual if outcome else None,
            latency_ms=outcome.latency_ms if outcome else None,
            eval_run_id=item.eval_run_id,
            trace_id=item.trace_id,
            error=item.error,
        )


class BatchDetailOut(BaseModel):
    batch: BatchOut
    items: list[ItemOut]
    baseline: BatchOut | None = Field(description="The default comparison: another version on the same dataset")

    @classmethod
    def of(cls, value: BatchDetail) -> BatchDetailOut:
        return cls(
            batch=BatchOut.of(value.batch),
            items=[ItemOut.of(item) for item in value.items],
            baseline=BatchOut.of(value.baseline) if value.baseline else None,
        )


class CaseChangeOut(BaseModel):
    case_id: str
    position: int
    input: str
    expected: str | None
    before: ItemOut | None
    after: ItemOut | None
    change: Literal["regression", "fix", "same", "missing"]

    @classmethod
    def of(cls, row: CaseChange) -> CaseChangeOut:
        return cls(
            case_id=row.case_id,
            position=row.position,
            input=row.input,
            expected=row.expected,
            before=ItemOut.of(row.before) if row.before else None,
            after=ItemOut.of(row.after) if row.after else None,
            change=row.change,
        )


class ComparisonCountsOut(BaseModel):
    regressions: int
    fixes: int
    below_before: int
    below_after: int


class BatchComparisonOut(BaseModel):
    before: BatchOut
    after: BatchOut
    rows: list[CaseChangeOut]
    counts: ComparisonCountsOut
    insight: str
    generated: bool = Field(default=False, description="Always false: the insight comes from fixed templates")

    @classmethod
    def of(cls, value: BatchComparison) -> BatchComparisonOut:
        return cls(
            before=BatchOut.of(value.before),
            after=BatchOut.of(value.after),
            rows=[CaseChangeOut.of(row) for row in value.rows],
            counts=ComparisonCountsOut(
                regressions=value.counts.regressions,
                fixes=value.counts.fixes,
                below_before=value.counts.below_before,
                below_after=value.counts.below_after,
            ),
            insight=value.insight,
        )


class EvaluationOut(BaseModel):
    source: Literal["batch", "agentos"] = Field(description="batch: run from a dataset here; agentos: any other run")
    id: str
    name: str
    eval_type: EvalTypeIn
    component_kind: str | None
    component_id: str | None
    version_label: str | None
    model: str | None
    judge: bool
    result: str
    bad: bool
    status: str
    progress: float
    created_at: datetime | None
    dataset_name: str | None
    case_count: int | None

    @classmethod
    def of(cls, row: EvaluationRow) -> EvaluationOut:
        return cls(
            source=row.source,
            id=row.id,
            name=row.name,
            eval_type=row.eval_type,
            component_kind=row.component_kind,
            component_id=row.component_id,
            version_label=row.version_label,
            model=row.model,
            judge=row.judge,
            result=row.result,
            bad=row.bad,
            status=row.status,
            progress=row.progress,
            created_at=row.created_at,
            dataset_name=row.dataset_name,
            case_count=row.case_count,
        )


class EvaluationsOut(BaseModel):
    data: list[EvaluationOut]
    standalone_unavailable: str | None = Field(description="Why AgentOS eval runs couldn't be listed")

    @classmethod
    def of(cls, value: Evaluations) -> EvaluationsOut:
        return cls(
            data=[EvaluationOut.of(row) for row in value.rows], standalone_unavailable=value.standalone_unavailable
        )


class EvalCapabilitiesOut(BaseModel):
    bridge_installed: bool
    versions: bool = Field(description="Drafts and pinned versions can be evaluated, and the judge can be chosen")
    reason: str | None

    @classmethod
    def of(cls, value: BridgeSupport) -> EvalCapabilitiesOut:
        return cls(bridge_installed=value.installed, versions=value.versions, reason=value.reason)


class GateIn(BaseModel):
    component_kind: Literal["agent", "team"]
    component_id: str = Field(min_length=1, max_length=200)
    dataset_id: str
    min_average: float = Field(ge=0, le=10)
    enabled: bool


class GateResultOut(BaseModel):
    batch_id: str
    version_label: str
    value: float | None


class GateOut(BaseModel):
    id: str
    component_kind: Literal["agent", "team"]
    component_id: str
    dataset_id: str
    dataset_name: str | None
    eval_type: EvalTypeIn
    min_average: float
    enabled: bool
    updated_by: str | None
    updated_at: datetime
    latest: GateResultOut | None
    state: Literal["off", "no_result", "would_block", "passes"]
    consequence: str

    @classmethod
    def of(cls, view: GateView) -> GateOut:
        gate = view.gate
        latest = view.latest
        return cls(
            id=gate.id,
            component_kind=gate.component_kind,
            component_id=gate.component_id,
            dataset_id=gate.dataset_id,
            dataset_name=view.dataset_name,
            eval_type=gate.eval_type,
            min_average=gate.min_average,
            enabled=gate.enabled,
            updated_by=gate.updated_by,
            updated_at=gate.updated_at,
            latest=GateResultOut(batch_id=latest.batch_id, version_label=latest.version_label, value=latest.value)
            if latest
            else None,
            state=view.consequence.state,
            consequence=view.consequence.text,
        )
