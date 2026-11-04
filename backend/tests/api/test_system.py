"""The System page: status overview, endpoint checks and failed jobs, for Owners (and read-only Administrators)."""

from collections.abc import AsyncIterator

import pytest

from tests.api.test_instances_gateway import connect, invite_operator
from tests.support.stack import Stack, running_stack


@pytest.fixture
async def stack(sqlite_database: str) -> AsyncIterator[Stack]:
    async with running_stack(sqlite_database) as running:
        yield running


async def test_status_and_checks(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)

    status = await owner.get("/api/v1/system/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["environment"] == "test"
    assert body["versions"]["database"].startswith("sqlite ")
    assert body["versions"]["cache"] == "in-process (development)"
    assert "system" in body["versions"]["modules"]
    assert [item["slug"] for item in body["instances"]] == [instance["slug"]]
    assert {item["name"] for item in body["items"]} >= {"Deliveries", "Webhooks"}
    assert all(item["state"] == "ok" for item in body["items"] if item["name"] in {"Deliveries", "Webhooks"})

    checks = (await owner.post("/api/v1/system/checks")).json()
    by_name = {check["name"]: check for check in checks}
    assert by_name["database"]["ok"] is True
    assert by_name["master key"]["ok"] is True
    assert by_name[f"instance {instance['slug']}"]["ok"] is True
    assert by_name[f"instance {instance['slug']}"]["facts"]["network"] == "gateway"

    stack.routes.runtimes.pop("prod.agentos.test")
    down = {check["name"]: check for check in (await owner.post("/api/v1/system/checks")).json()}
    assert down[f"instance {instance['slug']}"]["ok"] is False


async def test_failed_jobs_need_the_scopes(stack: Stack) -> None:
    owner = await stack.owner()
    assert (await owner.get("/api/v1/system/jobs/failed")).json() == []
    missing = await owner.post("/api/v1/system/jobs/999/retry")
    assert missing.status_code == 404

    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    operator = await invite_operator(stack, owner, instance["id"])
    denied = await operator.get("/api/v1/system/status")
    assert denied.status_code == 403
    assert denied.json()["code"] == "scope_missing"
