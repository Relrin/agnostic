"""What the approvals use cases need from storage: routes, views, events and per-instance policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from agnostic_approvals.domain.inbox import ApprovalEvent, Route

type ComponentKind = Literal["agent", "team", "workflow"]


@dataclass(frozen=True, slots=True)
class RouteDraft:
    name: str
    instance_id: str | None
    tool_name: str | None = None
    component_kind: ComponentKind | None = None
    component_ids: tuple[str, ...] = ()
    member_ids: tuple[str, ...] = ()
    role_ids: tuple[str, ...] = ()
    channels: tuple[str, ...] = ("in_app",)
    channel_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Policy:
    instance_id: str
    enforce_expiry: bool = False
    """After the effective expiry the control plane stops the run (workflows: AgentOS ``on_timeout``)."""
    ttl_hours: int | None = None
    """Overrides the org's ``approval_ttl_hours`` on this instance (``None``: use the org's)."""
    updated_by: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredView:
    user_id: str
    viewed_at: datetime


class ApprovalStore(Protocol):
    async def routes(self, instance_id: str | None, *, include_org: bool = True) -> list[Route]:
        """Routes of an instance (plus org-wide ones), or only org-wide ones with ``instance_id=None``."""
        ...

    async def route(self, route_id: str) -> Route | None: ...
    async def add_route(self, draft: RouteDraft, *, created_by: str) -> Route: ...
    async def update_route(self, route_id: str, draft: RouteDraft) -> Route: ...
    async def delete_route(self, route_id: str) -> None: ...

    async def record_view(self, instance_id: str, approval_id: str, user_id: str) -> bool:
        """True when this is the person's first view of the approval."""
        ...

    async def views(self, instance_id: str, approval_id: str) -> list[StoredView]: ...

    async def add_event(
        self,
        instance_id: str,
        approval_id: str,
        kind: str,
        detail: Mapping[str, Any],
        *,
        actor: str | None = None,
    ) -> None: ...
    async def events(self, instance_id: str, approval_id: str) -> list[ApprovalEvent]: ...
    async def event_kinds(self, instance_id: str, approval_ids: Sequence[str]) -> dict[str, set[str]]:
        """Approval id → the event kinds already recorded (what the watcher has done)."""
        ...

    async def policy(self, instance_id: str) -> Policy: ...
    async def set_policy(self, policy: Policy) -> Policy: ...
    async def commit(self) -> None: ...
