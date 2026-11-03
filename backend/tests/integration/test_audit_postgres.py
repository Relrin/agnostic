"""Audit governance on PostgreSQL: monthly partitions archived to S3, dropped and restored as partitions, and the
hash chain under concurrent writers (the advisory lock keeps one chain)."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from agnostic_audit.application.archive import Archives, MaintainPartitions
from agnostic_audit.application.ports import PartitionMaintenance
from agnostic_audit.application.streaming import DeliverSinks
from agnostic_audit.domain.archive import Manifest, month_key, parse_month
from agnostic_audit.domain.events import partition_name
from agnostic_audit.facade import Actor, AuditEntry, AuditLog, IngestedEntry
from agnostic_kernel.db import create_engine, utcnow
from tests.support.fake_s3 import FakeReceiver, FakeS3
from tests.support.stack import Stack, running_stack

pytestmark = pytest.mark.integration
NEVER = "0 0 1 1 *"


@pytest.fixture
async def stack(fresh_postgres: str, redis_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_ON_RECORD", "false")
    monkeypatch.setenv("AGNOSTIC_GATEWAY__INGEST_CRON", NEVER)
    async with running_stack(fresh_postgres, redis_url=redis_url, jobs={"mode": "embedded"}) as running:
        yield running


async def partitions(stack: Stack) -> set[str]:
    engine = create_engine(stack.settings.database)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'audit_events'"
                )
            )
            return {str(name) for (name,) in rows}
    finally:
        await engine.dispose()


async def test_partitions_are_archived_dropped_and_restored(stack: Stack) -> None:
    owner = await stack.owner()
    s3 = FakeS3()
    stack.serve("s3.test", s3.app)
    saved = await owner.put(
        "/api/v1/audit/policy",
        json={
            "archive_enabled": True,
            "endpoint": "https://s3.test",
            "bucket": "audit-archive",
            "access_key_id": "AKIDEXAMPLEAGNOSTIC",
            "secret_access_key": "test-" + "secret-key",
            "object_lock_mode": "governance",
            "archive_retention_days": 3650,
        },
    )
    assert saved.status_code == 200, saved.text

    moment = utcnow() - timedelta(days=460)
    month = month_key(moment)
    partition = partition_name(parse_month(month))
    async with stack.container() as request:
        await (await request.get(PartitionMaintenance)).ensure_month(month)
        old = [
            IngestedEntry(
                source_event_id=f"old:{n}",
                occurred_at=moment + timedelta(minutes=n),
                action="agentos.access",
                actor=Actor(kind="user", id="usr_maya", display="Maya Chen"),
                summary=f"Maya Chen called GET /agents/{n}",
                decision="allowed",
            )
            for n in range(12)
        ]
        assert await (await request.get(AuditLog)).ingest(old) == 12
    assert partition in await partitions(stack)

    async with stack.container() as request:
        report = await (await request.get(MaintainPartitions))()
    assert report.archived == [month]
    assert partition not in await partitions(stack)
    manifest = Manifest.parse(s3.objects()[f"audit-events-{month}.manifest.json"].data)
    assert manifest.event_count == 12
    assert s3.objects()[f"audit-events-{month}.jsonl.zst"].lock_mode == "GOVERNANCE"
    found = (await owner.get("/api/v1/audit/events", params={"source": "agentos"})).json()["data"]
    assert found == []

    async with stack.container() as request:
        restored = await (await request.get(Archives)).restore(month)
    assert restored.restore_expires_at is not None
    assert partition in await partitions(stack)
    found = (await owner.get("/api/v1/audit/events", params={"source": "agentos", "limit": 50})).json()["data"]
    assert len(found) == 12

    engine = create_engine(stack.settings.database)
    try:
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as connection:
                _ = await connection.execute(text(f"DELETE FROM agnostic.{partition}"))
    finally:
        await engine.dispose()

    # Once the restore window has passed, maintenance drops the month again without archiving it twice.
    async with stack.container() as request:
        later = await (await request.get(MaintainPartitions))(utcnow() + timedelta(days=8))
    assert later.archived == []
    assert month in later.dropped
    assert partition not in await partitions(stack)


async def test_concurrent_writers_keep_one_chain(stack: Stack) -> None:
    owner = await stack.owner()
    assert (await owner.put("/api/v1/audit/policy", json={"hash_chain": True})).status_code == 200

    async def record(number: int) -> str:
        async with stack.container() as request:
            log = await request.get(AuditLog)
            return await log.record_now(
                AuditEntry(
                    action="audit.export",
                    actor=Actor(kind="system", id="system", display="Agnostic"),
                    fields={"count": str(number), "format": "CSV"},
                )
            )

    async def create_view(number: int) -> Any:
        return await owner.post("/api/v1/audit/views", json={"name": f"Shared {number}", "shared": True})

    results = await asyncio.gather(*(record(n) for n in range(25)), *(create_view(n) for n in range(10)))
    assert len(set(results[:25])) == 25

    verified = (await owner.post("/api/v1/audit/verify", json={})).json()
    assert verified["ok"] is True, verified
    assert verified["checked"] >= 35

    engine = create_engine(stack.settings.database)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT prev_hash, hash FROM agnostic.audit_events WHERE hash IS NOT NULL "
                        "ORDER BY occurred_at, id"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    assert all(rows[i].prev_hash == rows[i - 1].hash for i in range(1, len(rows)))
    assert len({row.prev_hash for row in rows}) == len(rows)  # no fork: every hash is followed once


async def test_one_delivery_at_a_time_across_callers(stack: Stack) -> None:
    owner = await stack.owner()
    receiver = FakeReceiver()
    stack.serve("siem.test", receiver.app)
    created = await owner.post(
        "/api/v1/audit/sinks",
        json={"name": "SIEM", "kind": "https_webhook", "format": "ocsf", "config": {"url": "https://siem.test/"}},
    )
    assert created.status_code == 201, created.text
    for number in range(5):
        _ = await owner.post("/api/v1/audit/views", json={"name": f"Shared {number}", "shared": True})

    async def deliver() -> dict[str, int]:
        async with stack.container() as request:
            return await (await request.get(DeliverSinks))(utcnow() + timedelta(seconds=30))

    results = await asyncio.gather(*(deliver() for _ in range(4)))
    assert sum(sum(result.values()) for result in results) >= 6
    ids = [item["metadata"]["uid"] for request in receiver.received for item in json.loads(request["body"])]
    assert len(ids) == len(set(ids))  # the advisory lock let one caller deliver; nothing went out twice
    assert all(item["class_uid"] in {3002, 6003} for r in receiver.received for item in json.loads(r["body"]))
