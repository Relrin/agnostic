"""Workflow configs: agno's full ``to_dict()`` shape from partial configs, node paths, counts, references and rules."""

from typing import Any

import pytest

from agnostic_spec.v3_1 import (
    HUMAN_REVIEW_SUPPORT,
    WorkflowConfig,
    check,
    iter_nodes,
    iter_refs,
    json_schema,
    looks_like_cel,
    parse,
    shape_errors,
    step_count,
)
from agnostic_spec.v3_1.workflow import default_review

ROUTER: dict[str, Any] = {
    "id": "router",
    "steps": [
        {"type": "Step", "name": "Classify", "agent_id": "support-triage"},
        {
            "type": "Router",
            "name": "Route",
            "selector": 'input.contains("refund") ? "Refund" : "Answer"',
            "choices": [
                {"name": "Refund", "executor_ref": "refund"},
                {
                    "type": "Loop",
                    "name": "Answer",
                    "steps": [{"type": "Step", "name": "Draft", "team_id": "escalation-team"}],
                    "end_condition": "is_done",
                },
            ],
        },
    ],
}


def workflow(steps: list[dict[str, Any]]) -> WorkflowConfig:
    parsed = parse("workflow", {"id": "w", "steps": steps})
    assert isinstance(parsed, WorkflowConfig)
    return parsed


def test_a_partial_config_dumps_as_agno_writes_it() -> None:
    dumped = parse("workflow", ROUTER).dump()
    assert dumped["stream_executor_events"] is True
    assert dumped["telemetry"] is True
    step = dumped["steps"][0]
    assert step["type"] == "Step"
    assert step["step_id"] is None
    assert step["max_retries"] == 3
    assert step["human_review"] == default_review("Step")
    router = dumped["steps"][1]
    assert router["selector_type"] == "cel"
    loop = router["choices"][1]
    assert loop["end_condition_type"] == "function"
    assert loop["max_iterations"] == 3
    assert router["choices"][0]["type"] == "Step"
    assert parse("workflow", dumped).dump() == dumped


def test_review_defaults_follow_agno() -> None:
    condition = {"type": "Condition", "name": "C", "steps": [{"name": "A", "agent_id": "a"}]}
    assert workflow([condition]).dump()["steps"][0]["human_review"]["on_reject"] == "else"
    reviewed = {**condition, "human_review": {"requires_confirmation": True}}
    assert workflow([reviewed]).dump()["steps"][0]["human_review"]["on_reject"] == "skip"
    assert workflow([condition]).dump()["steps"][0]["evaluator"] is True


def test_nodes_paths_counts_and_refs() -> None:
    config = parse("workflow", ROUTER)
    assert isinstance(config, WorkflowConfig)
    assert [info.path for info in iter_nodes(config)] == [
        "steps[0]",
        "steps[1]",
        "steps[1].choices[0]",
        "steps[1].choices[1]",
        "steps[1].choices[1].steps[0]",
    ]
    assert step_count(config) == 5
    assert [(use.path, use.type, use.name) for use in iter_refs(config)] == [
        ("steps[0]", "agent", "support-triage"),
        ("steps[1].choices[0]", "function", "refund"),
        ("steps[1].choices[1].end_condition", "function", "is_done"),
        ("steps[1].choices[1].steps[0]", "team", "escalation-team"),
    ]


def test_cel_or_function_like_agno() -> None:
    assert looks_like_cel('input.contains("x")')
    assert looks_like_cel("a == b")
    assert not looks_like_cel("is_done")
    assert not looks_like_cel("check status")


@pytest.mark.parametrize(
    ("steps", "codes"),
    [
        ([], {"steps_missing"}),
        ([{"name": "A"}], {"executor_missing"}),
        ([{"name": "A", "agent_id": "a", "team_id": "t"}], {"executor_multiple"}),
        ([{"agent_id": "a"}], {"step_name_missing"}),
        ([{"name": "A", "agent_id": "a"}, {"name": "A", "agent_id": "b"}], {"step_name_duplicate"}),
        (
            [{"name": "A", "step_id": "x", "agent_id": "a"}, {"name": "B", "step_id": "x", "agent_id": "b"}],
            {"step_id_duplicate"},
        ),
        ([{"type": "Router", "name": "R", "selector": "input", "choices": []}], {"choices_missing"}),
        ([{"type": "Router", "name": "R", "choices": [{"name": "A", "agent_id": "a"}]}], {"selector_missing"}),
        ([{"type": "Condition", "name": "C", "steps": []}], {"children_missing"}),
        (
            [{"type": "Loop", "name": "L", "max_iterations": 0, "steps": [{"name": "A", "agent_id": "a"}]}],
            {"max_iterations_invalid"},
        ),
        (
            [
                {
                    "type": "Parallel",
                    "name": "P",
                    "steps": [{"name": "A", "agent_id": "a", "human_review": {"requires_confirmation": True}}],
                }
            ],
            {"review_in_parallel"},
        ),
        (
            [
                {
                    "type": "Loop",
                    "name": "L",
                    "steps": [{"name": "A", "agent_id": "a"}],
                    "human_review": {"requires_output_review": True},
                }
            ],
            {"review_unsupported"},
        ),
        (
            [
                {
                    "name": "A",
                    "agent_id": "a",
                    "human_review": {"requires_output_review": True, "requires_iteration_review": True},
                }
            ],
            {"review_unsupported", "review_exclusive"},
        ),
        (
            [
                {
                    "type": "Steps",
                    "name": "S",
                    "steps": [{"name": "A", "agent_id": "a"}],
                    "human_review": {"timeout": 60},
                }
            ],
            {"review_option_unused"},
        ),
    ],
)
def test_rules(steps: list[dict[str, Any]], codes: set[str]) -> None:
    found = {diagnostic.code for diagnostic in check(workflow(steps))}
    assert codes <= found, found


def test_nesting_depth_is_capped() -> None:
    node: dict[str, Any] = {"name": "leaf", "agent_id": "a"}
    for level in range(11):
        node = {"type": "Steps", "name": f"level {level}", "steps": [node]}
    assert "nesting_too_deep" in {diagnostic.code for diagnostic in check(workflow([node]))}


def test_a_valid_workflow_has_no_errors() -> None:
    found = [diagnostic for diagnostic in check(parse("workflow", ROUTER)) if diagnostic.severity == "error"]
    assert found == []


def test_shape_errors_name_the_node() -> None:
    errors = shape_errors("workflow", {"steps": [{"type": "Step", "name": "A", "max_retries": "many"}]})
    assert [error.path for error in errors] == ["steps[0].max_retries"]
    assert shape_errors("workflow", {"steps": [{"type": "Nope"}]})


def test_schema_carries_the_inspector_layout() -> None:
    schema = json_schema("workflow")
    assert schema["x-agnostic-human-review"]["support"]["Parallel"] == []
    assert schema["x-agnostic-human-review"]["support"] == {
        key: list(value) for key, value in HUMAN_REVIEW_SUPPORT.items()
    }
    router = {section["id"]: section["fields"] for section in schema["x-agnostic-nodes"]["Router"]}
    assert router["settings"] == ["name", "description", "selector"]
    assert "StepNode" in schema["$defs"]
