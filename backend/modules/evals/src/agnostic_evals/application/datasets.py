"""Eval datasets and their cases.

Datasets are org-wide; the routes run through an instance and check ``evals:read`` / ``evals:write`` there, so
whoever may run evals on an instance may curate the cases.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_evals.application.access import READ_SCOPE, WRITE_SCOPE, EvalAccess, rule
from agnostic_evals.application.ports import CaseChanges, DatasetRepository
from agnostic_evals.domain.importing import CaseDraft, ImportFormat, parse_cases
from agnostic_evals.domain.model import Case, Dataset, EvalRuleError, EvalType, check_case
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import NotFoundError


@dataclass(frozen=True, slots=True)
class DatasetDetail:
    dataset: Dataset
    cases: list[Case]


class Datasets:
    def __init__(self, access: EvalAccess, datasets: DatasetRepository, audit: AuditLog) -> None:
        self._access = access
        self._datasets = datasets
        self._audit = audit

    async def _get(self, dataset_id: str) -> Dataset:
        dataset = await self._datasets.get(dataset_id)
        if dataset is None:
            raise NotFoundError(f"There is no dataset {dataset_id}.")
        return dataset

    async def _record(self, principal: Principal, action: str, dataset: Dataset, **fields: str) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="eval_dataset",
                resource_id=dataset.id,
                resource_display=dataset.name,
                fields={"dataset": dataset.name, **fields},
            )
        )

    async def list(self, principal: Principal, instance_ref: str, eval_type: EvalType | None) -> list[Dataset]:
        _ = await self._access.instance(principal, instance_ref, READ_SCOPE)
        return await self._datasets.list(eval_type)

    async def get(self, principal: Principal, instance_ref: str, dataset_id: str) -> DatasetDetail:
        _ = await self._access.instance(principal, instance_ref, READ_SCOPE)
        dataset = await self._get(dataset_id)
        return DatasetDetail(dataset, await self._datasets.cases(dataset.id))

    async def create(
        self,
        principal: Principal,
        instance_ref: str,
        *,
        name: str,
        description: str,
        eval_type: EvalType,
        tags: Sequence[str],
        cases: Sequence[CaseDraft],
    ) -> DatasetDetail:
        _ = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        self._check(eval_type, cases)
        dataset = await self._datasets.create(
            name=name.strip(), description=description.strip(), eval_type=eval_type, tags=tags, created_by=principal.id
        )
        created = await self._datasets.add_cases(dataset.id, cases, replace=False) if cases else []
        await self._record(principal, "evals.dataset.created", dataset, cases=str(len(created)))
        await self._datasets.commit()
        return DatasetDetail(await self._get(dataset.id), created)

    async def update(
        self,
        principal: Principal,
        instance_ref: str,
        dataset_id: str,
        *,
        name: str | None,
        description: str | None,
        tags: Sequence[str] | None,
    ) -> Dataset:
        _ = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        _ = await self._get(dataset_id)
        dataset = await self._datasets.update(
            dataset_id, name=name.strip() if name else None, description=description, tags=tags
        )
        await self._record(principal, "evals.dataset.updated", dataset)
        await self._datasets.commit()
        return dataset

    async def delete(self, principal: Principal, instance_ref: str, dataset_id: str) -> None:
        _ = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        dataset = await self._get(dataset_id)
        await self._datasets.delete(dataset_id)
        await self._record(principal, "evals.dataset.deleted", dataset)
        await self._datasets.commit()

    @staticmethod
    def _check(eval_type: EvalType, drafts: Sequence[CaseDraft]) -> None:
        for position, draft in enumerate(drafts, start=1):
            try:
                check_case(
                    eval_type,
                    Case(
                        id="",
                        dataset_id="",
                        position=position,
                        input=draft.input,
                        expected_output=draft.expected_output,
                        criteria=draft.criteria,
                        expected_tool_calls=draft.expected_tool_calls,
                    ),
                )
            except EvalRuleError as exc:
                raise rule(exc) from exc

    async def add_cases(
        self, principal: Principal, instance_ref: str, dataset_id: str, drafts: Sequence[CaseDraft]
    ) -> list[Case]:
        _ = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        dataset = await self._get(dataset_id)
        self._check(dataset.eval_type, drafts)
        created = await self._datasets.add_cases(dataset_id, drafts, replace=False)
        await self._record(principal, "evals.dataset.updated", dataset)
        await self._datasets.commit()
        return created

    async def import_cases(
        self,
        principal: Principal,
        instance_ref: str,
        dataset_id: str,
        *,
        content: str,
        fmt: ImportFormat,
        replace: bool,
    ) -> list[Case]:
        _ = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        dataset = await self._get(dataset_id)
        try:
            drafts = parse_cases(content, fmt, dataset.eval_type)
        except EvalRuleError as exc:
            raise rule(exc) from exc
        created = await self._datasets.add_cases(dataset_id, drafts, replace=replace)
        await self._record(principal, "evals.dataset.imported", dataset, cases=str(len(created)), format=fmt)
        await self._datasets.commit()
        return created

    async def update_case(
        self, principal: Principal, instance_ref: str, dataset_id: str, case_id: str, changes: CaseChanges
    ) -> Case:
        _ = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        dataset = await self._get(dataset_id)
        current = await self._datasets.case(case_id)
        if current is None or current.dataset_id != dataset_id:
            raise NotFoundError(f"Dataset {dataset.name} has no case {case_id}.")
        case = await self._datasets.update_case(case_id, changes)
        try:
            check_case(dataset.eval_type, case)
        except EvalRuleError as exc:
            raise rule(exc) from exc
        await self._record(principal, "evals.dataset.updated", dataset)
        await self._datasets.commit()
        return case

    async def delete_case(self, principal: Principal, instance_ref: str, dataset_id: str, case_id: str) -> None:
        _ = await self._access.instance(principal, instance_ref, WRITE_SCOPE)
        dataset = await self._get(dataset_id)
        current = await self._datasets.case(case_id)
        if current is None or current.dataset_id != dataset_id:
            raise NotFoundError(f"Dataset {dataset.name} has no case {case_id}.")
        await self._datasets.delete_case(case_id)
        await self._record(principal, "evals.dataset.updated", dataset)
        await self._datasets.commit()
