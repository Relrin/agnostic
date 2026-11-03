"""Saved views (named filter sets) and the translation between stored filters and event queries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from agnostic_audit.application.ports import AuditRepository, EventQuery, UnitOfWork, ViewRepository
from agnostic_audit.domain.governance import VIEW_COUNT_CAP, VIEW_ID_PREFIX, SavedView, clean_filters
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError, ScopeMissingError, ValidationFailedError
from agnostic_kernel.ids import new_id

_DECISIONS = ("allowed", "denied", "n_a")
_ACTOR_KINDS = ("user", "service_account", "system", "anonymous")
_SOURCES = ("control_plane", "agentos")
SHARED_VIEW_SCOPES = ("audit:export", "org:write")
"""Holding either lets someone create, change and delete shared views (exporters and org admins)."""


def _time(value: str | None, key: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValidationFailedError(f"{key} must be an ISO 8601 time.") from exc


def query_from_filters(filters: Mapping[str, Any]) -> EventQuery:
    """Stored filters (a saved view's, an export's) → a query; unknown values are rejected, not ignored."""
    values = clean_filters(filters)
    decision = values.get("decision")
    if decision is not None and decision not in _DECISIONS:
        raise ValidationFailedError(f"decision must be one of {', '.join(_DECISIONS)}.")
    actor_kind = values.get("actor_kind")
    if actor_kind is not None and actor_kind not in _ACTOR_KINDS:
        raise ValidationFailedError(f"actor_kind must be one of {', '.join(_ACTOR_KINDS)}.")
    source = values.get("source")
    if source is not None and source not in _SOURCES:
        raise ValidationFailedError(f"source must be one of {', '.join(_SOURCES)}.")
    return EventQuery(
        actor_id=values.get("actor"),
        actor_kind=actor_kind,
        action=values.get("action"),
        decision=decision,
        instance_id=values.get("instance"),
        resource_id=values.get("resource"),
        source=source,
        q=values.get("q"),
        since=_time(values.get("since"), "since"),
        until=_time(values.get("until"), "until"),
    )


def filters_from_query(query: EventQuery) -> dict[str, str]:
    return clean_filters(
        {
            "q": query.q,
            "actor": query.actor_id,
            "actor_kind": query.actor_kind,
            "action": query.action,
            "decision": query.decision,
            "instance": query.instance_id,
            "resource": query.resource_id,
            "source": query.source,
            "since": query.since.isoformat() if query.since else None,
            "until": query.until.isoformat() if query.until else None,
        }
    )


@dataclass(frozen=True, slots=True)
class CountedView:
    view: SavedView
    count: int
    count_capped: bool
    editable: bool


class SavedViews:
    def __init__(self, views: ViewRepository, events: AuditRepository, uow: UnitOfWork, authorizer: Authorizer) -> None:
        self._views = views
        self._events = events
        self._uow = uow
        self._authorizer = authorizer

    async def manages_shared(self, principal: Principal) -> bool:
        for scope in SHARED_VIEW_SCOPES:
            if (await self._authorizer.check(principal, scope)).allowed:
                return True
        return False

    async def _counted(self, view: SavedView, editable: bool) -> CountedView:
        count = await self._events.count(query_from_filters(view.filters), VIEW_COUNT_CAP + 1)
        return CountedView(
            view=view, count=min(count, VIEW_COUNT_CAP), count_capped=count > VIEW_COUNT_CAP, editable=editable
        )

    async def list(self, principal: Principal) -> list[CountedView]:
        shared_ok = await self.manages_shared(principal)
        return [
            await self._counted(view, editable=not view.shared or shared_ok)
            for view in await self._views.visible_to(principal.id)
        ]

    async def _editable(self, principal: Principal, view_id: str) -> SavedView:
        view = await self._views.get(view_id)
        if view is None or (view.owner_id is not None and view.owner_id != principal.id):
            raise NotFoundError(f"Saved view {view_id} doesn't exist.")
        if view.shared and not await self.manages_shared(principal):
            raise ScopeMissingError("Changing shared views needs audit:export or an org admin role.")
        return view

    async def create(
        self, principal: Principal, *, name: str, filters: Mapping[str, Any], shared: bool, position: int | None
    ) -> CountedView:
        if shared and not await self.manages_shared(principal):
            raise ScopeMissingError("Sharing a view needs audit:export or an org admin role.")
        cleaned = clean_filters(filters)
        _ = query_from_filters(cleaned)
        existing = await self._views.visible_to(principal.id)
        now = utcnow()
        view = SavedView(
            id=new_id(VIEW_ID_PREFIX),
            owner_id=None if shared else principal.id,
            name=name.strip(),
            filters=cleaned,
            position=position if position is not None else max((v.position for v in existing), default=-1) + 1,
            created_at=now,
            updated_at=now,
        )
        await self._views.save(view)
        await self._uow.commit()
        return await self._counted(view, editable=True)

    async def update(self, principal: Principal, view_id: str, changes: Mapping[str, Any]) -> CountedView:
        view = await self._editable(principal, view_id)
        if "name" in changes:
            view = replace(view, name=str(changes["name"]).strip())
        if "filters" in changes:
            cleaned = clean_filters(changes["filters"] or {})
            _ = query_from_filters(cleaned)
            view = replace(view, filters=cleaned)
        if "position" in changes:
            view = replace(view, position=int(changes["position"]))
        view = replace(view, updated_at=utcnow())
        await self._views.save(view)
        await self._uow.commit()
        return await self._counted(view, editable=True)

    async def delete(self, principal: Principal, view_id: str) -> None:
        view = await self._editable(principal, view_id)
        await self._views.delete(view.id)
        await self._uow.commit()
