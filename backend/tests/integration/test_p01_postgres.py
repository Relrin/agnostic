"""P01 on PostgreSQL + Redis: sessions in Redis, the gateway, and the partitioned append-only audit log."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agnostic_audit.infrastructure.repository import SqlPartitionMaintenance
from agnostic_kernel.cache import create_redis
from agnostic_kernel.db import create_engine
from agnostic_kernel.ephemeral import RedisStore
from agnostic_kernel.settings import RedisSettings
from tests.support.stack import running_stack

pytestmark = pytest.mark.integration


async def test_redis_store(redis_url: str) -> None:
    redis = create_redis(RedisSettings(url=redis_url))  # pyright: ignore[reportArgumentType]
    store = RedisStore(redis, prefix="agnostic-test:")
    try:
        await store.set("k", b"v", ttl=5)
        assert await store.get("k") == b"v"
        assert not await store.set_if_absent("k", b"w", ttl=5)
        assert await store.pop("k") == b"v"
        assert await store.get("k") is None
        assert await store.incr("n", ttl=5) == 1
        assert await store.incr("n", ttl=5) == 2
        await store.delete("n")
    finally:
        await redis.aclose()


async def test_p01_flow_on_postgres(fresh_postgres: str, redis_url: str) -> None:
    async with running_stack(fresh_postgres, redis_url=redis_url, jobs={"mode": "embedded"}) as stack:
        assert stack.settings.cache_backend() == "redis"
        owner = await stack.owner()
        fake = stack.runtime("prod.agentos.test")
        created = await owner.post(
            "/api/v1/instances", json={"endpoint_url": "http://prod.agentos.test", "env_tag": "production"}
        )
        instance = created.json()["instance"]
        keys = (await owner.get(f"/api/v1/instances/{instance['id']}/keys/public")).json()
        fake.public_keys = [keys["keys"][0]["public_pem"]]
        assert (await owner.post(f"/api/v1/instances/{instance['id']}/test")).json()["ok"]
        assert (await owner.get(f"/api/v1/instances/{instance['id']}/os/sessions")).status_code == 200
        events = (await owner.get("/api/v1/audit/events", params={"action": "instances.*"})).json()["data"]
        assert {event["action"] for event in events} >= {"instances.create", "instances.test"}

    engine = create_engine(stack.settings.database)
    try:
        async with engine.connect() as connection:
            partitions = set(
                (
                    await connection.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                            "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'audit_events'"
                        )
                    )
                ).scalars()
            )
        now = datetime.now(UTC)
        assert f"audit_events_y{now.year:04d}m{now.month:02d}" in partitions
        assert "audit_events_default" in partitions

        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as connection:
                _ = await connection.execute(text("UPDATE agnostic.audit_events SET summary = 'edited'"))

        maintenance = SqlPartitionMaintenance(engine)
        created = await maintenance.ensure_partitions(now + timedelta(days=200), months_ahead=0)
        assert len(created) == 1
        dropped = await maintenance.drop_expired(now + timedelta(days=200 + 400 + 62), retention_days=400)
        assert created[0] in dropped
    finally:
        await engine.dispose()
