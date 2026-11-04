"""On PostgreSQL + Redis: realtime events over Redis pub/sub and streams, full-text palette search, and the
elevation default on new instances."""

import asyncio
import json

import pytest

from agnostic_kernel.cache import create_redis
from agnostic_kernel.events import RealtimeEvent, RedisEventBus
from agnostic_kernel.settings import RedisSettings
from tests.api.test_instances_gateway import connect
from tests.support.stack import running_stack

pytestmark = pytest.mark.integration


async def test_redis_event_bus(redis_url: str) -> None:
    redis = create_redis(RedisSettings(url=redis_url))  # pyright: ignore[reportArgumentType]
    bus = RedisEventBus(redis, prefix="agnostic-test:")
    try:
        subscription = await bus.subscribe(["evt:org"])
        await asyncio.sleep(0.05)
        event = RealtimeEvent("access.changed", {"why": "binding"})
        await bus.publish("evt:org", event)
        received = await subscription.next(2.0)
        assert received == ("evt:org", event)
        await subscription.close()

        later = RealtimeEvent("approvals.count", {"count": 2}, instance_id="ins_a")
        await bus.publish("evt:instance:ins_a", later)
        replayed = await bus.replay(["evt:org", "evt:instance:ins_a"], event.id)
        assert replayed == [("evt:instance:ins_a", later)]
    finally:
        await redis.delete("agnostic-test:stream:evt:org", "agnostic-test:stream:evt:instance:ins_a")
        await redis.aclose()


async def test_search_and_events_on_postgres(
    fresh_postgres: str, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_NOTIFICATIONS__MAX_STREAM_SECONDS", "0.5")
    monkeypatch.setenv("AGNOSTIC_NOTIFICATIONS__HEARTBEAT_SECONDS", "0.1")
    async with running_stack(fresh_postgres, redis_url=redis_url, jobs={"mode": "embedded"}) as stack:
        owner = await stack.owner()
        fake = stack.runtime("prod.agentos.test")
        instance = await connect(owner, fake)
        assert instance["elevation_enabled"] is True

        people = (await owner.get("/api/v1/search", params={"q": "dan oka"})).json()["data"]
        assert people[0]["title"] == "Daniel Okafor"
        exact = (await owner.get("/api/v1/search", params={"q": instance["id"]})).json()["data"]
        assert exact[0]["ref"] == instance["id"]
        wildcard = (await owner.get("/api/v1/search", params={"q": "100%"})).json()["data"]
        assert wildcard == []

        stream = await owner.get("/api/v1/events")
        frames = [block for block in stream.text.split("\n\n") if block.startswith("event: ready")]
        ready = json.loads(frames[0].split("data: ", 1)[1])
        assert ready["instances"] == [instance["id"]]
