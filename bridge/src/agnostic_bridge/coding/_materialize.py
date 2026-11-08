"""Studio agents marked as coding agents, served on this runtime as coding agents.

AgentOS rebuilds stored components only as Agno ``Agent``s, so a coding agent saved in Studio would otherwise run as
a plain agent. :class:`CodingAgentSync` reads the published agent components, and for each one whose metadata
carries the coding marker it builds the matching coding agent (same id, model, instructions and tools, rebuilt
through Agno and the registry) and keeps it in ``agent_os.agents``. AgentOS looks agents up in that list before the
database, so runs, sessions and the queue reach the coding agent. Agents defined in code are never replaced.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from agno.utils.log import log_info, log_warning
from pydantic import BaseModel, Field, ValidationError

from agnostic_bridge.coding._agent import CodingAgent
from agnostic_bridge.coding._opencode import OpenCodeAgent
from agnostic_bridge.coding._pi import PiAgent
from agnostic_bridge.coding._spec import CodingAgentSpec, spec_from_metadata

HARNESSES: dict[str, type[CodingAgent]] = {"pi": PiAgent, "opencode": OpenCodeAgent}
_PAGE = 100
_CAP = 1000


class RefreshResult(BaseModel):
    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict, description="Component id → why it could not be built")


def build_coding_agent(
    agent: Any,
    spec: CodingAgentSpec,
    *,
    db: Any = None,
    version: int | None = None,
    media_storage: Any = None,
) -> CodingAgent:
    """The coding agent for a rebuilt Agno ``Agent`` and its coding settings."""
    cls = HARNESSES[spec.harness]
    coding = cls(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions if isinstance(agent.instructions, (str, list)) else None,
        model=agent.model,
        tools=list(agent.tools or []),
        coding=spec,
        db=db if db is not None else agent.db,
        store_events=True,
        component_version=version,
    )
    if media_storage is not None:
        from agnostic_bridge.artifacts._capture import capture_artifacts

        capture_artifacts(coding, media_storage=media_storage, root=spec.outputs_root)
    return coding


class CodingAgentSync:
    """Keeps ``agent_os.agents`` in step with the published coding agents stored in the AgentOS database."""

    def __init__(self, agent_os: Any, *, interval: float = 10.0) -> None:
        self._os = agent_os
        self.interval = interval
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self.last: RefreshResult | None = None

    # ------------------------------------------------------------------ reading the database

    def _rows(self) -> list[tuple[str, int, dict[str, Any]]]:
        """(component id, published version, config) of every published agent carrying the coding marker."""
        from agno.db.base import BaseDb, ComponentType

        db = getattr(self._os, "db", None)
        if not isinstance(db, BaseDb):
            return []
        found: list[tuple[str, int, dict[str, Any]]] = []
        offset = 0
        while offset < _CAP:
            try:
                components, total = db.list_components(component_type=ComponentType.AGENT, limit=_PAGE, offset=offset)
            except NotImplementedError:
                return []
            for component in components:
                component_id = component.get("component_id") or component.get("id")
                version = component.get("current_version")
                if not isinstance(component_id, str) or version is None:
                    continue
                row = db.get_config(component_id=component_id, version=version)
                config = row.get("config") if isinstance(row, dict) else None
                if isinstance(config, dict):
                    found.append((component_id, int(version), config))
            offset += _PAGE
            if offset >= total or not components:
                break
        return found

    # ------------------------------------------------------------------ keeping the list in step

    def _materialized(self) -> dict[str, CodingAgent]:
        return {
            agent.get_id(): agent
            for agent in self._os.agents or []
            if isinstance(agent, CodingAgent) and agent.component_version is not None
        }

    def _code_ids(self) -> set[str]:
        return {
            str(agent.id)
            for agent in self._os.agents or []
            if not (isinstance(agent, CodingAgent) and agent.component_version is not None)
        }

    async def refresh(self) -> RefreshResult:
        async with self._lock:
            result = RefreshResult()
            rows = await asyncio.to_thread(self._rows)
            current = self._materialized()
            code_ids = self._code_ids()
            seen: set[str] = set()
            for component_id, version, config in rows:
                if component_id in code_ids:
                    continue
                try:
                    spec = spec_from_metadata(config.get("metadata"))
                except ValidationError as error:
                    result.errors[component_id] = f"Invalid coding agent settings: {error.errors()[0]['msg']}"
                    continue
                if spec is None:
                    continue
                seen.add(component_id)
                existing = current.get(component_id)
                if existing is not None and existing.component_version == version:
                    continue
                try:
                    agent = await asyncio.to_thread(self._build, component_id, version, config, spec)
                except Exception as error:
                    result.errors[component_id] = str(error)[:500]
                    continue
                self._swap(existing, agent)
                (result.updated if existing is not None else result.added).append(component_id)
            for component_id, agent in current.items():
                if component_id not in seen and component_id not in result.errors:
                    self._os.agents.remove(agent)
                    result.removed.append(component_id)
            if result.added or result.updated or result.removed:
                log_info(
                    f"Coding agents: +{len(result.added)} ~{len(result.updated)} -{len(result.removed)} from Studio"
                )
            for component_id, error in result.errors.items():
                log_warning(f"Coding agents: cannot serve {component_id}: {error}")
            self.last = result
            return result

    def _build(self, component_id: str, version: int, config: dict[str, Any], spec: CodingAgentSpec) -> CodingAgent:
        from agno.agent import Agent

        agent = Agent.from_dict(config, registry=getattr(self._os, "registry", None), strict=True)
        agent.id = component_id
        return build_coding_agent(
            agent,
            spec,
            db=getattr(self._os, "db", None),
            version=version,
            media_storage=getattr(self._os, "media_storage", None),
        )

    def _swap(self, existing: CodingAgent | None, agent: CodingAgent) -> None:
        agents = self._os.agents
        if agents is None:
            self._os.agents = agents = []
        if existing is not None and existing in agents:
            agents[agents.index(existing)] = agent
        else:
            agents.append(agent)

    # ------------------------------------------------------------------ background loop

    @contextlib.asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        self._task = asyncio.ensure_future(self._loop())
        try:
            yield
        finally:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as error:
                log_warning(f"Coding agents: refreshing from Studio failed: {error}")
            await asyncio.sleep(self.interval)
