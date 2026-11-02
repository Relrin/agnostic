"""Eval batches: one AgentOS eval run per dataset case, compared case by case between component versions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_evals.application.access import READ_SCOPE, WRITE_SCOPE, BridgeSupport, EvalAccess, detail, page_items
from agnostic_evals.application.ports import BatchFilter, BatchRepository, DatasetRepository
from agnostic_evals.domain.compare import CaseChange, ComparisonCounts, compare_cases, counts, insight
from agnostic_evals.domain.model import (
    EVAL_TYPE_LABELS,
    LOW_SCORE,
    Batch,
    ComponentKind,
    EvalType,
    Item,
    Judge,
    Target,
)
from agnostic_evals.domain.scoring import Summary, headline, outcome
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.jobs import JobQueue

RUN_TASK = "evals.run_batch"
EVAL_TYPES: tuple[EvalType, ...] = ("accuracy", "agent_as_judge", "reliability", "performance")


class BridgeRequiredError(ConflictError):
    code = "bridge_required"
    title = "This needs agnostic-bridge on the instance"


@dataclass(frozen=True, slots=True)
class StartRequest:
    dataset_id: str
    component_kind: ComponentKind
    component_id: str
    version: int | None = None
    judge: Judge | None = None
    name: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict[str, Any])


def version_label(batch: Batch) -> str:
    return batch.target.label


def summary_of(batch: Batch) -> Summary | None:
    return Summary.from_dict(batch.summary) if batch.summary is not None else None


class StartBatch:
    def __init__(
        self,
        access: EvalAccess,
        datasets: DatasetRepository,
        batches: BatchRepository,
        audit: AuditLog,
        queue: JobQueue,
    ) -> None:
        self._access = access
        self._datasets = datasets
        self._batches = batches
        self._audit = audit
        self._queue = queue

    async def __call__(self, principal: Principal, instance_ref: str, request: StartRequest) -> Batch:
        instance = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        family = f"{request.component_kind}s"
        await self._access.require(principal, f"{family}:{request.component_id}:run", instance)
        dataset = await self._datasets.get(request.dataset_id)
        if dataset is None:
            raise NotFoundError(f"There is no dataset {request.dataset_id}.")
        cases = await self._datasets.cases(dataset.id)
        if not cases:
            raise ValidationFailedError(f"Dataset {dataset.name} has no cases yet.")

        bridge = await self._access.bridge(instance)
        if (request.version is not None or request.judge is not None) and not bridge.versions:
            what = "Evaluating a specific or draft version" if request.version is not None else "Choosing the judge"
            raise BridgeRequiredError(f"{what} needs agnostic-bridge. {bridge.reason or ''}".strip())
        draft = await self._is_draft(principal, instance, request) if request.version is not None else False
        target = Target(request.component_kind, request.component_id, request.version, draft)
        name = (request.name or f"{request.component_id} {EVAL_TYPE_LABELS[dataset.eval_type].lower()}").strip()
        batch = Batch(
            id=new_id("evb"),
            instance_id=instance.id,
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            case_count=len(cases),
            name=name[:255],
            target=target,
            eval_type=dataset.eval_type,
            judge=request.judge,
            via_bridge=bridge.versions,
            params=_params(request.params),
            status="queued",
            progress=0.0,
            started_by=principal.id,
            started_by_name=principal.display_name,
            started_at=utcnow(),
            finished_at=None,
            summary=None,
        )
        await self._batches.create(batch, cases)
        _ = await self._audit.record(
            AuditEntry(
                action="evals.batch.started",
                actor=actor_of(principal),
                resource_kind="eval_batch",
                resource_id=batch.id,
                resource_display=batch.name,
                instance_id=instance.id,
                fields={
                    "component": f"{target.component_id} {target.label}",
                    "dataset": dataset.name,
                    "cases": str(len(cases)),
                },
            )
        )
        await self._batches.commit()
        _ = await self._queue.defer(RUN_TASK, lock=f"evals:{instance.id}", batch_id=batch.id)
        return batch

    async def _is_draft(self, principal: Principal, instance: Instance, request: StartRequest) -> bool:
        path = f"/components/{request.component_id}/configs/{request.version}"
        response = await self._access.call(principal, instance, "GET", path)
        if response.status == 404:  # noqa: PLR2004
            raise NotFoundError(f"{request.component_id} has no version {request.version} on {instance.display_name}.")
        if not response.ok or not isinstance(response.body, dict):
            raise ValidationFailedError(f"Couldn't read version {request.version}: {detail(response)}")
        return cast("dict[str, Any]", response.body).get("stage") != "published"


def _params(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "num_iterations": (int, 1, 20),
        "warmup_runs": (int, 0, 10),
        "threshold": (int, 1, 10),
    }
    params: dict[str, Any] = {}
    for key, (kind, low, high) in allowed.items():
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, kind) or isinstance(value, bool) or not low <= value <= high:
            raise ValidationFailedError(f"{key} must be a whole number from {low} to {high}.")
        params[key] = value
    if raw.get("allow_additional_tool_calls") is not None:
        params["allow_additional_tool_calls"] = bool(raw["allow_additional_tool_calls"])
    return params


@dataclass(frozen=True, slots=True)
class BatchDetail:
    batch: Batch
    items: list[Item]
    baseline: Batch | None
    """The newest finished batch of another version on the same dataset: the default comparison."""


class Batches:
    def __init__(self, access: EvalAccess, batches: BatchRepository, audit: AuditLog) -> None:
        self._access = access
        self._batches = batches
        self._audit = audit

    async def _batch(self, principal: Principal, instance_ref: str, batch_id: str) -> tuple[Instance, Batch]:
        instance = await self._access.instance(principal, instance_ref, READ_SCOPE)
        batch = await self._batches.get(batch_id)
        if batch is None or batch.instance_id != instance.id:
            raise NotFoundError(f"There is no evaluation {batch_id} on {instance.display_name}.")
        return instance, batch

    async def get(self, principal: Principal, instance_ref: str, batch_id: str) -> BatchDetail:
        instance, batch = await self._batch(principal, instance_ref, batch_id)
        others = await self._batches.latest(instance.id, batch.target.component_id, batch.dataset_id, batch.eval_type)
        baseline = next(
            (
                other
                for other in others
                if other.id != batch.id
                and (other.target.version, other.target.draft) != (batch.target.version, batch.target.draft)
                and not other.target.draft
            ),
            None,
        ) or next((other for other in others if other.id != batch.id and other.target != batch.target), None)
        return BatchDetail(batch, await self._batches.items(batch.id), baseline)

    async def compare(self, principal: Principal, instance_ref: str, batch_id: str, other_id: str) -> BatchComparison:
        _, batch = await self._batch(principal, instance_ref, batch_id)
        other = await self._batches.get(other_id)
        if other is None:
            raise NotFoundError(f"There is no evaluation {other_id}.")
        if other.instance_id != batch.instance_id:
            other_instance = await self._access.by_id(other.instance_id)
            if other_instance is None:
                raise NotFoundError(f"There is no evaluation {other_id}.")
            await self._access.require(principal, READ_SCOPE, other_instance)
        if other.dataset_id != batch.dataset_id:
            raise ValidationFailedError("Only evaluations of the same dataset can be compared case by case.")
        before, after = (other, batch) if other.started_at <= batch.started_at else (batch, other)
        rows = compare_cases(await self._batches.items(before.id), await self._batches.items(after.id))
        return BatchComparison(
            before=before,
            after=after,
            rows=rows,
            counts=counts(rows),
            insight=insight(rows, version_label(before), version_label(after)),
        )

    async def cancel(self, principal: Principal, instance_ref: str, batch_id: str) -> Batch:
        instance, batch = await self._batch(principal, instance_ref, batch_id)
        await self._access.require(principal, WRITE_SCOPE, instance)
        if batch.finished:
            return batch
        await self._batches.update(batch.id, status="cancelled", finished_at=utcnow())
        _ = await self._audit.record(
            AuditEntry(
                action="evals.batch.cancelled",
                actor=actor_of(principal),
                resource_kind="eval_batch",
                resource_id=batch.id,
                resource_display=batch.name,
                instance_id=instance.id,
                fields={"batch": batch.name},
            )
        )
        await self._batches.commit()
        return cast("Batch", await self._batches.get(batch.id))

    async def results(
        self, principal: Principal, instance_ref: str, component_id: str, version: int | None
    ) -> list[Batch]:
        """The newest finished batch per dataset for one component version (``None``: the current version)."""
        instance = await self._access.instance(principal, instance_ref, READ_SCOPE)
        latest: dict[tuple[str, str], Batch] = {}
        for batch in await self._batches.latest(instance.id, component_id, version=version, any_version=False):
            latest.setdefault((batch.dataset_id, batch.eval_type), batch)
        return list(latest.values())


@dataclass(frozen=True, slots=True)
class BatchComparison:
    before: Batch
    after: Batch
    rows: Sequence[CaseChange]
    counts: ComparisonCounts
    insight: str


# ---------------------------------------------------------------- the evaluations table


type Source = Literal["batch", "agentos"]


@dataclass(frozen=True, slots=True)
class EvaluationRow:
    source: Source
    id: str
    name: str
    eval_type: EvalType
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
    dataset_name: str | None = None
    case_count: int | None = None


def batch_row(batch: Batch) -> EvaluationRow:
    summary = summary_of(batch)
    bad = bool(summary and ((summary.avg is not None and summary.avg < LOW_SCORE) or summary.failed or summary.errors))
    return EvaluationRow(
        source="batch",
        id=batch.id,
        name=batch.name,
        eval_type=batch.eval_type,
        component_kind=batch.target.kind,
        component_id=batch.target.component_id,
        version_label=batch.target.label,
        model=batch.judge.model_id if batch.judge else None,
        judge=batch.judge is not None,
        result=headline(batch.eval_type, summary) if summary else batch.status.capitalize(),
        bad=bad,
        status=batch.status,
        progress=batch.progress,
        created_at=batch.started_at,
        dataset_name=batch.dataset_name,
        case_count=batch.case_count,
    )


def standalone_row(raw: Mapping[str, Any]) -> EvaluationRow | None:
    eval_type = str(raw.get("eval_type") or "")
    if eval_type not in EVAL_TYPES:
        return None
    kind: EvalType = eval_type
    result = outcome(kind, raw)
    if kind == "performance" and result.latency_ms is not None:
        text = f"{result.latency_ms / 1000:.1f} s avg"
    elif result.score is not None and kind == "accuracy":
        text = f"{result.score:.2f} avg"
    elif result.passed is not None:
        text = "Passed" if result.passed else "Failed"
    else:
        text = "Done"
    component_kind = "agent" if raw.get("agent_id") else "team" if raw.get("team_id") else None
    created = raw.get("created_at")
    return EvaluationRow(
        source="agentos",
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or raw.get("evaluated_component_name") or "Evaluation"),
        eval_type=kind,
        component_kind=component_kind,
        component_id=cast("str | None", raw.get("agent_id") or raw.get("team_id") or raw.get("workflow_id")),
        version_label=None,
        model=cast("str | None", raw.get("model_id")),
        judge=kind == "agent_as_judge",
        result=text,
        bad=(result.score is not None and result.score < LOW_SCORE) or result.passed is False,
        status="completed",
        progress=1.0,
        created_at=_parse(created) if created is not None else None,
    )


def _parse(value: object) -> datetime | None:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=utcnow().tzinfo)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=utcnow().tzinfo)


@dataclass(frozen=True, slots=True)
class Evaluations:
    rows: list[EvaluationRow]
    standalone_unavailable: str | None


class ListEvaluations:
    def __init__(self, access: EvalAccess, batches: BatchRepository) -> None:
        self._access = access
        self._batches = batches

    async def __call__(
        self,
        principal: Principal,
        instance_ref: str,
        *,
        eval_type: EvalType | None,
        component_id: str | None,
        model: str | None,
        limit: int = 100,
    ) -> Evaluations:
        instance = await self._access.instance(principal, instance_ref, READ_SCOPE)
        batches = await self._batches.list(
            instance.id, BatchFilter(eval_type=eval_type, component_id=component_id, model=model, limit=limit)
        )
        rows = [batch_row(batch) for batch in batches]
        params: dict[str, str | int] = {"limit": limit, "page": 1, "sort_by": "created_at", "sort_order": "desc"}
        if eval_type:
            params["eval_types"] = eval_type
        if model:
            params["model_id"] = model
        response = await self._access.call(principal, instance, "GET", "/eval-runs", params=params)
        unavailable: str | None = None
        if response.ok:
            owned = await self._batches.eval_run_ids(instance.id)
            for raw in page_items(response.body):
                row = standalone_row(raw)
                if row is None or row.id in owned:
                    continue
                if component_id and row.component_id != component_id:
                    continue
                rows.append(row)
        else:
            unavailable = detail(response)
        rows.sort(key=lambda row: row.created_at or utcnow(), reverse=True)
        return Evaluations(rows[:limit], unavailable)


async def bridge_support(access: EvalAccess, principal: Principal, instance_ref: str) -> BridgeSupport:
    instance = await access.instance(principal, instance_ref, READ_SCOPE)
    return await access.bridge(instance)
