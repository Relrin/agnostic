"""The workflow builder's server side.

Validation with a step count, CEL checks and evaluation, per-step stats from traces, recent step results from runs,
and the canvas layout a person adjusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from agnostic_cel import CheckResult, ContextName
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import AppError, ValidationFailedError
from agnostic_observe.facade import RangeName, StepStats, WorkflowStepStats
from agnostic_spec.v3_1 import WorkflowConfig, parse, shape_errors, step_count
from agnostic_studio.application.access import BRIDGE_CEL, READ_SCOPE, WRITE_SCOPE, StudioAccess, page_items
from agnostic_studio.application.ports import SourceRunner, StudioStore
from agnostic_studio.application.source_jobs import Evaluation, check_job, evaluate_job
from agnostic_studio.application.validation import ValidationReport, Validator
from agnostic_studio.domain.model import CanvasLayout

MAX_EXPRESSION = 4_000
RUN_SESSIONS = 10
MAX_STEP_RUNS = 50
MAX_CONTENT = 2_000
SERVICE_UNAVAILABLE = 503


@dataclass(frozen=True, slots=True)
class WorkflowValidation:
    report: ValidationReport
    step_count: int

    @property
    def sentence(self) -> str:
        """``"11 steps · valid"``: every Step and every container counts as a step."""
        count = f"{self.step_count} step{'s' if self.step_count != 1 else ''}"
        errors = sum(1 for item in self.report.diagnostics if item.severity == "error")
        if errors:
            return f"{count} · {errors} problem{'s' if errors != 1 else ''}"
        return f"{count} · valid"


@dataclass(frozen=True, slots=True)
class CelEvaluation:
    result: Any
    type: str | None
    evaluator: str
    """``agno`` when the instance evaluated it (authoritative), ``agnostic`` for the control plane's evaluator."""
    error: str | None = None
    start: int | None = None
    end: int | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class StepRun:
    run_id: str
    session_id: str
    created_at: int | None
    status: str | None
    content: str | None
    success: bool | None
    error: str | None


