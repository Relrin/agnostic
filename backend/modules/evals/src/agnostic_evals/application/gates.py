"""Publish gates: configured here, enforced by Studio's Publish (with an audited override)."""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_evals.application.access import READ_SCOPE, EvalAccess, rule
from agnostic_evals.application.batches import summary_of
from agnostic_evals.application.ports import BatchRepository, DatasetRepository, GateRepository
from agnostic_evals.domain.gates import Consequence, Gate, GateResult, consequence
from agnostic_evals.domain.model import ComponentKind, EvalRuleError
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import NotFoundError

GATES_SCOPE = "evals:gates:write"


@dataclass(frozen=True, slots=True)
class GateView:
    gate: Gate
    dataset_name: str | None
    latest: GateResult | None
    consequence: Consequence


@dataclass(frozen=True, slots=True)
class GateRequest:
    component_kind: ComponentKind
    component_id: str
    dataset_id: str
    min_average: float
    enabled: bool


class Gates:
    def __init__(
        self,
        access: EvalAccess,
        gates: GateRepository,
        batches: BatchRepository,
        datasets: DatasetRepository,
        audit: AuditLog,
    ) -> None:
        self._access = access
        self._gates = gates
        self._batches = batches
        self._datasets = datasets
        self._audit = audit

    async def _view(self, gate: Gate) -> GateView:
        newest = await self._batches.latest(gate.instance_id, gate.component_id, gate.dataset_id, gate.eval_type)
        latest = None
        if newest:
            batch = newest[0]
            summary = summary_of(batch)
            latest = GateResult(batch.id, batch.target.label, summary.gate_value if summary else None)
        dataset = await self._datasets.get(gate.dataset_id)
        return GateView(gate, dataset.name if dataset else None, latest, consequence(gate, latest))

    async def list(self, principal: Principal, instance_ref: str, component_id: str | None) -> list[GateView]:
        instance = await self._access.instance(principal, instance_ref, READ_SCOPE)
        return [await self._view(gate) for gate in await self._gates.list(instance.id, component_id)]

    async def put(self, principal: Principal, instance_ref: str, request: GateRequest) -> GateView:
        instance = await self._access.instance(principal, instance_ref, READ_SCOPE)
        await self._access.require(principal, GATES_SCOPE, instance)
        dataset = await self._datasets.get(request.dataset_id)
        if dataset is None:
            raise NotFoundError(f"There is no dataset {request.dataset_id}.")
        try:
            gate = await self._gates.upsert(
                instance_id=instance.id,
                component_kind=request.component_kind,
                component_id=request.component_id,
                dataset_id=dataset.id,
                eval_type=dataset.eval_type,
                min_average=request.min_average,
                enabled=request.enabled,
                updated_by=principal.id,
            )
        except EvalRuleError as exc:
            raise rule(exc) from exc
        _ = await self._audit.record(
            AuditEntry(
                action="evals.gate.updated",
                actor=actor_of(principal),
                resource_kind="eval_gate",
                resource_id=gate.id,
                resource_display=f"{gate.component_id} on {dataset.name}",
                instance_id=instance.id,
                fields={
                    "component": gate.component_id,
                    "dataset": dataset.name,
                    "state": f"on, minimum {gate.min_average:g}" if gate.enabled else "off",
                },
            )
        )
        await self._gates.commit()
        return await self._view(gate)

    async def delete(self, principal: Principal, instance_ref: str, gate_id: str) -> None:
        instance = await self._access.instance(principal, instance_ref, READ_SCOPE)
        await self._access.require(principal, GATES_SCOPE, instance)
        gate = await self._gates.get(gate_id)
        if gate is None or gate.instance_id != instance.id:
            raise NotFoundError(f"There is no gate {gate_id} on {instance.display_name}.")
        await self._gates.delete(gate.id)
        _ = await self._audit.record(
            AuditEntry(
                action="evals.gate.deleted",
                actor=actor_of(principal),
                resource_kind="eval_gate",
                resource_id=gate.id,
                resource_display=gate.component_id,
                instance_id=instance.id,
                fields={"component": gate.component_id},
            )
        )
        await self._gates.commit()
