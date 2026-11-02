"""``POST /agnostic/v1/evals/run``: run one eval against a specific version of an agent or team.

AgentOS's ``POST /eval-runs`` evaluates only the component as it is served now. This route takes the same body plus
the component and an optional config version, so the control plane can evaluate a draft before publishing it. It is
the AgentOS route with a different resolution step and a judge-only model override:

- **Resolution** goes through agno's ``resolve_agent`` / ``resolve_team`` (the run routes' helpers): an explicit
  version loads that stored config, drafts included; no version resolves what the run routes would (code-defined
  first, then the current published config). A draft is a preview for its owner and for privileged callers (admin,
  or authorization off); everyone else gets the same 404 as a missing component.
- **Access** is AgentOS's: the route needs ``evals:write`` (:data:`~agnostic_bridge.SCOPE_MAPPINGS`), and the caller
  must be allowed to run the target, as on ``POST /eval-runs``.
- **Judge**: ``model_provider`` + ``model_id`` pick the evaluator model of accuracy and agent-as-judge evals. The
  evaluated component keeps its own model (``POST /eval-runs`` swaps the component's model instead).
- **Execution** is AgentOS's ``run_*_eval`` helpers with the OS db, so the result is stored and listed by
  ``GET /eval-runs`` like any other eval run, owned by the caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.evals import EvalType
from agno.models.utils import get_model
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.evals import utils as eval_utils
from agno.os.routers.evals.schemas import EvalRunInput, EvalSchema
from agno.os.utils import resolve_agent, resolve_team
from agno.team import Team
from agno.utils.log import log_warning
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, create_model

if TYPE_CHECKING:
    from agno.models.base import Model
    from agno.os import AgentOS

RUN_EVAL_PATH = "/evals/run"

_TARGET_FIELDS = ("agent_id", "team_id")
# Eval types whose helpers take default_model as the evaluator; performance and reliability have none.
_JUDGED = (EvalType.ACCURACY, EvalType.AGENT_AS_JUDGE)

try:  # agno's own per-target gate, so the decision and its audit record match POST /eval-runs
    from agno.os.routers.evals.evals import _require_eval_target_run_access
except ImportError:  # private in agno; fall back to the scope check it makes under the default provider

    async def _require_eval_target_run_access(request: Request, *, resource_type: str, resource_id: str) -> None:
        if not getattr(request.state, "authorization_enabled", False):
            return
        scopes = set(getattr(request.state, "scopes", None) or [])
        accepted = {"agent_os:admin", f"{resource_type}:run", f"{resource_type}:{resource_id}:run"}
        if scopes.isdisjoint(accepted):
            singular = "agent" if resource_type == "agents" else "team"
            raise HTTPException(status_code=403, detail=f"Access denied to run this {singular}")


# Every EvalRunInput field except the target, which the component fields replace; built from agno's model so the
# body follows it field for field.
BridgeEvalRunInput: Any = create_model(  # Any: a dynamic model is not a valid type expression for checkers
    "BridgeEvalRunInput",
    __doc__="AgentOS's eval run body, with the target named by component and optional config version.",
    component_type=(Literal["agent", "team"], Field(description="Kind of component to evaluate")),
    component_id=(str, Field(min_length=1, description="Agent or team id")),
    version=(
        int | None,
        Field(None, ge=1, description="Config version to evaluate, drafts included; None = the current component"),
    ),
    **{
        name: (field.annotation, field)
        for name, field in EvalRunInput.model_fields.items()
        if name not in _TARGET_FIELDS
    },
)


class BridgeEvalRun(EvalSchema):
    component_version: int | None = Field(None, description="The version evaluated, as requested; None = current")


def _judge_model(body: Any) -> Model | None:
    """The evaluator model named by ``model_provider`` + ``model_id``; None = agno's default evaluator.

    Unlike ``POST /eval-runs``, this never touches the evaluated component's model: the component runs as
    configured, so a draft and the current version are scored by the same judge. Only accuracy and agent-as-judge
    evals have a judge; the others ignore it."""
    if body.eval_type not in _JUDGED:
        return None
    if body.model_id is None and body.model_provider is None:
        return None
    if body.model_id is None or body.model_provider is None:
        raise HTTPException(status_code=400, detail="model_id and model_provider name the judge model together")
    try:
        return get_model(f"{body.model_provider}:{body.model_id}")
    except (ValueError, ImportError) as e:  # unknown provider, or its SDK isn't installed in this AgentOS
        raise HTTPException(status_code=400, detail=f"Judge model unavailable: {e}") from e


async def _resolve(agent_os: AgentOS, request: Request, body: Any) -> Agent | Team:
    version = body.version
    # An explicit version is a stored config; the code-defined components would shadow it.
    if body.component_type == "agent":
        agents = agent_os.agents if version is None else None
        component: Any = await resolve_agent(
            body.component_id, agents, agent_os.db, agent_os.registry, version=version, request=request
        )
        if not isinstance(component, Agent):
            raise HTTPException(status_code=400, detail="Evals run only against local agents")
    else:
        teams = agent_os.teams if version is None else None
        component = await resolve_team(
            body.component_id, teams, agent_os.db, agent_os.registry, version=version, request=request
        )
        if not isinstance(component, Team):
            raise HTTPException(status_code=400, detail="Evals run only against local teams")
    return component


async def _stamp_owner(db: BaseDb | AsyncBaseDb, eval_run: EvalSchema, user_id: str) -> None:
    # Best-effort, as on POST /eval-runs: the run is already stored.
    try:
        if isinstance(db, AsyncBaseDb):
            await db.update_eval_run_user_id(eval_run_id=eval_run.id, user_id=user_id)
        else:
            db.update_eval_run_user_id(eval_run_id=eval_run.id, user_id=user_id)
        eval_run.user_id = user_id
    except Exception as e:
        log_warning(f"Could not set owner on eval run {eval_run.id}: {e}")


def add_eval_routes(router: APIRouter, agent_os: AgentOS) -> None:
    @router.post(
        RUN_EVAL_PATH,
        operation_id="agnostic_bridge_run_eval",
        summary="Run an eval against a component version",
        description=(
            "POST /eval-runs for a chosen config version of an agent or team, drafts included (owner or admin "
            "only). The run is stored in the OS db and listed by GET /eval-runs. Needs evals:write and run access "
            "to the component."
        ),
        response_model=BridgeEvalRun,
        responses={
            400: {"description": "Invalid body for the eval type, or a component that can't be evaluated"},
            404: {"description": "Component or version not found"},
            503: {"description": "The AgentOS has no db to store eval runs in"},
        },
    )
    async def run_eval(request: Request, body: BridgeEvalRunInput) -> BridgeEvalRun:
        # Resolved before the run: get_scoped_user_id raises 403 and the eval makes real model calls.
        creator_user_id = get_scoped_user_id(request) or getattr(request.state, "user_id", None)
        await _require_eval_target_run_access(
            request,
            resource_type="agents" if body.component_type == "agent" else "teams",
            resource_id=body.component_id,
        )

        db = agent_os.db
        if not isinstance(db, (BaseDb, AsyncBaseDb)):
            raise HTTPException(status_code=503, detail="This AgentOS has no db to store eval runs in")

        judge = _judge_model(body)
        component = await _resolve(agent_os, request, body)
        agent = component if isinstance(component, Agent) else None
        team = component if isinstance(component, Team) else None
        eval_run_input = EvalRunInput(
            **body.model_dump(exclude={"component_type", "component_id", "version"}),
            agent_id=agent.id if agent else None,
            team_id=team.id if team else None,
        )

        runner = {
            EvalType.ACCURACY: eval_utils.run_accuracy_eval,
            EvalType.AGENT_AS_JUDGE: eval_utils.run_agent_as_judge_eval,
            EvalType.PERFORMANCE: eval_utils.run_performance_eval,
            EvalType.RELIABILITY: eval_utils.run_reliability_eval,
        }[eval_run_input.eval_type]
        eval_run = await runner(eval_run_input=eval_run_input, db=db, agent=agent, team=team, default_model=judge)

        if creator_user_id is not None:
            await _stamp_owner(db, eval_run, creator_user_id)
        return BridgeEvalRun(**eval_run.model_dump(), component_version=body.version)
