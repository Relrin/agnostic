"""SQLAlchemy persistence for audit events, and monthly partition maintenance on PostgreSQL."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import ColumnElement, Select, Text, and_, delete, func, insert, literal_column, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from agnostic_audit.application.ports import ActorSummary, EventQuery, Position
from agnostic_audit.domain.archive import month_bounds, month_key
from agnostic_audit.domain.chain import chain_hash
from agnostic_audit.domain.events import (
    Actor,
    ActorKind,
    AuditEvent,
    Decision,
    Source,
    month_start,
    next_month,
    partition_expired,
    partition_name,
    partitions_to_create,
)
from agnostic_audit.infrastructure.tables import AuditEventRow
from agnostic_kernel.db import SCHEMA, aware, utcnow

_PARTITIONS = text(
    "SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) FROM pg_inherits i "
    "JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent "
    "JOIN pg_namespace n ON n.oid = p.relnamespace WHERE p.relname = 'audit_events' AND n.nspname = :schema"
)
CHAIN_LOCK_KEY = 0x6175646974636861
"""``pg_advisory_xact_lock`` key that serialises hash-chain writers ("auditcha")."""

type Executor = AsyncSession | AsyncConnection


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
        "source_event_id": event.source_event_id,
        "prev_hash": event.prev_hash,
        "hash": event.hash,
        "denial_reason": event.denial_reason,
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
        denial_reason=row.denial_reason,
        source_event_id=row.source_event_id,
        prev_hash=row.prev_hash,
        hash=row.hash,
    )


async def _linked(executor: Executor, dialect: str, event: AuditEvent) -> AuditEvent:
    """Link ``event`` after the newest chained event.

    On PostgreSQL the transaction lock serialises chain writers until the caller commits; the event's time is taken
    under the lock, so chain order is time order.
    """
    if dialect == "postgresql":
        _ = await executor.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK_KEY})
    last = (
        await executor.execute(
            select(AuditEventRow.hash, AuditEventRow.occurred_at)
            .where(AuditEventRow.hash.is_not(None))
            .order_by(AuditEventRow.occurred_at.desc(), AuditEventRow.id.desc())
            .limit(1)
        )
    ).first()
    at = utcnow()
    if last is not None and aware(last.occurred_at) >= at:
        at = aware(last.occurred_at) + timedelta(microseconds=1)
    linked = replace(event, occurred_at=at, prev_hash=last.hash if last is not None else None, hash=None)
    return replace(linked, hash=chain_hash(linked.prev_hash, linked))


SEARCH_SEPARATOR = "\x1f"
"""Joins the searched columns; a needle can't match across two of them unless it contains this character."""


def _search_text() -> ColumnElement[str]:
    """The searched columns as one string, exactly as the trigram index (``a0001_audit_events``) is built.

    PostgreSQL uses the index only when the expression matches it, so keep the columns, their order, the
    ``coalesce`` and the separator in step with the migration.
    """
    searched = (
        AuditEventRow.resource_id,
        AuditEventRow.resource_display,
        AuditEventRow.request_id,
        AuditEventRow.ip,
        AuditEventRow.actor_display,
    )
    parts = [func.coalesce(column, literal_column("''"), type_=Text) for column in searched]
    joined: ColumnElement[str] = parts[0]
    for part in parts[1:]:
        joined = joined.op("||", return_type=Text)(literal_column(f"'{SEARCH_SEPARATOR}'")).op("||", return_type=Text)(
            part
        )
    return joined


def _conditions(query: EventQuery) -> list[ColumnElement[bool]]:  # noqa: C901  (one branch per filter)
    conditions: list[ColumnElement[bool]] = []
    if query.actor_id:
        conditions.append(AuditEventRow.actor_id == query.actor_id)
    if query.actor_kind:
        conditions.append(AuditEventRow.actor_kind == query.actor_kind)
    if query.action:
        if query.action.endswith("*"):
            conditions.append(AuditEventRow.action.startswith(query.action[:-1], autoescape=True))
        else:
            conditions.append(AuditEventRow.action == query.action)
    if query.decision:
        conditions.append(AuditEventRow.decision == query.decision)
    if query.instance_id:
        conditions.append(AuditEventRow.instance_id == query.instance_id)
    if query.resource_id:
        conditions.append(AuditEventRow.resource_id == query.resource_id)
    if query.source:
        conditions.append(AuditEventRow.source == query.source)
    if query.q and query.q.strip():
        conditions.append(_search_text().icontains(query.q.strip(), autoescape=True))
    if query.since:
        conditions.append(AuditEventRow.occurred_at >= query.since)
    if query.until:
        conditions.append(AuditEventRow.occurred_at < query.until)
    return conditions


