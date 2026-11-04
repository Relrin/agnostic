"""The cache goes away (stopped, or frozen so commands hang): caches and realtime degrade, the API keeps serving and
``/readyz`` says what is wrong; once the cache is back, everything works again without a restart."""

import time
from collections.abc import AsyncIterator, Awaitable
from typing import Any

import httpx
import pytest

from agnostic_kernel.events import EventBus, RealtimeEvent
from tests.chaos.conftest import Chaos, redis_ready
from tests.support.stack import OWNER_PASSWORD, Stack, running_stack

pytestmark = pytest.mark.chaos

NEVER = "0 0 1 1 *"
FAST = 3.0
"""A degraded request answers well within this (the cache's socket timeout is 1 s)."""
CHECK_BUDGET = 7.0
"""``/readyz`` probes each dependency with a 5 s timeout."""


@pytest.fixture
async def stack(fresh_postgres: str, redis_up: Chaos, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
    monkeypatch.setenv("AGNOSTIC_GATEWAY__INGEST_CRON", NEVER)
    async with running_stack(fresh_postgres, redis_url=redis_up.url, jobs={"mode": "embedded"}) as running:
        yield running


def break_cache(redis: Chaos, how: str) -> None:
    if how == "stop":
        redis.stop()
    else:
        redis.pause()


async def restore_cache(redis: Chaos, how: str) -> None:
    if how == "stop":
        redis.start()
    else:
        redis.unpause()
    await redis_ready(redis.url)


async def timed(call: Awaitable[httpx.Response]) -> tuple[httpx.Response, float]:
    started = time.monotonic()
    response = await call
    return response, time.monotonic() - started


def cache_check(readiness: dict[str, Any]) -> dict[str, Any]:
    return next(check for check in readiness["checks"] if check["name"] == "cache")


@pytest.mark.parametrize("how", ["stop", "pause"])
async def test_api_keeps_serving_without_the_cache(stack: Stack, redis_up: Chaos, how: str) -> None:
    owner = await stack.owner()
    assert (await owner.get("/api/v1/instances")).status_code == 200
    anonymous = stack.client()

    break_cache(redis_up, how)
    try:
        ready, elapsed = await timed(anonymous.get("/readyz"))
        assert elapsed < CHECK_BUDGET
        body = ready.json()
        assert cache_check(body)["ok"] is False
        assert next(check for check in body["checks"] if check["name"] == "database")["ok"] is True
        assert (await anonymous.get("/healthz")).status_code == 200

        status, elapsed = await timed(anonymous.get("/api/v1/onboarding/status"))
        assert status.status_code == 200, status.text
        assert elapsed < FAST

        # Realtime is a hint: publishing into a dead cache neither raises nor blocks.
        async with stack.container() as request:
            bus = await request.get(EventBus)
            started = time.monotonic()
            await bus.publish("evt:org", RealtimeEvent(type="chaos.ping"))
            assert time.monotonic() - started < FAST
    finally:
        await restore_cache(redis_up, how)

    ready = await anonymous.get("/readyz")
    assert ready.status_code == 200, ready.text
    assert cache_check(ready.json())["ok"] is True
    again = await stack.sign_in("daniel@localhost.company", OWNER_PASSWORD)
    assert (await again.get("/api/v1/instances")).status_code == 200


@pytest.mark.xfail(
    strict=True,
    reason="Known limitation (docs/release-notes/1.0.0.md): web sessions live only in the cache, so a cache "
    "outage signs people out (caches and rate limits degrade instead of failing)",
)
@pytest.mark.parametrize("how", ["stop", "pause"])
async def test_signed_in_people_keep_working_without_the_cache(stack: Stack, redis_up: Chaos, how: str) -> None:
    owner = await stack.owner()
    break_cache(redis_up, how)
    try:
        listed, elapsed = await timed(owner.get("/api/v1/instances"))
        assert listed.status_code == 200, listed.text
        assert elapsed < FAST
    finally:
        await restore_cache(redis_up, how)


async def test_readiness_stays_ready_when_only_the_cache_is_down(stack: Stack, redis_up: Chaos) -> None:
    anonymous = stack.client()
    redis_up.stop()
    try:
        ready = await anonymous.get("/readyz")
        assert cache_check(ready.json())["ok"] is False
        assert ready.status_code == 200
    finally:
        await restore_cache(redis_up, "stop")
