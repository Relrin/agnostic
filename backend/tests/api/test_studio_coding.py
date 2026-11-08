"""Coding agents in Studio: the template, and the bridge's refresh after a publish (only where the bridge offers it)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.api.test_instances_gateway import connect
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

STAGING = "/api/v1/instances/staging-agentos"
PROD = "/api/v1/instances/prod-agentos"
CODER = {
    "name": "mock-coder",
    "type": "model",
    "metadata": {"class_path": "app.models.mock.MockModel", "provider": "Agnostic", "model_id": "mock-coder"},
}


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


async def instances(stack: Stack, owner: httpx.AsyncClient) -> tuple[FakeAgentOS, FakeAgentOS]:
    staging = stack.runtime("staging.agentos.test", os_id="fake-staging", name="Fake staging")
    prod = stack.runtime("prod.agentos.test")
    await connect(owner, staging, "http://staging.agentos.test:7777", display_name="staging-agentos", env_tag="staging")
    await connect(owner, prod)
    for fake in (staging, prod):
        fake.registry_items = [CODER]
    staging.bridge = staging.bridge_coding = True
    prod.bridge = True
    return staging, prod


async def create_and_publish(owner: httpx.AsyncClient, base: str, name: str) -> dict[str, Any]:
    created = await owner.post(
        f"{base}/studio/components",
        json={"kind": "agent", "name": name, "mode": "template", "template_id": "coding-agent"},
    )
    assert created.status_code == 201, created.text
    published = await owner.post(f"{base}/studio/components/{name}/configs/1/publish", json={})
    assert published.status_code == 200, published.text
    return created.json()["draft"]["config"]


async def test_coding_agent_template_publishes_and_refreshes_the_bridge(stack: Stack) -> None:
    owner = await stack.owner()
    staging, prod = await instances(stack, owner)

    templates = (await owner.get("/api/v1/studio/templates", params={"kind": "agent"})).json()
    coding = next(item for item in templates if item["id"] == "coding-agent")
    assert coding["description"] == "Pi in a Docker sandbox; files written to outputs/ become artefacts."

    config = await create_and_publish(owner, STAGING, "pi-coder")
    assert config["metadata"] == {"agnostic": {"coding_agent": {"harness": "pi"}}}
    assert config["model"]["id"] == "mock-coder"
    assert staging.coding_refreshes == 1

    # Without the endpoint in the bridge's capabilities, nothing is called and the publish still succeeds.
    _ = await create_and_publish(owner, PROD, "pi-coder")
    assert prod.coding_refreshes == 0
    assert not any(call["path"] == "/agnostic/v1/coding-agents/refresh" for call in prod.calls)


async def test_a_failing_refresh_never_fails_the_publish(stack: Stack) -> None:
    owner = await stack.owner()
    staging, _ = await instances(stack, owner)
    staging.coding_refresh_status = 503

    _ = await create_and_publish(owner, STAGING, "pi-coder")
    assert staging.coding_refreshes == 1
    assert staging.components["pi-coder"]["current_version"] == 1
