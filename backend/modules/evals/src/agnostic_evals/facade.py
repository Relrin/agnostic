"""The only import surface other modules may use: publish-gate results for one component version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agnostic_evals.application.batches import summary_of
from agnostic_evals.application.ports import BatchRepository, DatasetRepository, GateRepository
from agnostic_evals.domain.gates import GateResult, GateState, consequence

__all__ = ["EvalGates", "EvalGatesImpl", "GateCheck", "GateState"]


@dataclass(frozen=True, slots=True)
class GateCheck:
    gate_id: str
    dataset_id: str
    dataset_name: str | None
    eval_type: str
    min_average: float
    value: float | None
    batch_id: str | None
    state: GateState
    consequence: str

    @property
    def blocks(self) -> bool:
        return self.state in {"no_result", "would_block"}


class EvalGates(Protocol):
    async def check(self, instance_id: str, component_id: str, version: int, version_label: str) -> list[GateCheck]:
        """Every gate on the component, judged by the newest finished batch of exactly ``version``."""
        ...


class EvalGatesImpl:
    def __init__(self, gates: GateRepository, batches: BatchRepository, datasets: DatasetRepository) -> None:
        self._gates = gates
        self._batches = batches
        self._datasets = datasets

    async def check(self, instance_id: str, component_id: str, version: int, version_label: str) -> list[GateCheck]:
        checks: list[GateCheck] = []
        for gate in await self._gates.list(instance_id, component_id):
            newest = await self._batches.latest(
                instance_id, component_id, gate.dataset_id, gate.eval_type, version=version, any_version=False
            )
            result: GateResult | None = None
            if newest:
                summary = summary_of(newest[0])
                result = GateResult(newest[0].id, version_label, summary.gate_value if summary else None)
            dataset = await self._datasets.get(gate.dataset_id)
            judged = consequence(gate, result)
            checks.append(
                GateCheck(
                    gate_id=gate.id,
                    dataset_id=gate.dataset_id,
                    dataset_name=dataset.name if dataset else None,
                    eval_type=gate.eval_type,
                    min_average=gate.min_average,
                    value=result.value if result else None,
                    batch_id=result.batch_id if result else None,
                    state=judged.state,
                    consequence=judged.text,
                )
            )
        return checks
