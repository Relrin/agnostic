"""The request body of one eval run: AgentOS ``POST /eval-runs`` or the bridge's version-pinned twin."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agnostic_evals.domain.model import LOW_SCORE, Batch, Case

PARAMS = ("scoring_strategy", "threshold", "num_iterations", "warmup_runs", "allow_additional_tool_calls")


def run_name(batch: Batch, position: int) -> str:
    return f"{batch.name} · case {position}"[:255]


def run_input(batch: Batch, case: Case) -> dict[str, Any]:
    """The ``EvalRunInput`` fields agno expects; through the bridge also the target version and the judge model.

    AgentOS ``/eval-runs`` reads ``model_id`` as a model to swap into the evaluated component, so the judge is only
    sent to the bridge, which uses it for the evaluator alone.
    """
    body: dict[str, Any] = {
        "eval_type": batch.eval_type,
        "input": case.input,
        "name": run_name(batch, case.position),
    }
    if case.expected_output:
        body["expected_output"] = case.expected_output
    if case.criteria:
        body["criteria"] = case.criteria
        body["scoring_strategy"] = "numeric"
        body["threshold"] = round(LOW_SCORE)
    if case.expected_tool_calls:
        body["expected_tool_calls"] = list(case.expected_tool_calls)
    arguments = case.metadata.get("expected_tool_call_arguments")
    if isinstance(arguments, Mapping) and arguments:
        body["expected_tool_call_arguments"] = dict(arguments)  # pyright: ignore[reportUnknownArgumentType]
    for key in PARAMS:
        if batch.params.get(key) is not None:
            body[key] = batch.params[key]
    target = batch.target
    if batch.via_bridge:
        body["component_type"] = target.kind
        body["component_id"] = target.component_id
        body["version"] = target.version
        if batch.judge is not None:
            body["model_id"] = batch.judge.model_id
            body["model_provider"] = batch.judge.provider
    else:
        body[f"{target.kind}_id"] = target.component_id
    return body


def run_path(batch: Batch) -> str:
    return "/agnostic/v1/evals/run" if batch.via_bridge else "/eval-runs"
