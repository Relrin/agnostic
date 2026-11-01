"""SQLAlchemy persistence for audit events, and monthly partition maintenance on PostgreSQL."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agnostic_audit.application.ports import EventQuery
from agnostic_audit.domain.events import (
    Actor,
    ActorKind,
    AuditEvent,
    Decision,
    Source,
    partition_expired,
    partitions_to_create,
)
from agnostic_audit.infrastructure.tables import AuditEventRow
from agnostic_kernel.db import SCHEMA, aware

_PARTITIONS = text(
    "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits i "
    "JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent "
    "JOIN pg_namespace n ON n.oid = p.relnamespace WHERE p.relname = 'audit_events' AND n.nspname = :schema"
)


def _values(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at,
        "request_id": event.request_id,
        "actor_kind": event.actor.kind,
        "actor_id": event.actor.id,
        "actor_display": event.actor.display,
        "via": event.via,
        "ip": event.ip,
        "client": event.client,
        "action": event.action,
        "resource_kind": event.resource_kind,
        "resource_id": event.resource_id,
        "resource_display": event.resource_display,
        "instance_id": event.instance_id,
        "decision": event.decision,
        "scope_checked": event.scope_checked,
        "missing_scopes": list(event.missing_scopes) or None,
        "response_status": event.response_status,
        "summary": event.summary,
        "diff": dict(event.diff) if event.diff is not None else None,
        "links": dict(event.links) if event.links is not None else None,
        "source": event.source,
    }


def _to_domain(row: AuditEventRow) -> AuditEvent:
    return AuditEvent(
        id=row.id,
        occurred_at=aware(row.occurred_at),
        request_id=row.request_id,
        actor=Actor(kind=cast("ActorKind", row.actor_kind), id=row.actor_id, display=row.actor_display),
        via=row.via,
        ip=row.ip,
        client=row.client,
        action=row.action,
        resource_kind=row.resource_kind,
        resource_id=row.resource_id,
        resource_display=row.resource_display,
        instance_id=row.instance_id,
        decision=cast("Decision", row.decision),
        scope_checked=row.scope_checked,
        missing_scopes=tuple(row.missing_scopes or ()),
        response_status=row.response_status,
        summary=row.summary,
        diff=row.diff,
        links=row.links,
        source=cast("Source", row.source),
    )


class SqlAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: AuditEvent) -> None:
        # Core insert: audit rows are never loaded back into this unit of work or updated.
        _ = await self._session.execute(insert(AuditEventRow).values(**_values(event)))

    async def get(self, event_id: str) -> AuditEvent | None:
        row = await self._session.scalar(select(AuditEventRow).where(AuditEventRow.id == event_id))
        return _to_domain(row) if row else None

    async def list_page(
        self, query: EventQuery, limit: int, after: tuple[datetime, str] | None
    ) -> Sequence[AuditEvent]:
        statement = select(AuditEventRow).order_by(AuditEventRow.occurred_at.desc(), AuditEventRow.id.desc())
        if query.actor_id:
            statement = statement.where(AuditEventRow.actor_id == query.actor_id)
        if query.action:
            if query.action.endswith("*"):
                statement = statement.where(AuditEventRow.action.startswith(query.action[:-1], autoescape=True))
            else:
                statement = statement.where(AuditEventRow.action == query.action)
        if query.decision:
            statement = statement.where(AuditEventRow.decision == query.decision)
        if query.instance_id:
            statement = statement.where(AuditEventRow.instance_id == query.instance_id)
        if query.resource_id:
            statement = statement.where(AuditEventRow.resource_id == query.resource_id)
        if query.since:
            statement = statement.where(AuditEventRow.occurred_at >= query.since)
        if query.until:
            statement = statement.where(AuditEventRow.occurred_at < query.until)
        if after is not None:
            at, event_id = after
            statement = statement.where(
                or_(
                    AuditEventRow.occurred_at < at,
                    and_(AuditEventRow.occurred_at == at, AuditEventRow.id < event_id),
                )
            )
        rows = await self._session.scalars(statement.limit(limit))
        return [_to_domain(row) for row in rows]


class SqlStandaloneAuditWriter:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def write(self, event: AuditEvent) -> None:
        async with self._sessionmaker.begin() as session:
            _ = await session.execute(insert(AuditEventRow).values(**_values(event)))


class SqlPartitionMaintenance:
    """Creates upcoming monthly partitions and drops expired ones (PostgreSQL); deletes old rows on SQLite."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ensure_partitions(self, now: datetime, months_ahead: int) -> list[str]:
        if self._engine.dialect.name != "postgresql":
            return []
        created: list[str] = []
        async with self._engine.begin() as connection:
            existing = {str(name) for name, _ in await connection.execute(_PARTITIONS, {"schema": SCHEMA})}
            for name, start, end in partitions_to_create(now, months_ahead):
                if name in existing:
                    continue
                _ = await connection.execute(
                    text(
                        f"CREATE TABLE {SCHEMA}.{name} PARTITION OF {SCHEMA}.audit_events "
                        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
                    )
                )
                created.append(name)
        return created

    async def drop_expired(self, now: datetime, retention_days: int) -> list[str]:
        if self._engine.dialect.name != "postgresql":
            async with self._engine.begin() as connection:
                _ = await connection.execute(
                    delete(AuditEventRow).where(AuditEventRow.occurred_at < now - timedelta(days=retention_days))
                )
            return []
        dropped: list[str] = []
        async with self._engine.begin() as connection:
            for name, bound in await connection.execute(_PARTITIONS, {"schema": SCHEMA}):
                upper = upper_bound(str(bound))
                if upper is not None and partition_expired(upper, now, retention_days):
                    _ = await connection.execute(text(f"DROP TABLE {SCHEMA}.{name}"))
                    dropped.append(str(name))
        return dropped


def upper_bound(bound: str) -> datetime | None:
    """``FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00')`` → the TO value."""
    marker = "TO ('"
    if marker not in bound:
        return None  # the DEFAULT partition
    value = bound.split(marker, 1)[1].split("'", 1)[0]
    return aware(datetime.fromisoformat(value))
