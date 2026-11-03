"""``POST /agnostic/v1/components/{validate,normalize}``: check a component config the way AgentOS will load it.

Studio edits agent, team and workflow configs as JSON and stores them through AgentOS's ``/components`` routes. A
config only runs if agno can rebuild it from this instance's registry and db, which the control plane can't check
itself (it never imports agno). These routes rebuild the config with agno's own ``from_dict`` and say what failed:

- **validate** rebuilds strictly, as a strict load would: every tool, model, schema, knowledge, memory manager and
  member must resolve. Answers ``{valid, errors}``; an invalid config is a 200 with ``valid`` false.
- **normalize** rebuilds leniently and serializes the result again, so the control plane can store what agno itself
  would write (defaults applied, unknown keys dropped). A config that can't be rebuilt at all is a 422 with the same
  ``{valid, errors}`` body.

Nothing is stored. Both need ``components:read`` (:data:`~agnostic_bridge.SCOPE_MAPPINGS`) and a synchronous OS db,
since teams and workflows load their members from it.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Literal

from agno.agent import Agent
from agno.db.base import BaseDb
from agno.exceptions import ComponentPinError, ComponentRehydrationError
from agno.team import Team
from agno.workflow import Workflow
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os import AgentOS

VALIDATE_PATH = "/components/validate"
NORMALIZE_PATH = "/components/normalize"

ComponentKind = Literal["agent", "team", "workflow"]

# Rebuild failures agno raises for a bad config, rather than for a bug in agno or the bridge.
_CONFIG_ERRORS = (ComponentPinError, ComponentRehydrationError, ValueError, TypeError, KeyError)

# Best-effort: the config key a rehydration message is about, by the wording agno uses for it. First match wins.
_MESSAGE_PATHS = (
    ("output schema", "output_schema"),
    ("input schema", "input_schema"),
    ("memory manager", "memory_manager"),
    ("session summary manager", "session_summary_manager"),
    ("knowledge", "knowledge"),
    ("learning", "learning"),
    ("filesystem", "filesystem"),
    ("tools", "tools"),
    ("member", "members"),
    ("step", "steps"),
    ("model", "model"),
)


class ComponentConfigInput(BaseModel):
    kind: ComponentKind = Field(description="What the config describes")
    config: dict[str, Any] = Field(description="The config as GET /components/{id}/configs returns it")


class ComponentError(BaseModel):
    path: str | None = Field(None, description="Top-level config key the error is about, when it can be told")
    message: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ComponentError]


class NormalizedConfig(BaseModel):
    config: dict[str, Any] = Field(description="The config as agno serializes it after a lenient rebuild")


def error_of(error: Exception) -> ComponentError:
    if isinstance(error, KeyError) and error.args:
        return ComponentError(path=str(error.args[0]), message=f"Missing key: {error.args[0]}")
    message = str(error) or type(error).__name__
    lowered = message.lower()
    path = next((key for phrase, key in _MESSAGE_PATHS if phrase in lowered), None)
    return ComponentError(path=path, message=message)


def rebuild(kind: ComponentKind, config: dict[str, Any], agent_os: AgentOS, *, strict: bool) -> Agent | Team | Workflow:
    """The component agno builds from ``config``; raises what ``from_dict`` raises. ``config`` is left untouched."""
    data = copy.deepcopy(config)  # from_dict replaces references with live objects in place
    registry = agent_os.registry
    if kind == "agent":
        return Agent.from_dict(data, registry=registry, strict=strict)
    db = agent_os.db if isinstance(agent_os.db, BaseDb) else None
    if kind == "team":
        return Team.from_dict(data, db=db, registry=registry, links=None, strict=strict)
    return Workflow.from_dict(data, db=db, links=None, registry=registry, strict=strict)


def _require_sync_db(agent_os: AgentOS) -> None:
    if not isinstance(agent_os.db, BaseDb):
        raise HTTPException(status_code=503, detail="Components need a synchronous db on this AgentOS")


def add_component_routes(router: APIRouter, agent_os: AgentOS) -> None:
    @router.post(
        VALIDATE_PATH,
        operation_id="agnostic_bridge_validate_component",
        summary="Validate a component config",
        description=(
            "Rebuild an agent, team or workflow config strictly against this AgentOS's registry and db, as a strict "
            "load would, and list what doesn't resolve. Nothing is stored. Needs components:read."
        ),
        response_model=ValidationResult,
        responses={503: {"description": "The AgentOS has no synchronous db"}},
    )
    async def validate_component(body: ComponentConfigInput) -> ValidationResult:
        _require_sync_db(agent_os)
        try:
            rebuild(body.kind, body.config, agent_os, strict=True)
        except _CONFIG_ERRORS as e:
            return ValidationResult(valid=False, errors=[error_of(e)])
        return ValidationResult(valid=True, errors=[])

    @router.post(
        NORMALIZE_PATH,
        operation_id="agnostic_bridge_normalize_component",
        summary="Normalize a component config",
        description=(
            "Rebuild an agent, team or workflow config leniently and serialize it again, as agno would store it. "
            "Nothing is stored. Needs components:read."
        ),
        response_model=NormalizedConfig,
        responses={
            422: {"description": "The config can't be rebuilt", "model": ValidationResult},
            503: {"description": "The AgentOS has no synchronous db"},
        },
    )
    async def normalize_component(body: ComponentConfigInput) -> NormalizedConfig | JSONResponse:
        _require_sync_db(agent_os)
        try:
            component = rebuild(body.kind, body.config, agent_os, strict=False)
            normalized = component.to_dict()
        except _CONFIG_ERRORS as e:
            result = ValidationResult(valid=False, errors=[error_of(e)])
            return JSONResponse(status_code=422, content=result.model_dump())
        return NormalizedConfig(config=normalized)
