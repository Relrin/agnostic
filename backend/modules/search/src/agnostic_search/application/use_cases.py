"""Searching the palette index (filtered by what the person may see) and rebuilding it from module providers."""

from __future__ import annotations

from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.logging import get_logger
from agnostic_kernel.modules import LoadedModules
from agnostic_search.application.ports import Hit, SearchIndex

log = get_logger(__name__)
OVERFETCH = 4


class SearchEntities:
    def __init__(self, index: SearchIndex, authorizer: Authorizer, instances: InstancesFacade) -> None:
        self._index = index
        self._authorizer = authorizer
        self._instances = instances

    async def __call__(self, principal: Principal, text: str, *, instance_ref: str | None, limit: int) -> list[Hit]:
        if not text.strip():
            return []
        instance = await self._instances.get(instance_ref) if instance_ref else None
        candidates = await self._index.query(
            text, instance_id=instance.id if instance else None, limit=limit * OVERFETCH
        )
        decisions: dict[tuple[str, str | None], bool] = {}
        visible: list[Hit] = []
        for hit in candidates:
            if hit.required_scope:
                key = (hit.required_scope, hit.instance_id)
                if key not in decisions:
                    decision = await self._authorizer.check(principal, hit.required_scope, instance_id=hit.instance_id)
                    decisions[key] = decision.allowed
                if not decisions[key]:
                    continue
            visible.append(hit)
            if len(visible) >= limit:
                break
        return visible


async def reindex(container: AsyncContainer) -> dict[str, int]:
    """Rebuild every provider's documents in one transaction; a failing provider keeps its old documents."""
    modules = await container.get(LoadedModules)
    index = await container.get(SearchIndex)
    session = await container.get(AsyncSession)
    counts: dict[str, int] = {}
    for module in modules.enabled:
        for provider in module.search_providers():
            if provider.documents is None:
                continue
            try:
                documents = await provider.documents(container)
            except Exception as exc:  # noqa: BLE001  (one module failing must not empty the palette)
                log.warning("search.provider_failed", provider=provider.entity, error=str(exc))
                continue
            await index.replace(provider.entity, documents)
            counts[provider.entity] = len(documents)
    await session.commit()
    return counts
