"""Audit pipeline health for the System page: SIEM sinks, the archive tier and AgentOS trail ingestion."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_audit.infrastructure.tables import IngestCursorRow, PolicyRow, SinkRow
from agnostic_kernel.diagnostics import StatusItem, StatusState

INGEST_LAG_WARNING = timedelta(hours=1)
GROUP = "Audit"


async def audit_status(session: AsyncSession, now: datetime) -> list[StatusItem]:
    items: list[StatusItem] = []
    for sink in await session.scalars(select(SinkRow).where(SinkRow.enabled).order_by(SinkRow.name)):
        states: dict[str, StatusState] = {"ok": "ok", "paused": "warning"}
        state = states.get(sink.status, "error")
        if state == "ok" and sink.failure_count:
            state = "warning"
        detail = sink.last_error or (
            f"last event {sink.last_event_at:%Y-%m-%d %H:%M} UTC" if sink.last_event_at else "idle"
        )
        items.append(
            StatusItem(
                GROUP, f"SIEM: {sink.name}", state, detail, {"kind": sink.kind, "failures": str(sink.failure_count)}
            )
        )
    policy = await session.get(PolicyRow, 1)
    if policy is not None and policy.archive_enabled:
        if policy.last_archive_error:
            items.append(StatusItem(GROUP, "Archive", "error", policy.last_archive_error))
        else:
            when = f"{policy.last_archive_at:%Y-%m-%d}" if policy.last_archive_at else "not yet"
            items.append(StatusItem(GROUP, "Archive", "ok", f"last archived {when}"))
    oldest = await session.scalar(select(func.min(IngestCursorRow.last_ingested_at)))
    if oldest is not None:
        lag = now - (oldest if oldest.tzinfo else oldest.replace(tzinfo=now.tzinfo))
        state = "warning" if lag > INGEST_LAG_WARNING else "ok"
        items.append(
            StatusItem(
                GROUP,
                "AgentOS trail ingestion",
                state,
                f"oldest cursor {int(lag.total_seconds() // 60)} min behind",
                {"lag_seconds": str(int(lag.total_seconds()))},
            )
        )
    return items
