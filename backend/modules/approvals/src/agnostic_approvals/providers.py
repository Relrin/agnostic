"""Dependency wiring of the approvals module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_approvals.application.decide import DecideApproval
from agnostic_approvals.application.poller import ApprovalsCountPoller
from agnostic_approvals.settings import ApprovalsSettings
from agnostic_audit.facade import AuditLog
from agnostic_gateway.facade import GatewayFacade
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus


class ApprovalsProvider(Provider):
    scope = Scope.REQUEST

    @provide
    def decide(
        self,
        gateway: GatewayFacade,
        audit: AuditLog,
        store: EphemeralStore,
        bus: EventBus,
        settings: ApprovalsSettings,
    ) -> DecideApproval:
        return DecideApproval(gateway, audit, store, bus, settings.continue_retry_delays)

    @provide
    def poller(
        self, instances: InstancesFacade, store: EphemeralStore, bus: EventBus, settings: ApprovalsSettings
    ) -> ApprovalsCountPoller:
        return ApprovalsCountPoller(instances, store, bus, settings.poll_seconds or 15.0)
