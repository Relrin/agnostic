"""``GET /agnostic/v1/coding-agents`` (what this runtime serves as coding agents) and the Studio refresh route."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agnostic_bridge.coding._agent import CodingAgent
from agnostic_bridge.coding._materialize import CodingAgentSync, RefreshResult

CODING_AGENTS_PATH = "/coding-agents"
REFRESH_CODING_AGENTS_PATH = "/coding-agents/refresh"


class CodingModel(BaseModel):
    id: str | None = None
    provider: str | None = None


class CodingSandbox(BaseModel):
    provider: Literal["docker", "e2b"]
    image: str
    template: str | None = None
    network: str
    cpus: float
    memory_mb: int
    turn_timeout_s: int


class CodingAgentInfo(BaseModel):
    id: str
    name: str | None = None
    harness: Literal["pi", "opencode"]
    source: Literal["code", "studio"] = Field(description="Defined in the runtime's code, or a published Studio agent")
    version: int | None = Field(default=None, description="The published Studio version it was built from")
    model: CodingModel | None = None
    sandbox: CodingSandbox
    outputs_root: str
    tools: list[str] = Field(default_factory=list, description="Agno tools the agent offers its sandbox over MCP")


class CodingAgentList(BaseModel):
    items: list[CodingAgentInfo]


def _tool_names(agent: CodingAgent) -> list[str]:
    names: list[str] = []
    for tool in agent.tools or []:
        name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
        if isinstance(name, str) and name:
            names.append(name)
    return names


def describe(agent: CodingAgent) -> CodingAgentInfo:
    spec = agent.spec
    model = agent.model
    return CodingAgentInfo(
        id=agent.get_id(),
        name=agent.name,
        harness=spec.harness,
        source="studio" if agent.component_version is not None else "code",
        version=agent.component_version,
        model=CodingModel(id=model.id, provider=model.get_provider()) if model is not None else None,
        sandbox=CodingSandbox(
            provider=spec.sandbox.provider,
            image=spec.sandbox.image,
            template=spec.sandbox.template,
            network=spec.sandbox.network,
            cpus=spec.sandbox.cpus,
            memory_mb=spec.sandbox.memory_mb,
            turn_timeout_s=spec.sandbox.turn_timeout_s,
        ),
        outputs_root=spec.outputs_root,
        tools=_tool_names(agent),
    )


def add_coding_routes(router: APIRouter, agent_os: Any, sync: CodingAgentSync | None) -> None:
    @router.get(
        CODING_AGENTS_PATH,
        operation_id="agnostic_bridge_list_coding_agents",
        summary="List coding agents",
        description="Agents this runtime runs as sandboxed coding harnesses (Pi, OpenCode). Needs agents:read.",
        response_model=CodingAgentList,
    )
    async def list_coding_agents() -> CodingAgentList:
        agents = [agent for agent in agent_os.agents or [] if isinstance(agent, CodingAgent)]
        return CodingAgentList(items=[describe(agent) for agent in agents])

    @router.post(
        REFRESH_CODING_AGENTS_PATH,
        operation_id="agnostic_bridge_refresh_coding_agents",
        summary="Refresh coding agents from Studio",
        description="Rebuild the coding agents published in Studio now, not at the next poll. Needs config:write.",
        response_model=RefreshResult,
    )
    async def refresh_coding_agents() -> RefreshResult:
        if sync is None:
            raise HTTPException(status_code=409, detail="Serving Studio coding agents is off on this runtime")
        return await sync.refresh()
