"""Request and response bodies of ``/api/v1/instances/{instance}/approvals`` and ``/api/v1/approvals/routes``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_approvals.application.decide import DecideResult
from agnostic_approvals.application.inbox import Counts, Detail, InboxPage, Row
from agnostic_approvals.application.ports import Policy, RouteDraft
from agnostic_approvals.application.routing import RouteView

type StatusName = Literal["pending", "approved", "rejected", "expired", "cancelled"]
type PersonalChannelName = Literal["in_app", "email", "slack"]


class DecideIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000, description="Required to reject")
    edited_args: dict[str, Any] | None = Field(
        default=None, description="Replacement tool arguments (approve only); the change is audited as a diff"
    )


class DecideOut(BaseModel):
    approval_id: str
    instance_id: str
    decision: Literal["approve", "reject"]
    status: str = Field(description="approved, rejected, or what someone else decided first")
    run_id: str | None
    session_id: str | None
    continue_state: Literal["continued", "pending_admin", "conflict", "failed", "skipped"]
    continue_detail: str | None
    already_resolved: bool
    args_changed: list[str]

    @classmethod
    def from_result(cls, result: DecideResult) -> DecideOut:
        return cls(
            approval_id=result.approval_id,
            instance_id=result.instance_id,
            decision=result.decision,
            status=result.status,
            run_id=result.run_id,
            session_id=result.session_id,
            continue_state=result.continue_state,
            continue_detail=result.continue_detail,
            already_resolved=result.already_resolved,
            args_changed=list(result.args_changed),
        )


class CountOut(BaseModel):
    instance_id: str
    count: int | None = Field(description="None when the instance has approvals disabled or didn't answer")
    available: bool


class ApprovalOut(BaseModel):
    id: str
    tool_name: str | None
    type: Literal["blocking", "audit"]
    status: StatusName
    agentos_status: str
    expiry_enforced: bool = Field(description="Expired and acted on (run stopped), not just past its expiry")
    source_kind: Literal["agent", "team", "workflow", "schedule"] | None
    source_id: str | None
    source_name: str | None
    component_kind: Literal["agent", "team", "workflow"] | None
    component_id: str | None
    user_id: str | None
    user_name: str | None
    via: str | None
    session_id: str | None
    run_id: str | None
    schedule_id: str | None
    created_at: datetime | None
    expires_at: datetime | None
    expiry_source: Literal["approval", "step_timeout", "ttl"] | None
    resolved_at: datetime | None
    resolved_by: str | None
    resolved_by_name: str | None
    note: str | None
    args_changed: list[str]

    @classmethod
    def of(cls, row: Row) -> ApprovalOut:
        record = row.record
        source = record.source
        component = record.component
        diff = record.resolution_data.get("diff")
        return cls(
            id=record.id,
            tool_name=record.tool_name,
            type=record.kind,
            status=row.status,
            agentos_status=record.status,
            expiry_enforced=row.enforced,
            source_kind=source[0] if source else None,
            source_id=(
                record.schedule_id if source and source[0] == "schedule" else component[1] if component else None
            ),
            source_name=source[1] if source else None,
            component_kind=component[0] if component else None,
            component_id=component[1] if component else None,
            user_id=record.user_id,
            user_name=row.user_name,
            via="scheduler" if record.schedule_id else None,
            session_id=record.session_id,
            run_id=record.run_id,
            schedule_id=record.schedule_id,
            created_at=record.created_at,
            expires_at=row.expiry.at,
            expiry_source=row.expiry.source,
            resolved_at=record.resolved_at,
            resolved_by=record.resolved_by,
            resolved_by_name=row.resolver_name,
            note=str(record.resolution_data["note"]) if record.resolution_data.get("note") else None,
            args_changed=sorted(diff) if isinstance(diff, dict) else [],  # pyright: ignore[reportUnknownArgumentType]
        )


class ApprovalsPageOut(BaseModel):
    data: list[ApprovalOut]
    page: int
    limit: int
    total: int
    truncated: bool = Field(description="Only the newest approvals were searched (see scan_limit)")
    oldest_pending_at: datetime | None

    @classmethod
    def of(cls, page: InboxPage) -> ApprovalsPageOut:
        return cls(
            data=[ApprovalOut.of(row) for row in page.rows],
            page=page.page,
            limit=page.limit,
            total=page.total,
            truncated=page.truncated,
            oldest_pending_at=page.oldest_pending_at,
        )


class ApprovalCountsOut(BaseModel):
    pending: int
    approved: int
    rejected: int
    expired: int
    cancelled: int
    truncated: bool

    @classmethod
    def of(cls, counts: Counts) -> ApprovalCountsOut:
        c = counts.counts
        return cls(
            pending=c["pending"],
            approved=c["approved"],
            rejected=c["rejected"],
            expired=c["expired"],
            cancelled=c["cancelled"],
            truncated=counts.truncated,
        )


class TimelineEntryOut(BaseModel):
    text: str
    at: datetime | None
    detail: str | None
    state: Literal["done", "now", "end"]


class ViewOut(BaseModel):
    user_id: str
    name: str
    at: datetime


class ContextOut(BaseModel):
    user_message: str | None
    agent_message: str | None


class PolicyOut(BaseModel):
    instance_id: str
    enforce_expiry: bool
    ttl_hours: int | None = Field(description="None: the org's approval_ttl_hours applies")
    updated_by: str | None
    updated_at: datetime | None

    @classmethod
    def of(cls, policy: Policy) -> PolicyOut:
        return cls(
            instance_id=policy.instance_id,
            enforce_expiry=policy.enforce_expiry,
            ttl_hours=policy.ttl_hours,
            updated_by=policy.updated_by,
            updated_at=policy.updated_at,
        )


class ApprovalDetailOut(ApprovalOut):
    tool_args: dict[str, Any]
    resolution_data: dict[str, Any]
    requirements: list[dict[str, Any]]
    context: ContextOut
    timeline: list[TimelineEntryOut]
    routed_to: list[str]
    channels: list[str]
    views: list[ViewOut]
    can_resolve: bool
    cannot_resolve_reason: str | None
    run_status: str | None
    user_isolation: bool | None
    elevation_enabled: bool
    policy: PolicyOut

    @classmethod
    def of_detail(cls, detail: Detail) -> ApprovalDetailOut:
        base = ApprovalOut.of(detail.row).model_dump()
        record = detail.row.record
        return cls(
            **base,
            tool_args=dict(record.tool_args),
            resolution_data=dict(record.resolution_data),
            requirements=[dict(item) for item in record.requirements],
            context=ContextOut(user_message=detail.context.user_message, agent_message=detail.context.agent_message),
            timeline=[TimelineEntryOut(text=e.text, at=e.at, detail=e.detail, state=e.state) for e in detail.timeline],
            routed_to=detail.routed_to,
            channels=detail.channels,
            views=[ViewOut(user_id=v.user_id, name=v.name, at=v.at) for v in detail.views],
            can_resolve=detail.can_resolve,
            cannot_resolve_reason=detail.cannot_resolve_reason,
            run_status=detail.run_status,
            user_isolation=detail.instance.user_isolation,
            elevation_enabled=detail.instance.elevation_enabled,
            policy=PolicyOut.of(detail.policy),
        )


class RouteIn(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Billing ops"])
    tool_name: str | None = Field(default=None, max_length=200, description="Empty: every tool")
    component_kind: Literal["agent", "team", "workflow"] | None = None
    component_ids: list[str] = Field(default_factory=list, max_length=100)
    member_ids: list[str] = Field(default_factory=list, max_length=200)
    role_ids: list[str] = Field(default_factory=list, max_length=50)
    group_ids: list[str] = Field(default_factory=list, max_length=50)
    channels: list[PersonalChannelName] = Field(default_factory=lambda: ["in_app"])
    channel_ids: list[str] = Field(default_factory=list, max_length=20, description="Org notification channels")

    def draft(self, instance_id: str | None = None) -> RouteDraft:
        return RouteDraft(
            name=self.name,
            instance_id=instance_id,
            tool_name=self.tool_name or None,
            component_kind=self.component_kind,
            component_ids=tuple(self.component_ids),
            member_ids=tuple(self.member_ids),
            role_ids=tuple(self.role_ids),
            group_ids=tuple(self.group_ids),
            channels=tuple(self.channels),
            channel_ids=tuple(self.channel_ids),
        )


class NamedRef(BaseModel):
    id: str
    name: str


class RouteOut(BaseModel):
    id: str
    instance_id: str | None
    name: str
    tool_name: str | None
    component_kind: Literal["agent", "team", "workflow"] | None
    component_ids: list[str]
    members: list[NamedRef]
    roles: list[NamedRef]
    groups: list[NamedRef] = Field(default_factory=list[NamedRef])
    channels: list[PersonalChannelName]
    channel_ids: list[str]
    created_by: str | None
    updated_at: datetime

    @classmethod
    def of(cls, view: RouteView) -> RouteOut:
        route = view.route
        return cls(
            id=route.id,
            instance_id=route.instance_id,
            name=route.name,
            tool_name=route.tool_name,
            component_kind=route.component_kind,
            component_ids=list(route.component_ids),
            members=[NamedRef(id=k, name=v) for k, v in view.member_names.items()],
            roles=[NamedRef(id=k, name=v) for k, v in view.role_names.items()],
            groups=[NamedRef(id=k, name=v) for k, v in view.group_names.items()],
            channels=list(route.channels),  # pyright: ignore[reportArgumentType]
            channel_ids=list(route.channel_ids),
            created_by=route.created_by,
            updated_at=route.updated_at,
        )


class PolicyIn(BaseModel):
    enforce_expiry: bool
    ttl_hours: int | None = Field(default=None, ge=0, le=720, description="None: use the org's approval_ttl_hours")