def _ascending(query: EventQuery, limit: int, after: Position | None, before: datetime | None) -> Select[Any]:
    statement = select(AuditEventRow).where(*_conditions(query))
    if after is not None:
        at, event_id = after
        statement = statement.where(
            or_(AuditEventRow.occurred_at > at, and_(AuditEventRow.occurred_at == at, AuditEventRow.id > event_id))
        )
    if before is not None:
        statement = statement.where(AuditEventRow.occurred_at < before)
    return statement.order_by(AuditEventRow.occurred_at, AuditEventRow.id).limit(limit)


async def _known_source_ids(executor: Executor, source: Source, ids: Sequence[str]) -> set[str]:
    known: set[str] = set()
    unique = sorted(set(ids))
    for index in range(0, len(unique), 500):
        rows = await executor.execute(
            select(AuditEventRow.source_event_id).where(
                AuditEventRow.source == source, AuditEventRow.source_event_id.in_(unique[index : index + 500])
            )
        )
        known.update(str(value) for (value,) in rows)
    return known


class SqlAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: AuditEvent, *, chained: bool = False) -> AuditEvent:
        # Core insert: audit rows are never loaded back into this unit of work or updated.
        if chained:
            event = await _linked(self._session, self._session.get_bind().dialect.name, event)
        _ = await self._session.execute(insert(AuditEventRow).values(**_values(event)))
        return event

    async def get(self, event_id: str) -> AuditEvent | None:
        row = await self._session.scalar(select(AuditEventRow).where(AuditEventRow.id == event_id))
        return _to_domain(row) if row else None

    async def list_page(self, query: EventQuery, limit: int, after: Position | None) -> Sequence[AuditEvent]:
        statement = (
            select(AuditEventRow)
            .where(*_conditions(query))
            .order_by(AuditEventRow.occurred_at.desc(), AuditEventRow.id.desc())
        )
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

    async def ascending(
        self, query: EventQuery, limit: int, after: Position | None, *, before: datetime | None = None
    ) -> Sequence[AuditEvent]:
        rows = await self._session.scalars(_ascending(query, limit, after, before))
        return [_to_domain(row) for row in rows]

    async def count(self, query: EventQuery, cap: int) -> int:
        capped = select(AuditEventRow.id).where(*_conditions(query)).limit(cap).subquery()
        return int(await self._session.scalar(select(func.count()).select_from(capped)) or 0)

    async def actors(self, since: datetime, limit: int) -> list[ActorSummary]:
        events = func.count().label("events")
        rows = await self._session.execute(
            select(AuditEventRow.actor_kind, AuditEventRow.actor_id, func.max(AuditEventRow.actor_display), events)
            .where(AuditEventRow.occurred_at >= since)
            .group_by(AuditEventRow.actor_kind, AuditEventRow.actor_id)
            .order_by(events.desc(), AuditEventRow.actor_id)
            .limit(limit)
        )
        return [
            ActorSummary(kind=cast("ActorKind", kind), id=str(actor_id), display=str(display), count=int(count))
            for kind, actor_id, display, count in rows
        ]

    async def latest_at(self) -> datetime | None:
        value = await self._session.scalar(select(func.max(AuditEventRow.occurred_at)))
        return aware(value) if value is not None else None

    async def known_source_ids(self, source: Source, ids: Sequence[str]) -> set[str]:
        return await _known_source_ids(self._session, source, ids)


class SqlStandaloneAuditWriter:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def write(self, event: AuditEvent, *, chained: bool = False) -> AuditEvent:
        async with self._sessionmaker.begin() as session:
            if chained:
                event = await _linked(session, session.get_bind().dialect.name, event)
            _ = await session.execute(insert(AuditEventRow).values(**_values(event)))
        return event

    async def write_many(self, events: Sequence[AuditEvent]) -> int:
        async with self._sessionmaker.begin() as session:
            known: set[tuple[str, str]] = set()
            sources: set[Source] = {event.source for event in events if event.source_event_id is not None}
            for source in sources:
                ids = [event.source_event_id for event in events if event.source == source and event.source_event_id]
                known.update((source, value) for value in await _known_source_ids(session, source, ids))
            fresh: list[AuditEvent] = []
            for event in events:
                if event.source_event_id is not None:
                    key = (event.source, event.source_event_id)
                    if key in known:
                        continue
                    known.add(key)
                fresh.append(event)
            if fresh:
                _ = await session.execute(insert(AuditEventRow), [_values(event) for event in fresh])
        return len(fresh)


