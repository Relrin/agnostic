"""The workflow builder against a fake AgentOS: a workflow from a template, the design's ticket router built as a
config and validated (structure, executors, CEL) with its step count, saved with its executors pinned, its code
generated, read back, edited from the form and kept as the draft's code, CEL checked and tried with and without the
instance's own evaluator, per-step stats and runs, the canvas layout, and a draft test run streaming step events."""

import copy
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from tests.api.test_instances_gateway import connect
from tests.api.test_observe_evals import daily_brief_pair
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack
from tests.unit.test_prototype_ticket_router import PROTOTYPE

STAGING = "/api/v1/instances/staging-agentos"
WORKFLOW = f"{STAGING}/studio/components/ticket-router"
GOLDEN = Path(__file__).parents[1] / "golden" / "agno-3.1" / "prototype" / "ticket-router.json"
ROUTE_BY_CATEGORY = (
    'input.contains("refund") || input.contains("invoice") ? "Billing"'
    ' : previous_step_content.contains("BUG") ? "Investigate"'
    ' : "Draft & review"'
)
CHOICES = ["Billing", "Investigate", "Draft & review"]


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


def registry() -> list[dict[str, Any]]:
    components = [
        *(
            {"name": name, "id": name, "type": "agent", "metadata": {"class_path": "agno.agent.Agent"}}
            for name in (
                "support-triage",
                "kb-researcher",
                "qa-reviewer",
            )
        ),
        {
            "name": "escalation-team",
            "id": "escalation-team",
            "type": "team",
            "metadata": {"class_path": "agno.team.Team"},
        },
    ]
    functions = [
        {
            "name": name,
            "type": "function",
            "metadata": {"module": "app.functions", "signature": f"{name}(step_input: StepInput) -> StepOutput"},
        }
        for name in ("check_status", "send_reply")
    ]
    return [*components, *functions]


async def staging_instance(stack: Stack) -> tuple[Any, FakeAgentOS]:
    owner = await stack.owner()
    staging = stack.runtime("staging.agentos.test", os_id="fake-staging", name="Fake staging")
    await connect(owner, staging, "http://staging.agentos.test:7777", display_name="staging-agentos", env_tag="staging")
    staging.registry_items = registry()
    return owner, staging


def prototype_config() -> dict[str, Any]:
    return {**json.loads(GOLDEN.read_text(encoding="utf-8")), "name": "ticket-router"}


