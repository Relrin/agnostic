"""Webhook health for the System page: deliveries that failed or were never processed."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.diagnostics import StatusItem
from agnostic_sources.infrastructure.tables import WebhookDeliveryRow

STUCK_AFTER = timedelta(minutes=15)


async def webhook_status(session: AsyncSession, now: datetime) -> list[StatusItem]:
    failed = await session.scalar(
        select(func.count()).where(
            WebhookDeliveryRow.error.is_not(None), WebhookDeliveryRow.received_at >= now - timedelta(days=1)
        )
    )
    stuck = await session.scalar(
        select(func.count()).where(
            WebhookDeliveryRow.processed_at.is_(None), WebhookDeliveryRow.received_at < now - STUCK_AFTER
        )
    )
    failed, stuck = int(failed or 0), int(stuck or 0)
    state = "error" if failed else "warning" if stuck else "ok"
    detail = (
        f"{failed} failed in the last 24 h, {stuck} not processed" if failed or stuck else "every webhook processed"
    )
    return [StatusItem("Code sources", "Webhooks", state, detail, {"failed_24h": str(failed), "waiting": str(stuck)})]