class SqlPartitionMaintenance:
    """Creates upcoming monthly partitions and drops expired ones (PostgreSQL); deletes old rows on SQLite.

    The append-only trigger exists on PostgreSQL only, so on SQLite a month leaves by deleting its rows.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @property
    def _postgresql(self) -> bool:
        return self._engine.dialect.name == "postgresql"

    async def _partitions(self, connection: AsyncConnection) -> dict[str, str]:
        return {str(name): str(bound) for name, bound in await connection.execute(_PARTITIONS, {"schema": SCHEMA})}

    async def ensure_partitions(self, now: datetime, months_ahead: int) -> list[str]:
        if not self._postgresql:
            return []
        created: list[str] = []
        async with self._engine.begin() as connection:
            existing = await self._partitions(connection)
            for name, start, end in partitions_to_create(now, months_ahead):
                if name in existing:
                    continue
                await _create_partition(connection, name, start, end)
                created.append(name)
        return created

    async def drop_expired(self, now: datetime, retention_days: int) -> list[str]:
        if not self._postgresql:
            async with self._engine.begin() as connection:
                _ = await connection.execute(
                    delete(AuditEventRow).where(AuditEventRow.occurred_at < now - timedelta(days=retention_days))
                )
            return []
        dropped: list[str] = []
        async with self._engine.begin() as connection:
            for name, bound in (await self._partitions(connection)).items():
                upper = upper_bound(bound)
                if upper is not None and partition_expired(upper, now, retention_days):
                    _ = await connection.execute(text(f"DROP TABLE {SCHEMA}.{name}"))
                    dropped.append(name)
        return dropped

    async def expired_months(self, now: datetime, retention_days: int) -> list[str]:
        async with self._engine.connect() as connection:
            if self._postgresql:
                months: list[str] = []
                for bound in (await self._partitions(connection)).values():
                    upper = upper_bound(bound)
                    lower = lower_bound(bound)
                    if upper is not None and lower is not None and partition_expired(upper, now, retention_days):
                        months.append(month_key(lower))
                return sorted(months)
            oldest = await connection.scalar(select(func.min(AuditEventRow.occurred_at)))
        if oldest is None:
            return []
        months = []
        start = month_start(aware(oldest))
        while partition_expired(next_month(start), now, retention_days):
            months.append(month_key(start))
            start = next_month(start)
        return months

    async def month_events(self, month: str, batch: int = 1000) -> AsyncIterator[AuditEvent]:
        start, end = month_bounds(month)
        query = EventQuery(since=start, until=end)
        after: Position | None = None
        while True:
            async with self._engine.connect() as connection:
                rows = list((await connection.execute(_ascending(query, batch, after, None))).mappings())
            for row in rows:
                yield _to_domain(AuditEventRow(**dict(row)))
            if len(rows) < batch:
                return
            last = rows[-1]
            after = (aware(last["occurred_at"]), str(last["id"]))

    async def month_count(self, month: str) -> int:
        start, end = month_bounds(month)
        async with self._engine.connect() as connection:
            value = await connection.scalar(
                select(func.count())
                .select_from(AuditEventRow)
                .where(AuditEventRow.occurred_at >= start, AuditEventRow.occurred_at < end)
            )
        return int(value or 0)

    async def drop_month(self, month: str) -> None:
        start, end = month_bounds(month)
        async with self._engine.begin() as connection:
            if self._postgresql:
                _ = await connection.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.{partition_name(start)}"))
            else:
                _ = await connection.execute(
                    delete(AuditEventRow).where(AuditEventRow.occurred_at >= start, AuditEventRow.occurred_at < end)
                )

    async def ensure_month(self, month: str) -> None:
        if not self._postgresql:
            return
        start, end = month_bounds(month)
        name = partition_name(start)
        async with self._engine.begin() as connection:
            if name not in await self._partitions(connection):
                await _create_partition(connection, name, start, end)

    async def insert_events(self, events: Sequence[AuditEvent]) -> None:
        if not events:
            return
        async with self._engine.begin() as connection:
            _ = await connection.execute(insert(AuditEventRow), [_values(event) for event in events])


async def _create_partition(connection: AsyncConnection, name: str, start: datetime, end: datetime) -> None:
    _ = await connection.execute(
        text(
            f"CREATE TABLE {SCHEMA}.{name} PARTITION OF {SCHEMA}.audit_events "
            f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
        )
    )


def _bound(bound: str, marker: str) -> datetime | None:
    if marker not in bound:
        return None  # the DEFAULT partition
    value = bound.split(marker, 1)[1].split("'", 1)[0]
    return aware(datetime.fromisoformat(value))


def upper_bound(bound: str) -> datetime | None:
    """``FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00')`` → the TO value."""
    return _bound(bound, "TO ('")


def lower_bound(bound: str) -> datetime | None:
    return _bound(bound, "FROM ('")