class Workflows:
    def __init__(
        self,
        access: StudioAccess,
        validator: Validator,
        store: StudioStore,
        runner: SourceRunner,
        step_stats: StepStats,
    ) -> None:
        self._access = access
        self._validator = validator
        self._store = store
        self._runner = runner
        self._step_stats = step_stats

    async def validate(self, principal: Principal, ref: str, config: dict[str, Any]) -> WorkflowValidation:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        report = await self._validator.validate(principal, instance, "workflow", config)
        count = 0
        if not shape_errors("workflow", config):
            parsed = parse("workflow", config)
            assert isinstance(parsed, WorkflowConfig)
            count = step_count(parsed)
        return WorkflowValidation(report, count)

    # ---------------------------------------------------------------- CEL

    async def check(self, expression: str, context: ContextName, choices: list[str] | None) -> CheckResult:
        _limit(expression)
        return await self._runner.run(check_job, expression, context, choices)

    async def evaluate(
        self,
        principal: Principal,
        ref: str,
        expression: str,
        context: ContextName,
        sample: dict[str, Any],
        choices: list[str] | None,
    ) -> CelEvaluation:
        """With the bridge, agno evaluates it as a run would; otherwise the control plane's own evaluator does."""
        _limit(expression)
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        note: str | None = None
        if BRIDGE_CEL in await self._access.bridge(instance):
            answer = await self._bridge(principal, instance, expression, context, sample, choices)
            if answer is not None:
                return answer
            note = f"{instance.display_name} can't evaluate CEL (cel-python isn't installed), so Agnostic evaluated it."
        else:
            note = (
                f"agnostic-bridge isn't installed on {instance.display_name}, so Agnostic evaluated it; agno's "
                "evaluator decides at run time."
            )
        local: Evaluation = await self._runner.run(evaluate_job, expression, context, sample, choices)
        return CelEvaluation(local.result, local.type, "agnostic", local.error, local.start, local.end, note)

    async def _bridge(
        self,
        principal: Principal,
        instance: Instance,
        expression: str,
        context: ContextName,
        sample: dict[str, Any],
        choices: list[str] | None,
    ) -> CelEvaluation | None:
        body: dict[str, Any] = {"expression": expression, "context": context, **_bridge_sample(context, sample)}
        if context == "router":
            body["step_choices"] = list(choices or [])
        try:
            response = await self._access.call(principal, instance, "POST", "/agnostic/v1/cel/evaluate", body=body)
        except AppError as exc:
            # The gateway turns the bridge's 503 (no cel-python) into a disabled capability.
            if exc.status == SERVICE_UNAVAILABLE:
                return None
            raise
        if response.status == SERVICE_UNAVAILABLE:
            return None
        payload = cast("dict[str, Any]", response.body) if isinstance(response.body, dict) else {}
        if not response.ok:
            return CelEvaluation(None, None, "agno", str(payload.get("error") or payload.get("detail") or "Failed."))
        return CelEvaluation(payload.get("result"), str(payload.get("type") or ""), "agno")

    # ---------------------------------------------------------------- runs

    async def step_stats(
        self, principal: Principal, ref: str, component_id: str, window: RangeName
    ) -> WorkflowStepStats:
        await self._access.instance(principal, ref, READ_SCOPE)
        return await self._step_stats.for_workflow(principal, ref, component_id, window)

    async def step_runs(
        self, principal: Principal, ref: str, component_id: str, step: str, limit: int = 10
    ) -> list[StepRun]:
        """The step's latest results, newest first, from the workflow's most recent sessions."""
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        sessions = page_items(
            await self._access.json(
                principal,
                instance,
                "GET",
                "/sessions",
                params={
                    "type": "workflow",
                    "component_id": component_id,
                    "limit": str(RUN_SESSIONS),
                    "sort_by": "updated_at",
                    "sort_order": "desc",
                },
            )
        )
        found: list[StepRun] = []
        for session in sessions:
            session_id = str(session.get("session_id") or "")
            if not session_id:
                continue
            runs = page_items(
                await self._access.json(
                    principal, instance, "GET", f"/sessions/{session_id}/runs", params={"type": "workflow"}
                )
            )
            for run in sorted(runs, key=lambda item: int(item.get("created_at") or 0), reverse=True):
                found.extend(_step_runs(run, session_id, step))
            if len(found) >= min(limit, MAX_STEP_RUNS):
                break
        return found[: min(limit, MAX_STEP_RUNS)]

    # ---------------------------------------------------------------- canvas

    async def layout(self, principal: Principal, ref: str, component_id: str, version: int) -> CanvasLayout | None:
        instance = await self._access.instance(principal, ref, READ_SCOPE)
        return await self._store.canvas_layout(instance.id, component_id, version)

    async def save_layout(
        self, principal: Principal, ref: str, component_id: str, version: int, layout: dict[str, Any]
    ) -> CanvasLayout:
        instance = await self._access.instance(principal, ref, WRITE_SCOPE)
        saved = CanvasLayout(instance.id, component_id, version, layout, principal.id, utcnow())
        await self._store.save_canvas_layout(saved)
        await self._store.commit()
        return saved


def _limit(expression: str) -> None:
    if not expression.strip() or len(expression) > MAX_EXPRESSION:
        raise ValidationFailedError(f"Write an expression (up to {MAX_EXPRESSION:,} characters).")


def _bridge_sample(context: ContextName, sample: dict[str, Any]) -> dict[str, Any]:
    keys = (
        ("current_iteration", "max_iterations", "all_success", "last_step_content", "step_outputs")
        if context == "loop"
        else ("input", "previous_step_content", "previous_step_outputs", "additional_data", "session_state")
    )
    picked: dict[str, Any] = {key: sample[key] for key in keys if key in sample and sample[key] is not None}
    for key in ("previous_step_outputs", "step_outputs"):
        if isinstance(picked.get(key), dict):
            picked[key] = {str(name): str(value) for name, value in cast("dict[str, Any]", picked[key]).items()}
    return picked


def _step_runs(run: dict[str, Any], session_id: str, step: str) -> list[StepRun]:
    found: list[StepRun] = []

    def walk(results: object) -> None:
        for result in cast("list[Any]", results) if isinstance(results, list) else []:
            if not isinstance(result, dict):
                continue
            item = cast("dict[str, Any]", result)
            if item.get("step_name") == step:
                content = item.get("content")
                found.append(
                    StepRun(
                        run_id=str(run.get("run_id") or ""),
                        session_id=session_id,
                        created_at=cast("int | None", run.get("created_at")),
                        status=cast("str | None", run.get("status")),
                        content=str(content)[:MAX_CONTENT] if content is not None else None,
                        success=cast("bool | None", item.get("success")),
                        error=cast("str | None", item.get("error")),
                    )
                )
            walk(item.get("steps"))

    walk(run.get("step_results"))
    return found
