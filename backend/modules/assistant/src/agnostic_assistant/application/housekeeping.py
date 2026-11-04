"""Conversations past the org's retention go away; answers whose worker died are marked failed."""

from __future__ import annotations

from datetime import timedelta

from agnostic_assistant.application.limits import AnswerLimits
from agnostic_assistant.application.ports import AssistantStore
from agnostic_kernel.db import utcnow
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)


class Housekeeping:
    def __init__(self, store: AssistantStore, limits: AnswerLimits) -> None:
        self._store = store
        self._limits = limits

    async def prune(self) -> tuple[int, int]:
        settings = await self._store.settings()
        now = utcnow()
        removed = await self._store.prune(now - timedelta(days=settings.retention_days))
        stale = await self._store.fail_stale(
            now - timedelta(seconds=self._limits.answer_timeout_seconds * 2),
            "The answer stopped before it finished; ask again.",
        )
        await self._store.commit()
        if removed or stale:
            log.info("assistant.pruned", conversations=removed, stale=stale, retention_days=settings.retention_days)
        return removed, stale
