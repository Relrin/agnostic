"""Module declaration: the durable queue over AgentOS ``/queue/*`` with delegated elevation."""

from __future__ import annotations

from collections.abc import Iterable

from dishka import Provider

from agnostic_kernel.modules import AuditActionDecl, BaseModule, CapabilityProbe, RouterSpec
from agnostic_queue.api.router import router
from agnostic_queue.providers import QueueProvider


class QueueModule(BaseModule):
    name = "queue"
    version = "0.2.0"
    depends_on = ("access", "audit", "instances", "gateway")

    def provide(self) -> Iterable[Provider]:
        return (QueueProvider(),)

    def routers(self) -> Iterable[RouterSpec]:
        return (RouterSpec(router=router, prefix="/instances", tags=("queue",)),)

    def audit_actions(self) -> Iterable[AuditActionDecl]:
        return (
            AuditActionDecl("queue.resume", "{actor} resumed {run} ({component}) from a checkpoint on {instance}"),
            AuditActionDecl("queue.requeue", "{actor} requeued {run} ({component}) on {instance}"),
            AuditActionDecl("queue.cancel", "{actor} cancelled {run} ({component}) on {instance}"),
        )

    def capabilities(self) -> Iterable[CapabilityProbe]:
        return (CapabilityProbe("durable_queue", "Durable background runs with checkpoints"),)
