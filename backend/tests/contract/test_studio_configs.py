"""Contract tests for Studio configs: every golden agent config, and the full and prototype workflows, go through the
typed model, are stored as AgentOS components, read back and normalized by the bridge (agno's own
``from_dict().to_dict()``) without losing anything; the workflows also run.

Skipped when ``AGNOSTIC_CONTRACT_RUNTIME_URL`` is unset (see ``test_agentos_runtime.py``).
"""

import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agnostic_agentos_client import AgentOSClient
from agnostic_spec.v3_1 import parse

pytestmark = pytest.mark.contract

RUNTIME_URL = os.environ.get("AGNOSTIC_CONTRACT_RUNTIME_URL")
GOLDEN = Path(__file__).parents[1] / "golden" / "agno-3.1" / "agents"


@pytest.fixture
async def runtime() -> AsyncIterator[AgentOSClient]:
    if not RUNTIME_URL:
        pytest.skip("AGNOSTIC_CONTRACT_RUNTIME_URL is not set")
    async with AgentOSClient(RUNTIME_URL, retries=5, backoff=0.5) as client:
        yield client


@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*.json")), ids=lambda path: path.stem)
async def test_golden_agent_round_trips_through_components(runtime: AgentOSClient, path: Path) -> None:
    config: dict[str, Any] = parse("agent", json.loads(path.read_text(encoding="utf-8"))).dump()  # noqa: ASYNC240
    component_id = f"contract-{path.stem}-{uuid.uuid4().hex[:8]}"
    config = {**config, "id": component_id}
    created = await runtime.request_json(
        "POST",
        "/components",
        json={"name": component_id, "component_type": "agent", "component_id": component_id, "config": config},
    )
    assert created["component_id"] == component_id
    try:
        stored = await runtime.get_json(f"/components/{component_id}/configs/1")
        assert parse("agent", stored["config"]).dump() == config
        normalized = await runtime.request_json(
            "POST", "/agnostic/v1/components/normalize", json={"kind": "agent", "config": stored["config"]}
        )
        assert parse("agent", normalized["config"]).dump() == config
        checked = await runtime.request_json(
            "POST", "/agnostic/v1/components/validate", json={"kind": "agent", "config": stored["config"]}
        )
        assert checked["valid"] is True, checked["errors"]
    finally:
        await runtime.request_json("DELETE", f"/components/{component_id}")


WORKFLOWS = Path(__file__).parents[1] / "golden" / "agno-3.1"
STUDIO_WORKFLOWS = [
    WORKFLOWS / "workflows" / "golden-full-workflow.json",
    WORKFLOWS / "prototype" / "ticket-router.json",
]


def _without_step_ids(value: Any) -> Any:
    """agno gives a step stored without an id a new one on every load."""
    if isinstance(value, list):
        return [_without_step_ids(item) for item in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, dict):
        return {key: _without_step_ids(item) for key, item in value.items() if key != "step_id"}  # pyright: ignore[reportUnknownVariableType]
    return value


def _run_message(config: dict[str, Any]) -> str:
    """agno validates a run's input against the workflow's ``input_schema``; the goldens only use ``TriageResult``."""
    if config.get("input_schema") == "TriageResult":
        return json.dumps({"category": "billing", "urgency": "high", "needs_human": True})
    return "I was charged twice, need a refund"


@pytest.mark.parametrize("path", STUDIO_WORKFLOWS, ids=lambda path: path.stem)
async def test_golden_workflow_round_trips_and_runs(runtime: AgentOSClient, path: Path) -> None:
    config: dict[str, Any] = parse("workflow", json.loads(path.read_text(encoding="utf-8"))).dump()  # noqa: ASYNC240
    component_id = f"contract-{path.stem}-{uuid.uuid4().hex[:8]}"
    # Studio always writes the name; a traced runtime can't run a workflow without one.
    config = {**config, "id": component_id, "name": config.get("name") or component_id}
    await runtime.request_json(
        "POST",
        "/components",
        json={"name": component_id, "component_type": "workflow", "component_id": component_id, "config": config},
    )
    try:
        stored = await runtime.get_json(f"/components/{component_id}/configs/1")
        assert parse("workflow", stored["config"]).dump() == config
        normalized = await runtime.request_json(
            "POST", "/agnostic/v1/components/normalize", json={"kind": "workflow", "config": stored["config"]}
        )
        normalized_config = parse("workflow", normalized["config"]).dump()
        assert _without_step_ids(normalized_config) == _without_step_ids(config)
        run = await runtime.request_json(
            "POST",
            f"/workflows/{component_id}/runs",
            form={"message": _run_message(config), "stream": "false", "version": "1"},
        )
        assert run.get("status") in {"COMPLETED", "PAUSED"}, run
    finally:
        await runtime.request_json("DELETE", f"/components/{component_id}")
