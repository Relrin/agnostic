"""Background jobs and domain-event handlers of the notifications module."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import procrastinate
from dishka import AsyncContainer

from agnostic_kernel.jobs import job_container
from agnostic_notifications.application.announcements import Announcements
from agnostic_notifications.application.deliver import Deliver
from agnostic_notifications.application.notify import DELIVER_TASK
from agnostic_notifications.settings import NotificationsSettings

__all__ = ["DELIVER_TASK", "deliver", "on_eval_regression", "on_privileged_grant"]


async def deliver(context: procrastinate.JobContext, delivery_id: str) -> None:
    async with job_container(context) as container:
        retries = (await container.get(NotificationsSettings)).delivery_retries
        await (await container.get(Deliver))(delivery_id, last_attempt=context.job.attempts >= retries)


async def on_privileged_grant(container: AsyncContainer, payload: Mapping[str, Any]) -> None:
    async with container() as request:
        await (await request.get(Announcements)).privileged_grant(payload)


async def on_eval_regression(container: AsyncContainer, payload: Mapping[str, Any]) -> None:
    async with container() as request:
        await (await request.get(Announcements)).eval_regression(payload)
