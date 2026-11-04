"""The only import surface other modules may use: whether AI features are on (for their own feature checks)."""

from __future__ import annotations

from typing import Protocol

from agnostic_assistant.application.ports import AssistantStore
from agnostic_assistant.domain.settings import FEATURES, Feature

__all__ = ["AssistantStatusReader", "AssistantStatusReaderImpl", "Feature"]


class AssistantStatusReader(Protocol):
    async def available(self) -> dict[Feature, bool]:
        """Each feature: configured, switched on, and under the master switch."""
        ...


class AssistantStatusReaderImpl:
    def __init__(self, store: AssistantStore) -> None:
        self._store = store

    async def available(self) -> dict[Feature, bool]:
        settings = await self._store.settings()
        return {feature: settings.available(feature) for feature in FEATURES}