async def test_ticket_router_from_the_canvas_to_a_test_run(stack: Stack) -> None:  # noqa: PLR0915  (the journey)
    owner, staging = await staging_instance(stack)

    # ------------------------------------------------ templates and schema for the builder
    templates = (await owner.get("/api/v1/studio/templates", params={"kind": "workflow"})).json()
    assert [item["id"] for item in templates] == ["blank-workflow", "triage-and-route"]
    schema = (await owner.get("/api/v1/studio/schema/workflow")).json()
    assert schema["x-agnostic-human-review"]["support"]["Parallel"] == []
    assert {section["id"] for section in schema["x-agnostic-nodes"]["Step"]} >= {"settings", "executor", "review"}

    # ------------------------------------------------ a stored agent the router runs, so its step gets pinned
    billing = await owner.post(f"{STAGING}/studio/components", json={"kind": "agent", "name": "billing-agent"})
    assert billing.status_code == 201, billing.text
    staging.components["billing-agent"]["current_version"] = 1

    created = await owner.post(
        f"{STAGING}/studio/components", json={"kind": "workflow", "name": "ticket-router", "mode": "blank"}
    )
    assert created.status_code == 201, created.text
    detail = created.json()
    assert detail["editable"] is True
    assert detail["draft"]["config"]["id"] == "ticket-router"
    assert "model" not in detail["draft"]["config"]
    listed = (await owner.get(f"{STAGING}/studio/components", params={"kind": "workflow"})).json()
    assert [(row["component"]["id"], row["editable"]) for row in listed] == [("ticket-router", True)]

    # ------------------------------------------------ the design's ticket router, validated with its step count
    config = prototype_config()
    checked = await owner.post(f"{STAGING}/studio/workflows/validate", json={"config": config})
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["sentence"] == "12 steps · valid", body
    assert body["step_count"] == 12
    layers = {layer["id"]: layer["status"] for layer in body["validation"]["layers"]}
    assert layers == {"shape": "ok", "registry": "ok", "rules": "ok", "cel": "ok", "bridge": "skipped"}

    broken = copy.deepcopy(config)
    broken["steps"][1]["selector"] = 'input.contains("refund") ? "Refund" : "Billing"'
    broken["steps"][2]["steps"][0].pop("team_id")
    broken["steps"][1]["choices"][1]["steps"][0]["human_review"] = {"requires_confirmation": True}
    problems = (await owner.post(f"{STAGING}/studio/workflows/validate", json={"config": broken})).json()
    assert problems["sentence"] == "12 steps · 3 problems"
    found = {
        (item["path"], item["code"]) for layer in problems["validation"]["layers"] for item in layer["diagnostics"]
    }
    assert ("steps[1].selector", "cel.router_unknown_choice") in found
    assert ("steps[2].steps[0]", "executor_missing") in found
    assert ("steps[1].choices[1].steps[0].human_review", "review_in_parallel") in found

    # ------------------------------------------------ saved with the stored executor pinned
    saved = await owner.patch(f"{WORKFLOW}/configs/1", json={"config": config, "revision": detail["draft"]["revision"]})
    assert saved.status_code == 200, saved.text
    patch = staging.config_patches[-1]["body"]
    assert patch["config"]["steps"][1]["selector"] == ROUTE_BY_CATEGORY
    assert patch["links"] == [
        {
            "link_kind": "step_agent",
            "link_key": "Billing",
            "child_component_id": "billing-agent",
            "child_version": 1,
            "position": 0,
        }
    ]
    revision = saved.json()["revision"]

    # ------------------------------------------------ generated code, read back, edited from the form
    generated = (await owner.post(f"{STAGING}/studio/codegen", json={"kind": "workflow", "config": config})).json()
    assert generated["filename"] == "workflows/ticket_router.py"
    assert "ROUTE_BY_CATEGORY = (" in generated["code"]
    router = generated["spans"]["steps[1]"]
    assert generated["code"].splitlines()[router["line"] - 1].strip() == "Router("

    parsed = await owner.post(
        f"{STAGING}/studio/parse", json={"kind": "workflow", "code": PROTOTYPE, "component_id": "ticket-router"}
    )
    assert parsed.status_code == 200, parsed.text
    reading = parsed.json()
    assert reading["ok"] is True
    assert reading["config"] == {key: value for key, value in config.items() if key != "name"}
    assert reading["spans"]["steps[1].choices[1]"]["line"] == 12
    assert reading["ruff"]["available"] is True

    edited = copy.deepcopy(config)
    edited["steps"][1]["choices"][2]["max_iterations"] = 5
    transformed = await owner.post(
        f"{STAGING}/studio/transform",
        json={"kind": "workflow", "code": PROTOTYPE, "config": edited, "component_id": "ticket-router"},
    )
    assert transformed.status_code == 200, transformed.text
    result = transformed.json()
    assert result["equivalent"] is True, result["diagnostics"]
    assert result["changed"] == ["name", "steps", "steps[1].choices[2].max_iterations"]
    assert '    name="ticket-router",\n' in result["code"]
    assert "    max_iterations=5,\n" in result["code"]
    assert "ROUTE_BY_CATEGORY = (\n" in result["code"]

    # ------------------------------------------------ the draft keeps its code
    kept = await owner.patch(
        f"{WORKFLOW}/configs/1", json={"config": edited, "revision": revision, "code": result["code"]}
    )
    assert kept.status_code == 200, kept.text
    document = (await owner.get(f"{WORKFLOW}/configs/1/code")).json()
    assert document["code_backed"] is True
    assert document["code"] == result["code"]
    assert document["stale"] is False
    mismatch = await owner.patch(
        f"{WORKFLOW}/configs/1", json={"config": config, "revision": kept.json()["revision"], "code": result["code"]}
    )
    assert mismatch.status_code == 422
    staging.configs["ticket-router"][1]["config"]["description"] = "Edited straight on AgentOS"
    assert (await owner.get(f"{WORKFLOW}/configs/1/code")).json()["stale"] is True

    # ------------------------------------------------ CEL: checked in its context, tried on a sample
    cel = await owner.post(
        "/api/v1/studio/cel/check", json={"expression": ROUTE_BY_CATEGORY, "context": "router", "choices": CHOICES}
    )
    assert cel.status_code == 200, cel.text
    assert cel.json()["summary"] == "Returns string · every result matches a choice"
    assert cel.json()["exhaustive"] is True
    contexts = (await owner.get("/api/v1/studio/cel/contexts")).json()
    assert [item["name"] for item in contexts["contexts"]["loop"]["variables"]][:2] == [
        "current_iteration",
        "max_iterations",
    ]
    sample = {"input": "I was charged twice, need a refund"}
    request = {"expression": ROUTE_BY_CATEGORY, "context": "router", "sample": sample, "choices": CHOICES}
    local = (await owner.post(f"{STAGING}/studio/cel/evaluate", json=request)).json()
    assert (local["result"], local["evaluator"]) == ("Billing", "agnostic")
    assert "agnostic-bridge isn't installed" in local["note"]
    failing = (
        await owner.post(f"{STAGING}/studio/cel/evaluate", json={"expression": "nope.size() > 0", "context": "loop"})
    ).json()
    assert failing["error"] == "undeclared reference to 'nope'"
    assert failing["span"] == {"start": 0, "end": 4}

    staging.bridge = True
    staging.bridge_cel = True
    await owner.post(f"{STAGING}/studio/registry/refresh")
    agno = (await owner.post(f"{STAGING}/studio/cel/evaluate", json=request)).json()
    assert (agno["result"], agno["evaluator"], agno["note"]) == ("Billing", "agno", None)
    assert staging.cel_requests[-1]["step_choices"] == CHOICES
    staging.bridge_cel_installed = False
    answered = await owner.post(f"{STAGING}/studio/cel/evaluate", json=request)
    assert answered.status_code == 200, answered.text
    fallback = answered.json()
    assert fallback["evaluator"] == "agnostic"
    assert "cel-python isn't installed" in fallback["note"]

    # ------------------------------------------------ per-step stats from traces, step results from runs
    daily_brief_pair(staging)
    stats = (await owner.get(f"{STAGING}/studio/components/daily-brief/step-stats", params={"window": "7d"})).json()
    assert stats["traces_scanned"] == 2
    assert {step["name"] for step in stats["steps"]} == {"Gather news", "Write brief"}  # steps only, no agent spans
    staging.session_items = [{"session_id": "ses_w1", "user_id": None, "updated_at": 1, "created_at": 1}]
    staging.session_runs["ses_w1"] = [
        {
            "run_id": "run_w1",
            "created_at": 100,
            "status": "COMPLETED",
            "step_results": [
                {"step_name": "Classify ticket", "content": "BILLING", "success": True},
                {"step_name": "Route by category", "steps": [{"step_name": "Billing", "content": "Refunded."}]},
            ],
        }
    ]
    runs = (await owner.get(f"{WORKFLOW}/step-runs", params={"step": "Billing"})).json()
    assert [(run["run_id"], run["content"]) for run in runs] == [("run_w1", "Refunded.")]

    # ------------------------------------------------ the canvas layout a person adjusted
    empty = (await owner.get(f"{WORKFLOW}/canvas-layout", params={"version": 1})).json()
    assert empty["layout"] == {}
    layout = {"positions": {"steps[1]": {"x": 40, "y": 0}}, "collapsed": ["steps[1].choices[2]"], "viewport": {}}
    put = await owner.put(f"{WORKFLOW}/canvas-layout", json={"version": 1, "layout": layout})
    assert put.status_code == 200, put.text
    assert (await owner.get(f"{WORKFLOW}/canvas-layout", params={"version": 1})).json()["layout"] == layout

    # ------------------------------------------------ the draft runs with step events
    async with owner.stream(
        "POST", f"{WORKFLOW}/test-runs", json={"message": "I was charged twice", "version": 1}
    ) as response:
        assert response.status_code == 200
        streamed = b"".join([chunk async for chunk in response.aiter_bytes()]).decode()
    assert "event: RouterExecutionStarted" in streamed
    assert '"step_name":"Classify ticket"' in streamed
    assert "event: WorkflowCompleted" in streamed
    assert staging.run_requests[-1]["workflow_id"] == "ticket-router"
    assert staging.run_requests[-1]["form"]["version"] == "1"
