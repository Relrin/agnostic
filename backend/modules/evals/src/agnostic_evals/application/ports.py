"""Ports of the evals module."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from agnostic_evals.domain.gates import Gate
from agnostic_evals.domain.importing import CaseDraft
from agnostic_evals.domain.model import (
    Batch,
    BatchStatus,
    Case,
    ComponentKind,
    Dataset,
    EvalType,
    Item,
    ItemStatus,
    Outcome,
)


@dataclass(frozen=True, slots=True)
class BatchFilter:
    eval_type: EvalType | None = None
    component_id: str | None = None
    model: str | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class CaseChanges:
    input: str | None = None
    expected_output: str | None = None
    criteria: str | None = None
    expected_tool_calls: Sequence[str] | None = None
    clear: frozenset[str] = frozenset()
    """Fields to set to empty."""


class DatasetRepository(Protocol):
    async def list(self, eval_type: EvalType | None = None) -> list[Dataset]: ...
    async def get(self, dataset_id: str) -> Dataset | None: ...
    async def create(
        self, *, name: str, description: str, eval_type: EvalType, tags: Sequence[str], created_by: str
    ) -> Dataset: ...
    async def update(
        self, dataset_id: str, *, name: str | None, description: str | None, tags: Sequence[str] | None
    ) -> Dataset: ...
    async def delete(self, dataset_id: str) -> None: ...
    async def cases(self, dataset_id: str) -> list[Case]: ...
    async def case(self, case_id: str) -> Case | None: ...
    async def add_cases(self, dataset_id: str, drafts: Sequence[CaseDraft], *, replace: bool) -> list[Case]:
        """Append (or replace all) and bump the dataset version."""
        ...

    async def update_case(self, case_id: str, changes: CaseChanges) -> Case: ...
    async def delete_case(self, case_id: str) -> None:
        """Delete and renumber the remaining cases."""
        ...

    async def commit(self) -> None: ...


class BatchRepository(Protocol):
    async def create(self, batch: Batch, cases: Sequence[Case]) -> None: ...
    async def get(self, batch_id: str) -> Batch | None: ...
    async def status(self, batch_id: str) -> BatchStatus | None:
        """Read straight from the database (another request may have cancelled the batch)."""
        ...

    async def list(self, instance_id: str, where: BatchFilter) -> list[Batch]: ...
    async def items(self, batch_id: str) -> list[Item]: ...
    async def pending(self, batch_id: str) -> list[tuple[str, Case]]:
        """``(item id, case snapshot)`` of the items still to run."""
        ...

    async def finish_item(
        self,
        item_id: str,
        status: ItemStatus,
        *,
        outcome: Outcome | None = None,
        eval_run_id: str | None = None,
        trace_id: str | None = None,
        error: str | None = None,
    ) -> None: ...

    async def update(
        self,
        batch_id: str,
        *,
        status: BatchStatus | None = None,
        progress: float | None = None,
        summary: Mapping[str, Any] | None = None,
        finished_at: datetime | None = None,
        error: str | None = None,
    ) -> None: ...

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
        """Finished batches, newest first."""
        ...

    async def eval_run_ids(self, instance_id: str) -> set[str]: ...
    async def commit(self) -> None: ...


class GateRepository(Protocol):
    async def list(self, instance_id: str, component_id: str | None = None) -> list[Gate]: ...
    async def get(self, gate_id: str) -> Gate | None: ...
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
    ) -> Gate: ...
    async def delete(self, gate_id: str) -> None: ...
    async def commit(self) -> None: ...
