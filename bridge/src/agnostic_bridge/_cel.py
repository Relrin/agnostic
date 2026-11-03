"""``POST /agnostic/v1/cel/evaluate``: evaluate a workflow CEL expression the way this AgentOS would.

Condition evaluators, Router selectors and Loop end conditions can be CEL strings. agno evaluates them with
cel-python against a context it builds from the step's input (or the loop iteration's outputs). This route builds
the same objects from a sample (``StepInput`` with its previous outputs, or the iteration's ``StepOutput`` list) and
calls agno's own evaluation functions, so the answer is what a run would decide, coerced as a run coerces it
(bool for a Condition or Loop, the choice name for a Router).

Nothing is stored or run besides the expression. Needs ``components:read``
(:data:`~agnostic_bridge.SCOPE_MAPPINGS`) and cel-python (``agno[cel]``): without it the route answers 503.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from agno.workflow import cel as agno_cel
from agno.workflow.types import StepInput, StepOutput
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os import AgentOS

EVALUATE_CEL_PATH = "/cel/evaluate"
MAX_EXPRESSION = 4_000

CelContext = Literal["condition", "router", "loop"]


class CelEvaluationInput(BaseModel):
    expression: str = Field(max_length=MAX_EXPRESSION, description="The CEL expression")
    context: CelContext = Field(description="Where the expression sits: a Condition, a Router or a Loop")
    input: str | None = Field(None, description="Condition/Router: the workflow input")
    previous_step_content: str | None = Field(None, description="Condition/Router: the previous step's output")
    previous_step_outputs: dict[str, str] = Field(
        default_factory=dict, description="Condition/Router: earlier steps' outputs by step name"
    )
    additional_data: dict[str, Any] = Field(default_factory=dict, description="Condition/Router: extra run data")
    session_state: dict[str, Any] = Field(default_factory=dict, description="Condition/Router: the session state")
    step_choices: list[str] = Field(default_factory=list, description="Router: the choices' names")
    step_outputs: dict[str, str] = Field(
        default_factory=dict,
        description="Loop: this iteration's outputs by step name, in order; the last one is last_step_content",
    )
    last_step_content: str | None = Field(None, description="Loop: used when step_outputs is empty")
    all_success: bool = Field(True, description="Loop: whether every step of the iteration succeeded")
    current_iteration: int = Field(1, ge=0, description="Loop: the iteration that just finished")
    max_iterations: int = Field(3, ge=1, description="Loop: the loop's limit")


class CelEvaluation(BaseModel):
    result: bool | str = Field(description="What a run would act on: bool for a Condition or Loop, a name for a Router")
    type: Literal["bool", "string"]


class CelEvaluationError(BaseModel):
    error: str


def evaluate(body: CelEvaluationInput) -> bool | str:
    """Raises ``ValueError`` when agno can't evaluate the expression."""
    if body.context == "loop":
        outputs = [
            StepOutput(step_name=name, content=content, success=body.all_success)
            for name, content in body.step_outputs.items()
        ]
        if not outputs and body.last_step_content is not None:
            outputs = [StepOutput(step_name="last_step", content=body.last_step_content, success=body.all_success)]
        return agno_cel.evaluate_cel_loop_end_condition(
            body.expression, outputs, current_iteration=body.current_iteration, max_iterations=body.max_iterations
        )
    step_input = StepInput(
        input=body.input,
        previous_step_content=body.previous_step_content,
        previous_step_outputs={
            name: StepOutput(step_name=name, content=content) for name, content in body.previous_step_outputs.items()
        },
        additional_data=body.additional_data,
    )
    if body.context == "router":
        return agno_cel.evaluate_cel_router_selector(
            body.expression, step_input, session_state=body.session_state, step_choices=body.step_choices
        )
    return agno_cel.evaluate_cel_condition_evaluator(body.expression, step_input, session_state=body.session_state)


def add_cel_routes(router: APIRouter, agent_os: AgentOS) -> None:
    del agent_os  # evaluation needs nothing from the OS but agno itself

    @router.post(
        EVALUATE_CEL_PATH,
        operation_id="agnostic_bridge_evaluate_cel",
        summary="Evaluate a workflow CEL expression",
        description=(
            "Evaluate a Condition evaluator, Router selector or Loop end condition against a sample context, with "
            "agno's own CEL evaluation. Nothing is stored. Needs components:read."
        ),
        response_model=CelEvaluation,
        responses={
            422: {"description": "The expression doesn't evaluate", "model": CelEvaluationError},
            503: {"description": "cel-python isn't installed on this AgentOS"},
        },
    )
    async def evaluate_cel(body: CelEvaluationInput) -> CelEvaluation | JSONResponse:
        if not agno_cel.CEL_AVAILABLE:
            raise HTTPException(status_code=503, detail="cel-python isn't installed; install agno[cel]")
        try:
            result = evaluate(body)
        except (ValueError, RuntimeError) as e:
            return JSONResponse(status_code=422, content=CelEvaluationError(error=str(e)).model_dump())
        return CelEvaluation(result=result, type="bool" if isinstance(result, bool) else "string")
