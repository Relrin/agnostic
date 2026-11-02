"""Dependency wiring of the evals module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_evals.application.access import EvalAccess
from agnostic_evals.application.batches import Batches, ListEvaluations, StartBatch
from agnostic_evals.application.datasets import Datasets
from agnostic_evals.application.gates import Gates
from agnostic_evals.application.ports import BatchRepository, DatasetRepository, GateRepository
from agnostic_evals.application.run_batch import RunBatch
from agnostic_evals.infrastructure.repository import SqlBatchRepository, SqlDatasetRepository, SqlGateRepository
from agnostic_evals.settings import EvalsSettings
from agnostic_kernel.events import EventBus


class EvalsProvider(Provider):
    scope = Scope.REQUEST

    datasets_repo = provide(SqlDatasetRepository, provides=DatasetRepository)
    batches_repo = provide(SqlBatchRepository, provides=BatchRepository)
    gates_repo = provide(SqlGateRepository, provides=GateRepository)
    access = provide(EvalAccess)
    datasets = provide(Datasets)
    start = provide(StartBatch)
    batches = provide(Batches)
    evaluations = provide(ListEvaluations)
    gates = provide(Gates)

    @provide
    def run_batch(
        self, access: EvalAccess, batches: BatchRepository, bus: EventBus, settings: EvalsSettings
    ) -> RunBatch:
        return RunBatch(access, batches, bus, settings.concurrency)
