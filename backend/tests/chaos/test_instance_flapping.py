"""A runtime that keeps going away and coming back: the gateway's circuit opens, fails fast and closes again, and the
health status follows the runtime and settles once it stays up."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from agnostic_instances.application.use_cases import CheckHealth
from tests.api.test_instances_gateway import connect
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

pytestmark = pytest.mark.chaos

HOST = "prod.agentos.test"
THRESHOLD = 3
COOLDOWN = 1.0


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_GATEWAY__CIRCUIT_FAILURES", str(THRESHOLD))
    monkeypatch.setenv("AGNOSTIC_GATEWAY__CIRCUIT_COOLDOWN_SECONDS", str(COOLDOWN))
    async with running_stack(sqlite_database) as running:
        yield running


def runtime_calls(stack: Stack) -> int:
    return sum(1 for _, host, _ in stack.routes.requests if host == HOST)


def down(stack: Stack) -> FakeAgentOS:
    return stack.routes.runtimes.pop(HOST)


def up(stack: Stack, fake: FakeAgentOS) -> None:
    stack.routes.runtimes[HOST] = fake


async def check_health(stack: Stack) -> dict[str, str]:
    async with stack.container() as request:
        return await (await request.get(CheckHealth))()


async def status(owner: httpx.AsyncClient, instance_id: str) -> Any:
    return (await owner.get(f"/api/v1/instances/{instance_id}")).json()["status"]


async def test_circuit_opens_fails_fast_and_recovers(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime(HOST)
    instance = await connect(owner, fake)
    sessions = f"/api/v1/instances/{instance['id']}/os/sessions"
    assert (await owner.get(sessions)).status_code == 200

    fake = down(stack)
    for _ in range(THRESHOLD):
        failed = await owner.get(sessions)
        assert failed.status_code == 502
        assert failed.json()["code"] == "instance_unreachable"

    # Open: no call reaches the runtime, even once it is back, until the cooldown is over.
    up(stack, fake)
    before = runtime_calls(stack)
    for _ in range(5):
        fast = await owner.get(sessions)
        assert fast.status_code == 502
        assert fast.json()["retry_after"] <= COOLDOWN
    assert runtime_calls(stack) == before

    await asyncio.sleep(COOLDOWN + 0.2)
    assert (await owner.get(sessions)).status_code == 200  # half-open probe succeeds: closed again
    for _ in range(THRESHOLD + 2):
        assert (await owner.get(sessions)).status_code == 200


async def test_failed_probe_reopens_the_circuit(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime(HOST)
    instance = await connect(owner, fake)
    sessions = f"/api/v1/instances/{instance['id']}/os/sessions"

    _ = down(stack)
    for _ in range(THRESHOLD):
        assert (await owner.get(sessions)).status_code == 502
    await asyncio.sleep(COOLDOWN + 0.2)

    before = runtime_calls(stack)
    assert (await owner.get(sessions)).status_code == 502  # the half-open probe, still down
    assert runtime_calls(stack) == before + 1
    reopened = await owner.get(sessions)
    assert reopened.status_code == 502
    assert reopened.json()["retry_after"] > 0
    assert runtime_calls(stack) == before + 1


async def test_health_follows_a_flapping_runtime_and_settles(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime(HOST)
    instance = await connect(owner, fake)
    assert (await owner.post(f"/api/v1/instances/{instance['id']}/test")).json()["ok"] is True
    assert await status(owner, instance["id"]) == "connected"

    for _ in range(4):
        fake = down(stack)
        assert (await check_health(stack))[instance["slug"]].startswith("unreachable")
        assert await status(owner, instance["id"]) == "unreachable"
        up(stack, fake)
        assert (await check_health(stack))[instance["slug"]].startswith("ok")
        assert await status(owner, instance["id"]) == "connected"

    for _ in range(3):
        assert (await check_health(stack))[instance["slug"]].startswith("ok")
    health = (await owner.get(f"/api/v1/instances/{instance['id']}/health")).json()
    assert health["status"] == "connected"
    assert health["last_seen_at"] is not None
    assert (await owner.get(f"/api/v1/instances/{instance['id']}/os/sessions")).status_code == 200
