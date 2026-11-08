"""``GET /agnostic/v1/reasoning/{family}/{component_id}``: the reasoning levels a run of a component may ask for.

Only components whose runs apply ``reasoning_effort`` are answered with levels: the code-defined agents and teams
:func:`install` gave the reasoning hook, and coding agents (which apply it to their model proxy). Anything else,
including db-stored components AgentOS rebuilds per request, answers ``null``, so the UI offers no levels that would
be ignored.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter

from agnostic_bridge.coding._agent import CodingAgent
from agnostic_bridge.reasoning import ReasoningOptions, add_reasoning_hook, has_reasoning_hook, reasoning_options

REASONING_PATH = "/reasoning/{family}/{component_id}"


def _component_id(component: Any) -> str | None:
    get_id = getattr(component, "get_id", None)
    if callable(get_id):
        try:
            value = get_id()
        except Exception:
            value = None
        if isinstance(value, str):
            return value
    value = getattr(component, "id", None)
    return value if isinstance(value, str) else None


def _members(team: Any) -> list[Any]:
    members = getattr(team, "members", None)
    return list(members) if isinstance(members, list) else []


def add_reasoning_hooks(agent_os: Any) -> int:
    """Give the code-defined agents and teams of ``agent_os`` the reasoning hook; returns how many took it.

    Team members get it too, so a member run directly applies its own level. Coding agents apply the level
    themselves and are left alone.
    """
    count = 0
    pending: list[Any] = [*(agent_os.agents or []), *(getattr(agent_os, "teams", None) or [])]
    seen: set[int] = set()
    while pending:
        component = pending.pop()
        if id(component) in seen or isinstance(component, CodingAgent):
            continue
        seen.add(id(component))
        if add_reasoning_hook(component):
            count += 1
        pending.extend(_members(component))
    return count


def component_reasoning(agent_os: Any, family: str, component_id: str) -> ReasoningOptions | None:
    pool = agent_os.agents if family == "agents" else getattr(agent_os, "teams", None)
    component = next((item for item in pool or [] if _component_id(item) == component_id), None)
    if component is None:
        return None
    if not isinstance(component, CodingAgent) and not has_reasoning_hook(component):
        return None
    return reasoning_options(getattr(component, "model", None))


def add_reasoning_routes(router: APIRouter, agent_os: Any) -> None:
    @router.get(
        REASONING_PATH,
        operation_id="agnostic_bridge_get_reasoning_options",
        summary="Get a component's reasoning levels",
        description=(
            "The reasoning effort levels a run of this agent or team may send as `reasoning_effort`, translated for "
            "its model's provider; null when its runs take none. Needs agents:read."
        ),
        response_model=ReasoningOptions | None,
    )
    async def get_reasoning_options(family: Literal["agents", "teams"], component_id: str) -> ReasoningOptions | None:
        return component_reasoning(agent_os, family, component_id)
