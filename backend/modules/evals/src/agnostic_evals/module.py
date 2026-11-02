"""Module declaration: eval datasets, batches, version comparison and publish gates."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dishka import Provider
from pydantic_settings import BaseSettings
from sqlalchemy import MetaData

from agnostic_evals import jobs
from agnostic_evals.api.router import router
from agnostic_evals.infrastructure.tables import EvalsBase
from agnostic_evals.providers import EvalsProvider
from agnostic_evals.settings import EvalsSettings
from agnostic_kernel.modules import AuditActionDecl, BaseModule, CapabilityProbe, JobSpec, RouterSpec


class EvalsModule(BaseModule):
    name = "evals"
    version = "0.1.0"
    depends_on = ("access", "audit", "instances", "gateway")

    def settings_model(self) -> type[BaseSettings] | None:
        return EvalsSettings

    def provide(self) -> Iterable[Provider]:
        return (EvalsProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/instances", tags=("evals",)),)

    def metadata(self) -> MetaData | None:
        return EvalsBase.metadata

    def migrations(self) -> Path | None:
        return Path(__file__).with_name("migrations") / "versions"

    def jobs(self) -> Iterable[JobSpec]:
        return (JobSpec(name=jobs.RUN_TASK, func=jobs.run_batch, queue="evals"),)

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("evals.dataset.created", "{actor} created eval dataset {dataset} ({cases} cases)"),
            AuditActionDecl("evals.dataset.updated", "{actor} changed eval dataset {dataset}"),
            AuditActionDecl("evals.dataset.imported", "{actor} imported {cases} cases into {dataset}"),
            AuditActionDecl("evals.dataset.deleted", "{actor} deleted eval dataset {dataset}"),
            AuditActionDecl("evals.batch.started", "{actor} evaluated {component} on {dataset} ({cases} cases)"),
            AuditActionDecl("evals.batch.cancelled", "{actor} cancelled evaluation {batch}"),
            AuditActionDecl("evals.gate.updated", "{actor} set the publish gate of {component} on {dataset}: {state}"),
            AuditActionDecl("evals.gate.deleted", "{actor} removed a publish gate of {component}"),
        )

    def capabilities(self) -> Iterable[CapabilityProbe]:
        return (CapabilityProbe("evals", "Evaluations (datasets, batches, version comparison)"),)
