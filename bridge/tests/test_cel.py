"""POST /agnostic/v1/cel/evaluate: agno's own CEL evaluation for each workflow context, and its errors."""

from __future__ import annotations

from typing import Any

import pytest
from agno.workflow import cel as agno_cel
from fastapi.testclient import TestClient

from agnostic_bridge import SCOPE_MAPPINGS, install
from tests.conftest import make_os

PATH = "/agnostic/v1/cel/evaluate"
ROUTE_BY_CATEGORY = (
    'input.contains("refund") || input.contains("invoice") ? "Billing"'
    ' : previous_step_content.contains("BUG") ? "Investigate"'
    ' : "Draft & review"'
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(install(make_os()))


def _evaluate(client: TestClient, body: dict[str, Any]) -> Any:
    response = client.post(PATH, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_scope() -> None:
    assert SCOPE_MAPPINGS[f"POST {PATH}"] == ["components:read"]


def test_router_selector(client: TestClient) -> None:
    body = {"expression": ROUTE_BY_CATEGORY, "context": "router", "input": "I was charged twice, need a refund"}
    assert _evaluate(client, body) == {"result": "Billing", "type": "string"}
    body = {**body, "input": "hi", "previous_step_content": "BUG: 502 on login"}
    assert _evaluate(client, body)["result"] == "Investigate"
    choices = {"expression": "step_choices[1]", "context": "router", "step_choices": ["a", "b"]}
    assert _evaluate(client, choices)["result"] == "b"


def test_condition_evaluator(client: TestClient) -> None:
    body = {
        "expression": 'previous_step_outputs.classify.contains("ESCALATE") && session_state.tier == "gold"',
        "context": "condition",
        "previous_step_outputs": {"classify": "ESCALATE now"},
        "session_state": {"tier": "gold"},
    }
    assert _evaluate(client, body) == {"result": True, "type": "bool"}
    assert _evaluate(client, {**body, "session_state": {"tier": "free"}})["result"] is False


def test_loop_end_condition(client: TestClient) -> None:
    body = {
        "expression": 'last_step_content.contains("APPROVED") && all_success && current_iteration <= max_iterations',
        "context": "loop",
        "step_outputs": {"Draft reply": "Hi!", "Review tone": "APPROVED"},
        "current_iteration": 2,
    }
    assert _evaluate(client, body)["result"] is True
    assert _evaluate(client, {**body, "all_success": False})["result"] is False
    alone = {"expression": 'last_step_content == "done"', "context": "loop", "last_step_content": "done"}
    assert _evaluate(client, alone)["result"] is True


def test_errors_are_422(client: TestClient) -> None:
    response = client.post(PATH, json={"expression": "missing_variable", "context": "condition"})
    assert response.status_code == 422
    assert "Failed to evaluate CEL expression" in response.json()["error"]


def test_without_cel_python(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agno_cel, "CEL_AVAILABLE", False)
    response = client.post(PATH, json={"expression": "true", "context": "condition"})
    assert response.status_code == 503


def test_capabilities_report_cel(client: TestClient) -> None:
    features = client.get("/agnostic/v1/capabilities").json()["features"]
    assert features["cel"] is True
