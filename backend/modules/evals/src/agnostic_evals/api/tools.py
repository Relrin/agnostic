"""Assistant tool over evaluation results: recent evaluations, or two evaluations compared case by case."""

from __future__ import annotations

from typing import Literal

from dishka import AsyncContainer
from pydantic import BaseModel, Field

from agnostic_evals.application.access import READ_SCOPE
from agnostic_evals.application.batches import Batches, EvaluationRow, ListEvaluations
from agnostic_evals.domain.compare import CaseChange
from agnostic_evals.domain.model import Item
from agnostic_kernel.tools import Source, ToolCall, ToolResult, ToolSpec, clip

MAX_CASES = 20


class EvalResultsArgs(BaseModel):
    component_id: str | None = Field(None, description="Only evaluations of this agent, team or workflow")
    eval_type: Literal["accuracy", "agent_as_judge", "reliability", "performance"] | None = None
    evaluation_id: str | None = Field(None, description="Compare this evaluation (batch id) …")
    compare_to_id: str | None = Field(None, description="… with this one, case by case (same dataset)")
    limit: int = Field(10, ge=1, le=25)


def evaluation_source(call: ToolCall, evaluation_id: str, name: str) -> Source:
    return Source("evaluation", f"Evaluation {name}", f"/i/{call.instance_slug}/evals?evaluation={evaluation_id}")


def _row(row: EvaluationRow) -> dict[str, object]:
    return {
        "id": row.id,
        "name": row.name,
        "type": row.eval_type,
        "component": f"{row.component_kind}:{row.component_id}" if row.component_id else None,
        "version": row.version_label,
        "dataset": row.dataset_name,
        "cases": row.case_count,
        "result": row.result,
        "bad": row.bad,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _side(item: Item | None) -> dict[str, object] | None:
    if item is None:
        return None
    outcome = item.outcome
    return {
        "status": item.status,
        "score": outcome.score if outcome else None,
        "passed": outcome.passed if outcome else None,
        "reason": clip(outcome.reason if outcome else item.error, 300),
    }


def _case(row: CaseChange) -> dict[str, object]:
    return {
        "case": row.position + 1,
        "change": row.change,
        "input": clip(row.input, 300),
        "expected": clip(row.expected, 300),
        "before": _side(row.before),
        "after": _side(row.after),
    }


async def list_eval_results(container: AsyncContainer, call: ToolCall) -> ToolResult:
    args = call.arguments
    assert isinstance(args, EvalResultsArgs)
    if args.evaluation_id and args.compare_to_id:
        compared = await (await container.get(Batches)).compare(
            call.principal, call.instance_id, args.evaluation_id, args.compare_to_id
        )
        changed = [row for row in compared.rows if row.change != "same"]
        return ToolResult(
            {
                "before": {
                    "id": compared.before.id,
                    "name": compared.before.name,
                    "version": compared.before.target.label,
                },
                "after": {"id": compared.after.id, "name": compared.after.name, "version": compared.after.target.label},
                "regressions": compared.counts.regressions,
                "fixes": compared.counts.fixes,
                "below_threshold_before": compared.counts.below_before,
                "below_threshold_after": compared.counts.below_after,
                "insight": compared.insight,
                "changed_cases": [_case(row) for row in changed[:MAX_CASES]],
            },
            [
                evaluation_source(call, compared.before.id, compared.before.name),
                evaluation_source(call, compared.after.id, compared.after.name),
            ],
        )
    found = await (await container.get(ListEvaluations))(
        call.principal,
        call.instance_id,
        eval_type=args.eval_type,
        component_id=args.component_id,
        model=None,
        limit=args.limit,
    )
    rows = found.rows[: args.limit]
    return ToolResult(
        {"evaluations": [_row(row) for row in rows], "standalone_unavailable": found.standalone_unavailable},
        [evaluation_source(call, row.id, row.name) for row in rows[:5]],
    )


TOOLS = (
    ToolSpec(
        "list_eval_results",
        "Recent evaluation results (scores, pass rates) per component and version. With evaluation_id and "
        "compare_to_id: regressions, fixes and changed cases between two evaluations of the same dataset.",
        list_eval_results,
        EvalResultsArgs,
        READ_SCOPE,
    ),
)
