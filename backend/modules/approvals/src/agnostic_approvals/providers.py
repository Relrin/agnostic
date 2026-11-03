"""Dependency wiring of the approvals module."""

from __future__ import annotations

from datetime import timedelta

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_access.facade import AccessFacade
from agnostic_approvals.application.decide import DecideApproval
from agnostic_approvals.application.inbox import ApprovalsInbox
from agnostic_approvals.application.poller import ApprovalsCountPoller
from agnostic_approvals.application.ports import ApprovalStore
from agnostic_approvals.application.reader import ApprovalsReader
from agnostic_approvals.application.routing import ApprovalRouting
from agnostic_approvals.application.watch import WatchApprovals
from agnostic_approvals.infrastructure.repository import SqlApprovalStore
from agnostic_approvals.settings import ApprovalsSettings
from agnostic_audit.facade import AuditLog
from agnostic_gateway.facade import GatewayFacade
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Authorizer
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus
from agnostic_notifications.facade import Notifier
from agnostic_settings.facade import OrgSettingsReader


class ApprovalsProvider(Provider):
    scope = Scope.REQUEST

    reader = provide(ApprovalsReader)
    routing = provide(ApprovalRouting)

    @provide
    def store(self, session: AsyncSession) -> ApprovalStore:
        return SqlApprovalStore(session)

    @provide
    def decide(
        self,
        gateway: GatewayFacade,
        audit: AuditLog,
        store: EphemeralStore,
        bus: EventBus,
        settings: ApprovalsSettings,
        approvals: ApprovalStore,
        notifier: Notifier,
    ) -> DecideApproval:
        return DecideApproval(gateway, audit, store, bus, settings.continue_retry_delays, approvals, notifier)

    @provide
    def poller(
        self, instances: InstancesFacade, store: EphemeralStore, bus: EventBus, settings: ApprovalsSettings
    ) -> ApprovalsCountPoller:
        return ApprovalsCountPoller(instances, store, bus, settings.poll_seconds or 15.0)

    @provide
    def inbox(
        self,
        gateway: GatewayFacade,
        authorizer: Authorizer,
        reader: ApprovalsReader,
        store: ApprovalStore,
        identity: IdentityFacade,
        access: AccessFacade,
        org: OrgSettingsReader,
        bus: EventBus,
        settings: ApprovalsSettings,
    ) -> ApprovalsInbox:
        return ApprovalsInbox(gateway, authorizer, reader, store, identity, access, org, bus, settings.scan_limit)

    @provide
    def watch(
        self,
        instances: InstancesFacade,
        reader: ApprovalsReader,
        store: ApprovalStore,
        routing: ApprovalRouting,
        notifier: Notifier,
        org: OrgSettingsReader,
        audit: AuditLog,
        bus: EventBus,
        ephemeral: EphemeralStore,
        settings: ApprovalsSettings,
    ) -> WatchApprovals:
        return WatchApprovals(
            instances,
            reader,
            store,
            routing,
            notifier,
            org,
            audit,
            bus,
            ephemeral,
            scan_limit=settings.scan_limit,
            expiring_lead=timedelta(minutes=settings.expiring_lead_minutes),
            retry_delays=tuple(settings.continue_retry_delays),
        )
