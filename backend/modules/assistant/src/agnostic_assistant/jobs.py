"""Background jobs of the assistant module (queue ``assistant``)."""

from __future__ import annotations

import procrastinate

from agnostic_assistant.application.answer import AnswerMessage
from agnostic_assistant.application.housekeeping import Housekeeping
from agnostic_kernel.jobs import job_container


async def answer(context: procrastinate.JobContext, message_id: str) -> None:
    async with job_container(context) as container:
        await (await container.get(AnswerMessage))(container, message_id)


async def prune(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(Housekeeping)).prune()
