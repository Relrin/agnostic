"""Background jobs of the hello module."""

from __future__ import annotations

import procrastinate

from agnostic_hello.application.use_cases import ComposeReply
from agnostic_hello.facade import HelloFacade
from agnostic_kernel.jobs import job_container
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)


async def compose_reply(context: procrastinate.JobContext, greeting_id: str) -> None:
    job_id = context.job.id
    assert job_id is not None
    async with job_container(context) as container:
        use_case = await container.get(ComposeReply)
        greeting = await use_case(greeting_id, job_id)
    log.info("hello.reply_composed", greeting_id=greeting_id, replied=greeting is not None)


async def heartbeat(context: procrastinate.JobContext, timestamp: int) -> None:
    """Periodic proof that scheduling works: logs how many greetings exist."""
    async with job_container(context) as container:
        facade = await container.get(HelloFacade)
        total = await facade.greeting_count()
    log.info("hello.heartbeat", timestamp=timestamp, greetings=total)
