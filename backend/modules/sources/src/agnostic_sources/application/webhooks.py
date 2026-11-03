"""Webhooks from git hosts: verify, deduplicate, and queue a fetch (push) or a pull request check.

The answer comes fast and carries nothing about the sources: an unsigned or wrongly signed delivery is refused
without being stored, so unknown senders can't fill the delivery log.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import orjson

from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import AppError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger
from agnostic_sources.application.ports import SourceStore
from agnostic_sources.application.tasks import SourceJobs
from agnostic_sources.domain.model import Delivery, Provider, Source
from agnostic_sources.domain.webhooks import (
    delivery_id,
    event_name,
    installation_of,
    pull_event,
    push_event,
    repo_of,
    verify,
)

log = get_logger(__name__)

SAME_HOST: dict[str, frozenset[str]] = {
    "gitea": frozenset({"gitea", "forgejo"}),
    "forgejo": frozenset({"gitea", "forgejo"}),
    "github": frozenset({"github"}),
    "gitlab": frozenset({"gitlab"}),
}


class WebhookRejectedError(AppError):
    status = 401
    code = "webhook_rejected"
    title = "The webhook isn't signed for a source here"


class WebhookIntake:
    def __init__(self, store: SourceStore, jobs: SourceJobs) -> None:
        self._store = store
        self._jobs = jobs

    async def receive(  # noqa: C901, PLR0912
        self, provider: Provider, headers: Mapping[str, str], body: bytes
    ) -> int:
        """The number of sources the delivery was accepted for."""
        try:
            raw: object = orjson.loads(body) if body else {}
        except orjson.JSONDecodeError as exc:
            raise ValidationFailedError("The webhook body isn't JSON.") from exc
        if not isinstance(raw, dict):
            raise ValidationFailedError("The webhook body isn't a JSON object.")
        payload = cast("dict[str, Any]", raw)
        lowered = {name.lower(): value for name, value in headers.items()}
        repo = repo_of(provider, payload)
        installation = installation_of(payload)
        accepted: list[Source] = []
        for source in await self._store.sources():
            if source.provider not in SAME_HOST.get(provider, frozenset()):
                continue
            if repo is None or source.repo.lower() != repo.lower():
                continue
            secret = await self._secret(source, installation)
            if secret and verify(provider, secret, body, lowered):
                accepted.append(source)
        if not accepted:
            raise WebhookRejectedError("No source here expects this delivery, or its signature doesn't match.")
        event = event_name(provider, lowered, payload)
        identifier = delivery_id(provider, lowered, body)
        queued = 0
        for source in accepted:
            delivery = Delivery(new_id("swd"), source.id, provider, identifier, event or "unknown", utcnow())
            if not await self._store.record_delivery(delivery):
                continue
            error: str | None = None
            if event == "push":
                push = push_event(provider, payload)
                if push is not None and push.branch == source.branch and source.status == "active":
                    _ = await self._jobs.fetch(source.id, "push")
                    queued += 1
                elif push is not None and push.branch != source.branch:
                    error = f"Push to {push.branch}, not {source.branch}: nothing to do."
            elif event == "pull_request":
                pull = pull_event(provider, payload)
                if pull is not None and pull.number:
                    _ = await self._jobs.refresh(source.id, pull.number)
                    queued += 1
            elif event not in {"ping", ""}:
                error = f"{event} events aren't used."
            await self._store.finish_delivery(delivery.id, error)
        await self._store.commit()
        log.info("sources.webhook", provider=provider, webhook_event=event, sources=len(accepted), queued=queued)
        return len(accepted)

    async def _secret(self, source: Source, installation: str | None) -> str | None:
        secret = await self._store.source_secret(source.id)
        if secret:
            return secret
        if source.connection_id is None:
            return None
        connection = await self._store.connection(source.connection_id)
        if connection is None:
            return None
        if connection.auth_kind == "github_app" and installation and connection.installation_id != installation:
            return None
        return (await self._store.connection_secrets(connection.id)).webhook_secret
