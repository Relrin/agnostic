"""The approvals inbox: tabs with counts, filtered lists, and one approval with its context and timeline.

AgentOS filters by status, type, source and user but not by tool or free text, and knows nothing about expiry; the
inbox scans a bounded window of the newest approvals (``scan_limit``) and filters the rest itself. Lists say when
the window cut them short.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from agnostic_access.facade import AccessFacade
from agnostic_approvals.application.ports import ApprovalStore, Policy
from agnostic_approvals.application.reader import ApprovalsReader
from agnostic_approvals.domain.inbox import (
    ApprovalEvent,
    ApprovalRecord,
    ContextExcerpt,
    DisplayStatus,
    Expiry,
    TimelineEntry,
    View,
    context_excerpt,
    display_status,
    effective_expiry,
    expired_by_agnostic,
    search_matches,
    timeline,
)
from agnostic_gateway.facade import GatewayFacade
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError, ValidationFailedError
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_settings.facade import OrgSettingsReader

READ = "approvals:read"
WRITE = "approvals:write"
EPOCH = datetime.min.replace(tzinfo=UTC)
SOURCE_PARAMS = {"agent": "agent_id", "team": "team_id", "workflow": "workflow_id", "schedule": "schedule_id"}


@dataclass(frozen=True, slots=True)
class Filters:
    status: DisplayStatus = "pending"
    tool: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    user_id: str | None = None
    schedule_id: str | None = None
    kind: str | None = None
    """``blocking`` or ``audit``."""
    q: str | None = None

    def agentos(self) -> dict[str, str | int]:
        params: dict[str, str | int] = {}
        if self.source_kind and self.source_id:
            if self.source_kind not in SOURCE_PARAMS:
                raise ValidationFailedError("source_kind must be agent, team, workflow or schedule.")
            params[SOURCE_PARAMS[self.source_kind]] = self.source_id
        if self.user_id:
            params["user_id"] = self.user_id
        if self.schedule_id:
            params["schedule_id"] = self.schedule_id
        if self.kind:
            params["approval_type"] = "audit" if self.kind == "audit" else "required"
        return params


@dataclass(frozen=True, slots=True)
class Row:
    record: ApprovalRecord
    status: DisplayStatus
    expiry: Expiry
    enforced: bool
    user_name: str | None
    resolver_name: str | None


@dataclass(frozen=True, slots=True)
class InboxPage:
    rows: list[Row]
    page: int
    limit: int
    total: int
    truncated: bool
    oldest_pending_at: datetime | None


@dataclass(frozen=True, slots=True)
class Counts:
    counts: dict[DisplayStatus, int]
    truncated: bool


@dataclass(frozen=True, slots=True)
class Detail:
    row: Row
    instance: Instance
    context: ContextExcerpt
    timeline: list[TimelineEntry]
    routed_to: list[str]
    channels: list[str]
    views: list[View]
    can_resolve: bool
    cannot_resolve_reason: str | None
    run_status: str | None
    policy: Policy
    events: list[ApprovalEvent] = field(default_factory=list[ApprovalEvent])


def resolver_id(record: ApprovalRecord) -> str | None:
    """AgentOS stores the JWT subject; decisions made in Agnostic also say ``Name (usr_…)``."""
    value = record.resolved_by
    if not value:
        return None
    if value.endswith(")") and "(" in value:
        return value[value.rindex("(") + 1 : -1]
    return value


class ApprovalsInbox:
    def __init__(
        self,
        gateway: GatewayFacade,
        authorizer: Authorizer,
        reader: ApprovalsReader,
        store: ApprovalStore,
        identity: IdentityFacade,
        access: AccessFacade,
        settings: OrgSettingsReader,
        bus: EventBus,
        scan_limit: int,
    ) -> None:
        self._gateway = gateway
        self._authorizer = authorizer
        self._reader = reader
        self._store = store
        self._identity = identity
        self._access = access
        self._settings = settings
        self._bus = bus
        self._scan_limit = scan_limit

    async def instance(self, principal: Principal, ref: str, scope: str = READ) -> Instance:
        instance = await self._gateway.instance(ref)
        _ = await self._authorizer.require(principal, scope, instance_id=instance.id)
        return instance

    async def ttl_hours(self, instance_id: str) -> tuple[int, Policy]:
        policy = await self._store.policy(instance_id)
        ttl = policy.ttl_hours if policy.ttl_hours is not None else (await self._settings.get()).approval_ttl_hours
        return ttl, policy

    async def _names(self, records: Sequence[ApprovalRecord]) -> dict[str, str]:
        ids = {record.user_id for record in records if record.user_id}
        ids |= {rid for record in records if (rid := resolver_id(record))}
        return {user.id: user.display_name for user in await self._identity.get_users(sorted(ids))}

    async def rows(self, instance: Instance, records: Sequence[ApprovalRecord]) -> list[Row]:
        ttl, _ = await self.ttl_hours(instance.id)
        names = await self._names(records)
        pending = [record.id for record in records if record.status == "pending"]
        kinds = await self._store.event_kinds(instance.id, pending) if pending else {}
        now = utcnow()
        rows: list[Row] = []
        for record in records:
            expiry = effective_expiry(record, ttl)
            enforced = "expired" in kinds.get(record.id, set())
            resolver = resolver_id(record)
            rows.append(
                Row(
                    record=record,
                    status=display_status(record, expiry, now, enforced=enforced),
                    expiry=expiry,
                    enforced=enforced or expired_by_agnostic(record),
                    user_name=names.get(record.user_id or ""),
                    resolver_name=names.get(resolver or "")
                    or (record.resolved_by.split(" (")[0] if record.resolved_by else None),
                )
            )
        return rows

    async def _window(self, instance: Instance, filters: Filters) -> tuple[list[Row], bool]:
        """Every row of the tab (within the scan window), newest first."""
        statuses: tuple[str, ...] = {
            "pending": ("pending",),
            "expired": ("pending", "rejected"),
            "rejected": ("rejected",),
        }.get(filters.status, (filters.status,))
        records: list[ApprovalRecord] = []
        truncated = False
        for status in statuses:
            found, more = await self._reader.scan(instance, {**filters.agentos(), "status": status}, self._scan_limit)
            records.extend(found)
            truncated = truncated or more
        rows = [row for row in await self.rows(instance, records) if row.status == filters.status]
        names = {row.record.user_id or "": row.user_name or "" for row in rows}
        if filters.tool:
            rows = [row for row in rows if row.record.tool_name == filters.tool]
        if filters.q:
            rows = [row for row in rows if search_matches(row.record, filters.q, names)]
        rows.sort(key=lambda row: row.record.created_at or EPOCH, reverse=True)
        return rows, truncated

    async def list(self, principal: Principal, ref: str, filters: Filters, *, page: int, limit: int) -> InboxPage:
        instance = await self.instance(principal, ref)
        rows, truncated = await self._window(instance, filters)
        start = (page - 1) * limit
        oldest = min((row.record.created_at for row in rows if row.record.created_at), default=None)
        return InboxPage(
            rows=rows[start : start + limit],
            page=page,
            limit=limit,
            total=len(rows),
            truncated=truncated,
            oldest_pending_at=oldest if filters.status == "pending" else None,
        )

    async def counts(self, principal: Principal, ref: str) -> Counts:
        instance = await self.instance(principal, ref)
        pending, more_pending = await self._reader.scan(instance, {"status": "pending"}, self._scan_limit)
        rejected, more_rejected = await self._reader.scan(instance, {"status": "rejected"}, self._scan_limit)
        rows = await self.rows(instance, [*pending, *rejected])
        counts: dict[DisplayStatus, int] = {
            "pending": sum(1 for row in rows if row.status == "pending"),
            "rejected": sum(1 for row in rows if row.status == "rejected"),
            "expired": sum(1 for row in rows if row.status == "expired"),
            "approved": await self._reader.total(instance, {"status": "approved"}),
            "cancelled": await self._reader.total(instance, {"status": "cancelled"}),
        }
        if more_pending:
            counts["pending"] += await self._reader.total(instance, {"status": "pending"}) - len(pending)
        if more_rejected:
            counts["rejected"] += await self._reader.total(instance, {"status": "rejected"}) - len(rejected)
        return Counts(counts=counts, truncated=more_pending or more_rejected)

    async def detail(self, principal: Principal, ref: str, approval_id: str) -> Detail:
        instance = await self.instance(principal, ref)
        record = await self._reader.get(instance, approval_id)
        if record is None:
            raise NotFoundError(f"Approval {approval_id} doesn't exist on {instance.display_name}.")
        row = (await self.rows(instance, [record]))[0]
        if await self._store.record_view(instance.id, record.id, principal.id):
            await self._store.commit()
            await self._bus.publish(
                instance_channel(instance.id),
                RealtimeEvent(
                    "approval.viewed",
                    {"approval_id": record.id, "user_id": principal.id, "name": principal.display_name},
                    instance_id=instance.id,
                ),
            )
        stored_views = await self._store.views(instance.id, record.id)
        names = {u.id: u.display_name for u in await self._identity.get_users([v.user_id for v in stored_views])}
        views = [View(v.user_id, names.get(v.user_id, v.user_id), v.viewed_at) for v in stored_views]
        events = await self._store.events(instance.id, record.id)
        routed = next((event for event in events if event.kind == "routed"), None)
        run = await self._reader.run(instance, record)
        run_status = str(run.get("status")) if run and run.get("status") else record.run_status
        _, policy = await self.ttl_hours(instance.id)

        can, reason = True, None
        if row.status != "pending":
            can, reason = False, None
        elif record.kind == "audit":
            can, reason = False, "Audit approvals never block the run: they are records, not requests."
        elif not (await self._authorizer.check(principal, WRITE, instance_id=instance.id)).allowed:
            can, reason = False, f"Resolving needs approvals:write on {instance.display_name}."
        elif not instance.elevation_enabled:
            can, reason = (
                False,
                (
                    f"Delegated elevation is off on {instance.display_name}: only an Instance admin can resolve "
                    "approvals there, from the instance itself."
                ),
            )
        return Detail(
            row=row,
            instance=instance,
            context=context_excerpt(run),
            timeline=timeline(
                record,
                status=row.status,
                expiry=row.expiry,
                events=events,
                views=views,
                resolver_name=row.resolver_name,
                run_status=run_status if row.status in {"approved", "rejected"} else None,
            ),
            routed_to=[str(name) for name in cast("list[object]", routed.detail.get("routed_to") or [])]
            if routed
            else [],
            channels=[str(name) for name in cast("list[object]", routed.detail.get("channels") or [])]
            if routed
            else [],
            views=views,
            can_resolve=can,
            cannot_resolve_reason=reason,
            run_status=run_status,
            policy=policy,
            events=events,
        )

    async def role_names(self) -> Mapping[str, str]:
        return await self._access.role_names()
