"""What the tool catalog's use cases need from storage and from the runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from agnostic_instances.facade import Instance
from agnostic_tool_catalog.domain.entries import Entry

READ = "tool_catalog:read"
WRITE = "tool_catalog:write"
LOCAL = "tool_catalog:local"
SYNC = "tool_catalog:sync"
COMPONENTS_WRITE = "components:write"

NOTIFY_TASK = "tool_catalog.notify"
QUEUE = "instances"

BRIDGE_STATUS = "/agnostic/v1/tool-catalog/status"
BRIDGE_SYNC = "/agnostic/v1/tool-catalog/sync"
BRIDGE_PROBE = "/agnostic/v1/tool-catalog/probe"
BRIDGE_TOOLKITS = "/agnostic/v1/toolkits"


@dataclass(frozen=True, slots=True)
class SyncState:
    instance_id: str
    manifest_etag: str | None
    entries: int
    bridge_version: str | None
    last_pull_ip: str | None
    last_pulled_at: datetime | None


class EntryRepository(Protocol):
    async def list(self) -> list[Entry]: ...
    async def get(self, entry_id: str) -> Entry | None: ...
    async def by_registry_name(self, name: str) -> Entry | None: ...
    async def add(self, entry: Entry) -> None: ...
    async def save(self, entry: Entry, *, expected_version: int) -> bool:
        """Store a changed entry (its ``version`` already bumped); ``False`` when someone changed it first."""
        ...

    async def delete(self, entry_id: str) -> None: ...
    async def commit(self) -> None: ...


class SyncStateRepository(Protocol):
    async def get(self, instance_id: str) -> SyncState | None: ...
    async def record(self, state: SyncState) -> None: ...
    async def commit(self) -> None: ...


class RuntimeBridge(Protocol):
    """The bridge routes the control plane calls as itself (control-plane actions, not on someone's behalf)."""

    async def status(self, instance: Instance) -> dict[str, Any] | None:
        """``GET /agnostic/v1/tool-catalog/status``; ``None`` when the bridge doesn't answer."""
        ...

    async def nudge(self, instance: Instance) -> bool:
        """``POST /agnostic/v1/tool-catalog/sync``: pull now instead of at the next interval."""
        ...

    async def probe(self, instance: Instance, item: dict[str, Any]) -> dict[str, Any]:
        """``POST /agnostic/v1/tool-catalog/probe``: connect to a server once and list its tools."""
        ...

    async def toolkits(self, instance: Instance) -> dict[str, Any] | None:
        """``GET /agnostic/v1/toolkits``: the runtime's own toolkit list, with what it can build."""
        ...


class NotifyQueue(Protocol):
    async def notify(self, instance_ids: list[str]) -> None:
        """Ask the affected bridges to pull now (empty: every instance)."""
        ...
