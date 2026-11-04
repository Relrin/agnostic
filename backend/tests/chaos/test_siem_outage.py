"""The SIEM goes away: the sink turns failing, its backlog grows with every event, and once the receiver is back the
backlog drains in order, each event once, and the sink is healthy again."""

import json
from collections.abc import AsyncIterator
from datetime import timedelta

import httpx
import pytest

from agnostic_audit.application.ports import AuditRepository, EventQuery, SinkRepository
from agnostic_audit.application.streaming import DeliverSinks
from agnostic_audit.facade import Actor, AuditEntry, AuditLog
from agnostic_kernel.db import utcnow
from tests.support.fake_s3 import FakeReceiver
from tests.support.stack import Stack, running_stack

pytestmark = pytest.mark.chaos

NEVER = "0 0 1 1 *"
SIEM = "siem.test"
BATCH = 40


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_ON_RECORD", "false")
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVERY_BATCH", str(BATCH))
    monkeypatch.setenv("AGNOSTIC_GATEWAY__INGEST_CRON", NEVER)
    async with running_stack(sqlite_database) as running:
        yield running


async def record(stack: Stack, count: int, start: int) -> None:
    async with stack.container() as request:
        log = await request.get(AuditLog)
        for number in range(start, start + count):
            _ = await log.record_now(
                AuditEntry(
                    action="audit.export",
                    actor=Actor(kind="system", id="system", display="Agnostic"),
                    fields={"count": str(number), "format": "CSV"},
                )
            )


async def deliver(stack: Stack) -> int:
    async with stack.container() as request:
        delivered = await (await request.get(DeliverSinks))(utcnow() + timedelta(seconds=30))
    return sum(delivered.values())


async def backlog(stack: Stack, sink_id: str) -> list[str]:
    async with stack.container() as request:
        cursor = await (await request.get(SinkRepository)).cursor(sink_id)
        events = await (await request.get(AuditRepository)).ascending(EventQuery(), 100_000, cursor)
    return [event.id for event in events]


async def sink_state(owner: httpx.AsyncClient, sink_id: str) -> dict[str, object]:
    sinks = (await owner.get("/api/v1/audit/sinks")).json()
    return next(sink for sink in sinks if sink["id"] == sink_id)


async def test_backlog_grows_during_the_outage_and_drains_in_order(stack: Stack) -> None:
    owner = await stack.owner()
    receiver = FakeReceiver()
    stack.serve(SIEM, receiver.app)
    created = await owner.post(
        "/api/v1/audit/sinks",
        json={"name": "SIEM", "kind": "https_webhook", "format": "ocsf", "config": {"url": f"https://{SIEM}/"}},
    )
    assert created.status_code == 201, created.text
    sink_id = created.json()["id"]
    await record(stack, 10, 0)
    assert await deliver(stack) > 0
    assert await backlog(stack, sink_id) == []
    delivered_before = len(receiver.received)

    # The receiver's host stops answering, then answers 503 for a while: nothing is lost either way.
    del stack.routes.services[SIEM]
    sizes: list[int] = []
    for round_number in range(4):
        await record(stack, 25, 100 + round_number * 25)
        assert await deliver(stack) == 0
        sizes.append(len(await backlog(stack, sink_id)))
    assert sizes == sorted(sizes)
    assert sizes[-1] >= 100
    failing = await sink_state(owner, sink_id)
    assert failing["status"] == "failing"
    assert int(str(failing["failure_count"])) >= 3
    assert failing["last_error"]

    receiver.fail_next = 2
    stack.serve(SIEM, receiver.app)
    expected = await backlog(stack, sink_id)
    assert await deliver(stack) == 0  # the first answer is a 503: the cursor stays put
    assert await backlog(stack, sink_id) == expected

    drained = 0
    for _ in range(5):
        drained += await deliver(stack)
        if not await backlog(stack, sink_id):
            break
    assert drained == len(expected)
    assert await backlog(stack, sink_id) == []

    received = [
        item["metadata"]["uid"]
        for request in receiver.received[delivered_before:]
        for item in json.loads(request["body"])
    ]
    assert received == expected  # in (occurred_at, id) order, each event once
    assert all(len(json.loads(request["body"])) <= BATCH for request in receiver.received)
    healthy = await sink_state(owner, sink_id)
    assert healthy["status"] == "ok"
    assert healthy["failure_count"] == 0
    assert healthy["last_error"] is None
