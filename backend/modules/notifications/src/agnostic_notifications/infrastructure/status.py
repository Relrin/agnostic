"""Delivery health for the System page: failures in the last day, deliveries stuck waiting."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.diagnostics import StatusItem
from agnostic_notifications.infrastructure.tables import DeliveryRow

STUCK_AFTER = timedelta(minutes=15)


async def delivery_status(session: AsyncSession, now: datetime) -> list[StatusItem]:
    failed = await session.scalar(
        select(func.count()).where(DeliveryRow.status == "failed", DeliveryRow.created_at >= now - timedelta(days=1))
    )
    stuck = await session.scalar(
        select(func.count()).where(DeliveryRow.status == "pending", DeliveryRow.created_at < now - STUCK_AFTER)
    )
    failed, stuck = int(failed or 0), int(stuck or 0)
    state = "error" if failed else "warning" if stuck else "ok"
    detail = (
        f"{failed} failed in the last 24 h" + (f", {stuck} waiting longer than 15 min" if stuck else "")
        if failed or stuck
        else "every delivery went out"
    )
    return [
        StatusItem("Notifications", "Deliveries", state, detail, {"failed_24h": str(failed), "waiting": str(stuck)})
    ]
