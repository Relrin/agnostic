"""SQL repositories of the evals module."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_evals.application.ports import BatchFilter, CaseChanges
from agnostic_evals.domain.gates import Gate
from agnostic_evals.domain.importing import CaseDraft
from agnostic_evals.domain.model import (
    Batch,
    BatchStatus,
    Case,
    ComponentKind,
    Dataset,
    EvalRuleError,
    EvalType,
    Item,
    ItemStatus,
    Judge,
    Outcome,
    Target,
)
from agnostic_evals.infrastructure.tables import BatchItemRow, BatchRow, CaseRow, DatasetRow, GateRow
from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.ids import new_id

FINISHED = ("completed", "failed", "cancelled")


def _case(row: CaseRow) -> Case:
    return Case(
        id=row.id,
        dataset_id=row.dataset_id,
        position=row.position,
        input=row.input,
        expected_output=row.expected_output,
        criteria=row.criteria,
        expected_tool_calls=tuple(row.expected_tool_calls) if row.expected_tool_calls else None,
        metadata=dict(row.metadata_ or {}),
    )


def case_document(case: Case) -> dict[str, Any]:
    return {
        "id": case.id,
        "dataset_id": case.dataset_id,
        "position": case.position,
        "input": case.input,
        "expected_output": case.expected_output,
        "criteria": case.criteria,
        "expected_tool_calls": list(case.expected_tool_calls) if case.expected_tool_calls else None,
        "metadata": dict(case.metadata),
    }


def case_from_document(value: Mapping[str, Any]) -> Case:
    calls = value.get("expected_tool_calls")
    return Case(
        id=str(value["id"]),
        dataset_id=str(value["dataset_id"]),
        position=int(value["position"]),
        input=str(value["input"]),
        expected_output=value.get("expected_output"),
        criteria=value.get("criteria"),
        expected_tool_calls=tuple(cast("list[str]", calls)) if calls else None,
        metadata=dict(value.get("metadata") or {}),
    )


class SqlDatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _counts(self, ids: Sequence[str]) -> dict[str, int]:
        if not ids:
            return {}
        rows = await self._session.execute(
            select(CaseRow.dataset_id, func.count()).where(CaseRow.dataset_id.in_(ids)).group_by(CaseRow.dataset_id)
        )
        return {str(dataset_id): int(count) for dataset_id, count in rows}

    @staticmethod
    def _dataset(row: DatasetRow, count: int) -> Dataset:
        return Dataset(
            id=row.id,
            name=row.name,
            description=row.description or "",
            eval_type=cast("EvalType", row.eval_type),
            tags=tuple(row.tags or ()),
            version=row.version,
            case_count=count,
            created_by=row.created_by,
            created_at=aware(row.created_at),
            updated_at=aware(row.updated_at),
        )

    async def list(self, eval_type: EvalType | None = None) -> list[Dataset]:
        query = select(DatasetRow).order_by(DatasetRow.name)
        if eval_type is not None:
            query = query.where(DatasetRow.eval_type == eval_type)
        rows = (await self._session.scalars(query)).all()
        counts = await self._counts([row.id for row in rows])
        return [self._dataset(row, counts.get(row.id, 0)) for row in rows]

    async def get(self, dataset_id: str) -> Dataset | None:
        row = await self._session.get(DatasetRow, dataset_id)
        if row is None:
            return None
        return self._dataset(row, (await self._counts([row.id])).get(row.id, 0))

    async def _row(self, dataset_id: str) -> DatasetRow:
        row = await self._session.get(DatasetRow, dataset_id)
        if row is None:
            raise NotFoundError(f"There is no dataset {dataset_id}.")
        return row

    async def create(
        self, *, name: str, description: str, eval_type: EvalType, tags: Sequence[str], created_by: str
    ) -> Dataset:
        now = utcnow()
        row = DatasetRow(
            id=new_id("ds"),
            name=name,
            description=description,
            eval_type=eval_type,
            tags=list(tags),
            version=1,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return self._dataset(row, 0)

    async def update(
        self, dataset_id: str, *, name: str | None, description: str | None, tags: Sequence[str] | None
    ) -> Dataset:
        row = await self._row(dataset_id)
        if name is not None:
            row.name = name
        if description is not None:
            row.description = description
        if tags is not None:
            row.tags = list(tags)
        row.updated_at = utcnow()
        await self._session.flush()
        return self._dataset(row, (await self._counts([row.id])).get(row.id, 0))

    async def delete(self, dataset_id: str) -> None:
        _ = await self._session.execute(delete(CaseRow).where(CaseRow.dataset_id == dataset_id))
        _ = await self._session.execute(delete(DatasetRow).where(DatasetRow.id == dataset_id))

    async def cases(self, dataset_id: str) -> list[Case]:
        rows = await self._session.scalars(
            select(CaseRow).where(CaseRow.dataset_id == dataset_id).order_by(CaseRow.position)
        )
        return [_case(row) for row in rows]

    async def case(self, case_id: str) -> Case | None:
        row = await self._session.get(CaseRow, case_id)
        return _case(row) if row is not None else None

    async def _bump(self, dataset_id: str) -> None:
        row = await self._row(dataset_id)
        row.version += 1
        row.updated_at = utcnow()

    async def add_cases(self, dataset_id: str, drafts: Sequence[CaseDraft], *, replace: bool) -> list[Case]:
        await self._bump(dataset_id)
        if replace:
            _ = await self._session.execute(delete(CaseRow).where(CaseRow.dataset_id == dataset_id))
            start = 0
        else:
            start = int(
                await self._session.scalar(
                    select(func.coalesce(func.max(CaseRow.position), 0)).where(CaseRow.dataset_id == dataset_id)
                )
                or 0
            )
        rows = [
            CaseRow(
                id=new_id("evc"),
                dataset_id=dataset_id,
                position=start + index,
                input=draft.input,
                expected_output=draft.expected_output,
                criteria=draft.criteria,
                expected_tool_calls=list(draft.expected_tool_calls) if draft.expected_tool_calls else None,
                metadata_=dict(draft.metadata),
            )
            for index, draft in enumerate(drafts, start=1)
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return [_case(row) for row in rows]

    async def update_case(self, case_id: str, changes: CaseChanges) -> Case:
        row = await self._session.get(CaseRow, case_id)
        if row is None:
            raise NotFoundError(f"There is no case {case_id}.")
        if changes.input is not None:
            row.input = changes.input
        if changes.expected_output is not None or "expected_output" in changes.clear:
            row.expected_output = changes.expected_output
        if changes.criteria is not None or "criteria" in changes.clear:
            row.criteria = changes.criteria
        if changes.expected_tool_calls is not None or "expected_tool_calls" in changes.clear:
            row.expected_tool_calls = list(changes.expected_tool_calls) if changes.expected_tool_calls else None
        await self._bump(row.dataset_id)
        await self._session.flush()
        return _case(row)

    async def delete_case(self, case_id: str) -> None:
        row = await self._session.get(CaseRow, case_id)
        if row is None:
            raise NotFoundError(f"There is no case {case_id}.")
        dataset_id, position = row.dataset_id, row.position
        await self._session.delete(row)
        await self._session.flush()
        _ = await self._session.execute(
            update(CaseRow)
            .where(CaseRow.dataset_id == dataset_id, CaseRow.position > position)
            .values(position=CaseRow.position - 1)
        )
        await self._bump(dataset_id)

    async def commit(self) -> None:
        await self._session.commit()


def _batch(row: BatchRow) -> Batch:
    judge = Judge(row.judge_model_id, row.judge_provider or "") if row.judge_model_id else None
    return Batch(
        id=row.id,
        instance_id=row.instance_id,
        dataset_id=row.dataset_id,
        dataset_name=row.dataset_name,
        case_count=row.case_count,
        name=row.name,
        target=Target(
            kind=cast("ComponentKind", row.component_kind),
            component_id=row.component_id,
            version=row.component_version,
            draft=row.draft,
        ),
        eval_type=cast("EvalType", row.eval_type),
        judge=judge,
        via_bridge=row.via_bridge,
        params=dict(row.params or {}),
        status=cast("BatchStatus", row.status),
        progress=row.progress,
        started_by=row.started_by,
        started_by_name=row.started_by_name,
        started_at=aware(row.started_at),
        finished_at=aware_or_none(row.finished_at),
        summary=dict(row.summary) if row.summary is not None else None,
        error=row.error,
    )


def _item(row: BatchItemRow) -> Item:
    outcome = None
    if row.status == "done":
        outcome = Outcome(
            score=row.score, passed=row.passed, reason=row.reason, actual=row.actual, latency_ms=row.latency_ms
        )
    return Item(
        id=row.id,
        batch_id=row.batch_id,
        case_id=row.case_id,
        position=row.position,
        input=row.input,
        expected=row.expected,
        status=cast("ItemStatus", row.status),
        eval_run_id=row.eval_run_id,
        outcome=outcome,
        trace_id=row.trace_id,
        error=row.error,
    )


class SqlBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, batch: Batch, cases: Sequence[Case]) -> None:
        self._session.add(
            BatchRow(
                id=batch.id,
                instance_id=batch.instance_id,
                dataset_id=batch.dataset_id,
                dataset_name=batch.dataset_name,
                case_count=batch.case_count,
                name=batch.name,
                component_kind=batch.target.kind,
                component_id=batch.target.component_id,
                component_version=batch.target.version,
                draft=batch.target.draft,
                eval_type=batch.eval_type,
                judge_model_id=batch.judge.model_id if batch.judge else None,
                judge_provider=batch.judge.provider if batch.judge else None,
                via_bridge=batch.via_bridge,
                params=dict(batch.params),
                status=batch.status,
                progress=batch.progress,
                started_by=batch.started_by,
                started_by_name=batch.started_by_name,
                started_at=batch.started_at,
            )
        )
        await self._session.flush()
        self._session.add_all(
            BatchItemRow(
                id=new_id("evi"),
                batch_id=batch.id,
                case_id=case.id,
                position=case.position,
                input=case.input,
                expected=case.expected,
                case=case_document(case),
                status="pending",
            )
            for case in cases
        )
        await self._session.flush()

    async def get(self, batch_id: str) -> Batch | None:
        row = await self._session.get(BatchRow, batch_id)
        return _batch(row) if row is not None else None

    async def status(self, batch_id: str) -> BatchStatus | None:
        value = await self._session.scalar(select(BatchRow.status).where(BatchRow.id == batch_id))
        return cast("BatchStatus | None", value)

    async def list(self, instance_id: str, where: BatchFilter) -> list[Batch]:
        query = select(BatchRow).where(BatchRow.instance_id == instance_id)
        if where.eval_type is not None:
            query = query.where(BatchRow.eval_type == where.eval_type)
        if where.component_id is not None:
            query = query.where(BatchRow.component_id == where.component_id)
        if where.model is not None:
            query = query.where(BatchRow.judge_model_id == where.model)
        rows = await self._session.scalars(query.order_by(BatchRow.started_at.desc()).limit(where.limit))
        return [_batch(row) for row in rows]

    async def items(self, batch_id: str) -> list[Item]:
        rows = await self._session.scalars(
            select(BatchItemRow).where(BatchItemRow.batch_id == batch_id).order_by(BatchItemRow.position)
        )
        return [_item(row) for row in rows]

    async def pending(self, batch_id: str) -> list[tuple[str, Case]]:
        rows = await self._session.scalars(
            select(BatchItemRow)
            .where(BatchItemRow.batch_id == batch_id, BatchItemRow.status.in_(("pending", "running")))
            .order_by(BatchItemRow.position)
        )
        return [(row.id, case_from_document(row.case)) for row in rows]

    async def finish_item(
        self,
        item_id: str,
        status: ItemStatus,
        *,
        outcome: Outcome | None = None,
        eval_run_id: str | None = None,
        trace_id: str | None = None,
        error: str | None = None,
    ) -> None:
        row = await self._session.get(BatchItemRow, item_id)
        if row is None:
            return
        row.status = status
        row.eval_run_id = eval_run_id
        row.trace_id = trace_id
        row.error = error
        if outcome is not None:
            row.score = outcome.score
            row.passed = outcome.passed
            row.reason = outcome.reason
            row.actual = outcome.actual
            row.latency_ms = outcome.latency_ms
        await self._session.flush()

    async def update(
        self,
        batch_id: str,
        *,
        status: BatchStatus | None = None,
        progress: float | None = None,
        summary: Mapping[str, Any] | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {}
        if status is not None:
            values["status"] = status
        if progress is not None:
            values["progress"] = progress
        if summary is not None:
            values["summary"] = dict(summary)
        if finished_at is not None:
            values["finished_at"] = finished_at
        if error is not None:
            values["error"] = error
        if values:
            _ = await self._session.execute(
                update(BatchRow)
                .where(BatchRow.id == batch_id)
                .values(**values)
                .execution_options(synchronize_session="fetch")
            )

    async def latest(
        self,
        instance_id: str,
        component_id: str,
        dataset_id: str | None = None,
        eval_type: EvalType | None = None,
        *,
        version: int | None = None,
        any_version: bool = True,
    ) -> list[Batch]:
        query = select(BatchRow).where(
            BatchRow.instance_id == instance_id,
            BatchRow.component_id == component_id,
            BatchRow.status.in_(("completed", "failed")),
        )
        if dataset_id is not None:
            query = query.where(BatchRow.dataset_id == dataset_id)
        if eval_type is not None:
            query = query.where(BatchRow.eval_type == eval_type)
        if not any_version:
            query = query.where(
                BatchRow.component_version.is_(None) if version is None else BatchRow.component_version == version
            )
        rows = await self._session.scalars(query.order_by(BatchRow.finished_at.desc(), BatchRow.started_at.desc()))
        return [_batch(row) for row in rows]

    async def eval_run_ids(self, instance_id: str) -> set[str]:
        rows = await self._session.scalars(
            select(BatchItemRow.eval_run_id)
            .join(BatchRow, BatchRow.id == BatchItemRow.batch_id)
            .where(BatchRow.instance_id == instance_id, BatchItemRow.eval_run_id.is_not(None))
        )
        return {str(value) for value in rows if value}

    async def commit(self) -> None:
        await self._session.commit()


def _gate(row: GateRow) -> Gate:
    return Gate(
        id=row.id,
        instance_id=row.instance_id,
        component_kind=cast("ComponentKind", row.component_kind),
        component_id=row.component_id,
        dataset_id=row.dataset_id,
        eval_type=cast("EvalType", row.eval_type),
        min_average=row.min_average,
        enabled=row.enabled,
        updated_by=row.updated_by,
        updated_at=aware(row.updated_at),
    )


class SqlGateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, instance_id: str, component_id: str | None = None) -> list[Gate]:
        query = select(GateRow).where(GateRow.instance_id == instance_id)
        if component_id is not None:
            query = query.where(GateRow.component_id == component_id)
        rows = await self._session.scalars(query.order_by(GateRow.component_id, GateRow.dataset_id))
        return [_gate(row) for row in rows]

    async def get(self, gate_id: str) -> Gate | None:
        row = await self._session.get(GateRow, gate_id)
        return _gate(row) if row is not None else None

    async def upsert(
        self,
        *,
        instance_id: str,
        component_kind: ComponentKind,
        component_id: str,
        dataset_id: str,
        eval_type: EvalType,
        min_average: float,
        enabled: bool,
        updated_by: str,
    ) -> Gate:
        if not 0 <= min_average <= 10:  # noqa: PLR2004
            raise EvalRuleError("The minimum average is a score from 0 to 10.")
        row = await self._session.scalar(
            select(GateRow).where(
                GateRow.instance_id == instance_id,
                GateRow.component_id == component_id,
                GateRow.dataset_id == dataset_id,
                GateRow.eval_type == eval_type,
            )
        )
        if row is None:
            row = GateRow(
                id=new_id("gate"),
                instance_id=instance_id,
                component_id=component_id,
                dataset_id=dataset_id,
                eval_type=eval_type,
            )
            self._session.add(row)
        row.component_kind = component_kind
        row.min_average = min_average
        row.enabled = enabled
        row.updated_by = updated_by
        row.updated_at = utcnow()
        await self._session.flush()
        return _gate(row)

    async def delete(self, gate_id: str) -> None:
        _ = await self._session.execute(delete(GateRow).where(GateRow.id == gate_id))

    async def commit(self) -> None:
        await self._session.commit()
