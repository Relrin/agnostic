"""SQL repository of the approvals module."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_approvals.application.ports import Policy, RouteDraft, StoredView
from agnostic_approvals.domain.inbox import ApprovalEvent, Route
from agnostic_approvals.infrastructure.tables import EventRow, PolicyRow, RouteRow, ViewRow
from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.ids import new_id


def _route(row: RouteRow) -> Route:
    return Route(
        id=row.id,
        instance_id=row.instance_id,
        name=row.name,
        tool_name=row.tool_name,
        component_kind=cast("Any", row.component_kind),
        component_ids=tuple(row.component_ids or ()),
        member_ids=tuple(row.member_ids or ()),
        role_ids=tuple(row.role_ids or ()),
        group_ids=tuple(row.group_ids or ()),
        channels=tuple(row.channels or ()),
        channel_ids=tuple(row.channel_ids or ()),
        created_by=row.created_by,
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
    )


def _apply(row: RouteRow, draft: RouteDraft) -> None:
    row.name = draft.name
    row.instance_id = draft.instance_id
    row.tool_name = draft.tool_name
    row.component_kind = draft.component_kind
    row.component_ids = list(draft.component_ids)
    row.member_ids = list(draft.member_ids)
    row.role_ids = list(draft.role_ids)
    row.group_ids = list(draft.group_ids)
    row.channels = list(draft.channels)
    row.channel_ids = list(draft.channel_ids)


class SqlApprovalStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def routes(self, instance_id: str | None, *, include_org: bool = True) -> list[Route]:
        query = select(RouteRow)
        if instance_id is None:
            query = query.where(RouteRow.instance_id.is_(None))
        elif include_org:
            query = query.where(or_(RouteRow.instance_id == instance_id, RouteRow.instance_id.is_(None)))
        else:
            query = query.where(RouteRow.instance_id == instance_id)
        rows = (await self._session.scalars(query.order_by(RouteRow.name, RouteRow.id))).all()
        return [_route(row) for row in rows]

    async def all_routes(self) -> list[Route]:
        rows = (await self._session.scalars(select(RouteRow).order_by(RouteRow.name, RouteRow.id))).all()
        return [_route(row) for row in rows]

    async def route(self, route_id: str) -> Route | None:
        row = await self._session.get(RouteRow, route_id)
        return _route(row) if row is not None else None

    async def add_route(self, draft: RouteDraft, *, created_by: str) -> Route:
        now = utcnow()
        row = RouteRow(id=new_id("art"), created_by=created_by, created_at=now, updated_at=now)
        _apply(row, draft)
        self._session.add(row)
        await self._session.flush()
        return _route(row)

    async def update_route(self, route_id: str, draft: RouteDraft) -> Route:
        row = await self._session.get(RouteRow, route_id)
        if row is None:
            raise NotFoundError(f"There is no approval route {route_id!r}.")
        _apply(row, draft)
        row.updated_at = utcnow()
        await self._session.flush()
        return _route(row)

    async def delete_route(self, route_id: str) -> None:
        _ = await self._session.execute(delete(RouteRow).where(RouteRow.id == route_id))

    async def record_view(self, instance_id: str, approval_id: str, user_id: str) -> bool:
        if await self._session.get(ViewRow, (instance_id, approval_id, user_id)) is not None:
            return False
        self._session.add(
            ViewRow(instance_id=instance_id, approval_id=approval_id, user_id=user_id, viewed_at=utcnow())
        )
        await self._session.flush()
        return True

    async def views(self, instance_id: str, approval_id: str) -> list[StoredView]:
        query = (
            select(ViewRow)
            .where(ViewRow.instance_id == instance_id, ViewRow.approval_id == approval_id)
            .order_by(ViewRow.viewed_at)
        )
        return [StoredView(row.user_id, aware(row.viewed_at)) for row in (await self._session.scalars(query)).all()]

    async def add_event(
        self,
        instance_id: str,
        approval_id: str,
        kind: str,
        detail: Mapping[str, Any],
        *,
        actor: str | None = None,
    ) -> None:
        self._session.add(
            EventRow(
                id=new_id("aev"),
                instance_id=instance_id,
                approval_id=approval_id,
                kind=kind,
                detail=dict(detail),
                actor=actor,
                at=utcnow(),
            )
        )
        await self._session.flush()

    async def events(self, instance_id: str, approval_id: str) -> list[ApprovalEvent]:
        query = (
            select(EventRow)
            .where(EventRow.instance_id == instance_id, EventRow.approval_id == approval_id)
            .order_by(EventRow.at, EventRow.id)
        )
        return [
            ApprovalEvent(kind=row.kind, at=aware(row.at), detail=dict(row.detail or {}), actor=row.actor)
            for row in (await self._session.scalars(query)).all()
        ]

    async def event_kinds(self, instance_id: str, approval_ids: Sequence[str]) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        ids = list(approval_ids)
        for start in range(0, len(ids), 500):
            query = select(EventRow.approval_id, EventRow.kind).where(
                EventRow.instance_id == instance_id, EventRow.approval_id.in_(ids[start : start + 500])
            )
            for approval_id, kind in (await self._session.execute(query)).all():
                found.setdefault(approval_id, set()).add(kind)
        return found

    async def policy(self, instance_id: str) -> Policy:
        row = await self._session.get(PolicyRow, instance_id)
        if row is None:
            return Policy(instance_id=instance_id)
        return Policy(
            instance_id=instance_id,
            enforce_expiry=row.enforce_expiry,
            ttl_hours=row.ttl_hours,
            updated_by=row.updated_by,
            updated_at=aware_or_none(row.updated_at),
        )

    async def set_policy(self, policy: Policy) -> Policy:
        row = await self._session.get(PolicyRow, policy.instance_id)
        if row is None:
            row = PolicyRow(instance_id=policy.instance_id)
            self._session.add(row)
        row.enforce_expiry = policy.enforce_expiry
        row.ttl_hours = policy.ttl_hours
        row.updated_by = policy.updated_by
        row.updated_at = utcnow()
        await self._session.flush()
        return await self.policy(policy.instance_id)

    async def commit(self) -> None:
        await self._session.commit()
