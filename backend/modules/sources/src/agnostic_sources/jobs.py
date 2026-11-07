"""Background jobs of the sources module (queue ``git``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import procrastinate
from dishka import AsyncContainer

from agnostic_kernel.auth import SYSTEM_PRINCIPAL
from agnostic_kernel.jobs import job_container
from agnostic_sources.application.access import SourcesAccess
from agnostic_sources.application.housekeeping import Housekeeping
from agnostic_sources.application.outgoing import Committer, OnPublished, OutgoingPreparer, PullRequestTracker
from agnostic_sources.application.ports import SourceStore
from agnostic_sources.application.sources import Sources
from agnostic_sources.application.sync import Fetcher, IncomingComputer, Puller


async def scan(context: procrastinate.JobContext, source_id: str) -> None:
    async with job_container(context) as container:
        _ = await (await container.get(Sources)).scan(source_id)


async def fetch(context: procrastinate.JobContext, source_id: str, reason: str) -> None:
    async with job_container(context) as container:
        _ = await (await container.get(Fetcher)).fetch(source_id, reason)


async def compute_incoming(context: procrastinate.JobContext, source_id: str, reason: str) -> None:
    async with job_container(context) as container:
        _ = await (await container.get(IncomingComputer)).compute(source_id, reason)


async def pull_as_drafts(context: procrastinate.JobContext, source_id: str, change_ids: list[str]) -> None:
    """Pull on push (the "as drafts" policy): the control plane creates the drafts, never publishes them."""
    async with job_container(context) as container:
        store = await container.get(SourceStore)
        source = await store.source(source_id)
        if source is None:
            return
        instance = await (await container.get(SourcesAccess)).of(source)
        _ = await (await container.get(Puller)).run(SYSTEM_PRINCIPAL, source, instance, change_ids)


async def prepare_outgoing(context: procrastinate.JobContext, source_id: str) -> None:
    async with job_container(context) as container:
        _ = await (await container.get(OutgoingPreparer)).prepare(source_id)


async def commit_and_pr(
    context: procrastinate.JobContext,
    source_id: str,
    change_ids: list[str],
    message: str | None,
    actor_id: str | None,
    actor_name: str,
    actor_email: str | None,
) -> None:
    async with job_container(context) as container:
        _ = await (await container.get(Committer)).run(
            source_id, change_ids, message, actor_id, actor_name, actor_email
        )


async def write_back(
    context: procrastinate.JobContext,
    source_id: str,
    component_id: str,
    version: int,
    actor_id: str | None,
    actor_name: str,
    actor_email: str | None,
) -> None:
    async with job_container(context) as container:
        await (await container.get(OnPublished)).write_back(
            source_id, component_id, version, actor_id, actor_name, actor_email
        )


async def refresh_pr_status(context: procrastinate.JobContext, source_id: str, number: int | None) -> None:
    async with job_container(context) as container:
        _ = await (await container.get(PullRequestTracker)).refresh(source_id, number)


async def fetch_all(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(Housekeeping)).fetch_all()


async def refresh_all(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        _ = await (await container.get(Housekeeping)).refresh_all()


async def gc(context: procrastinate.JobContext, timestamp: int) -> None:  # noqa: ARG001
    async with job_container(context) as container:
        await (await container.get(Housekeeping)).gc()


async def on_published(container: AsyncContainer, payload: Mapping[str, Any]) -> None:
    await (await container.get(OnPublished))(dict(payload))
