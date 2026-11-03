"""Contract tests for Studio configs: every golden agent config goes through the typed model, is stored as an AgentOS
component, read back and normalized by the bridge (agno's own ``from_dict().to_dict()``) without losing anything.

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
