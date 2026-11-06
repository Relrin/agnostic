"""The only import surface other modules may use: which catalog entries a viewer can build with on an instance.

Studio reaches the catalog through its own ``ToolCatalogLookup`` port, which this module provides; nothing else needs
more than this.
"""

from __future__ import annotations

from typing import Protocol

from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_tool_catalog.application.catalog import EntryView, ToolCatalog

__all__ = ["EntryView", "ToolCatalogFacade", "ToolCatalogFacadeImpl"]


class ToolCatalogFacade(Protocol):
    async def for_instance(self, principal: Principal, instance: Instance) -> list[EntryView]:
        """Active entries the viewer may use on the instance, org first, then team, then custom."""
        ...


class ToolCatalogFacadeImpl:
    def __init__(self, catalog: ToolCatalog) -> None:
        self._catalog = catalog

    async def for_instance(self, principal: Principal, instance: Instance) -> list[EntryView]:
        return await self._catalog.for_instance(principal, instance)
