"""Audit governance end to end on SQLite: search, saved views, exports, the hash chain, retention with the archive
tier (against an in-memory S3), restores, SIEM streaming, and ingesting AgentOS authorization trails."""

import hashlib
import json
from collections.abc import AsyncIterator
from compression import zstd
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from agnostic_audit.application.archive import MaintainPartitions
from agnostic_audit.application.streaming import DeliverSinks
from agnostic_audit.domain.archive import Manifest, month_key
from agnostic_audit.domain.siem import verify_webhook_signature
from agnostic_audit.facade import Actor, AuditLog, IngestedEntry
from agnostic_gateway.application.ingest import IngestAuthz
from agnostic_kernel.db import create_engine, utcnow
from agnostic_kernel.testing import wait_for
from tests.support.fake_agentos import FakeAgentOS
from tests.support.fake_s3 import FakeReceiver, FakeS3
from tests.support.stack import Stack, running_stack

PROD = "http://prod.agentos.test:7777"
NEVER = "0 0 1 1 *"


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    # Deliveries and ingestion run when a test says so, not on the minute.
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_ON_RECORD", "false")
    monkeypatch.setenv("AGNOSTIC_AUDIT__EXPORT_SYNC_LIMIT", "200")
    monkeypatch.setenv("AGNOSTIC_GATEWAY__INGEST_CRON", NEVER)
    async with running_stack(sqlite_database) as running:
        yield running


def entry(number: int, *, days_ago: float = 0, **changes: Any) -> IngestedEntry:
    values: dict[str, Any] = {
        "source_event_id": f"test:{number}",
        "occurred_at": utcnow() - timedelta(days=days_ago, seconds=number),
        "action": "agentos.access",
        "actor": Actor(kind="user", id="usr_maya", display="Maya Chen"),
        "summary": f"Maya Chen called GET /agents/{number}",
        "resource_kind": "route",
        "resource_id": f"GET /agents/support-triage-{number}",
        "resource_display": f"GET /agents/support-triage-{number}",
        "decision": "allowed",
        **changes,
    }
    return IngestedEntry(**values)


async def ingest(stack: Stack, entries: list[IngestedEntry]) -> int:
    async with stack.container() as request:
        return await (await request.get(AuditLog)).ingest(entries)


async def events(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    response = await client.get("/api/v1/audit/events", params={"limit": 200, **params})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_search_saved_views_and_actors(stack: Stack) -> None:
    owner = await stack.owner()
    denied = entry(
        1,
        decision="denied",
        instance_id="ins_prod",
        scope_checked="components:write",
        missing_scopes=("components:write",),
        denial_reason="POST /components/*/set-current needs components:write on prod-agentos.",
    )
    assert await ingest(stack, [denied, entry(2), entry(3, actor=Actor("service_account", "sa:bot", "sa:bot"))]) == 3
    assert await ingest(stack, [denied]) == 0  # each source event once

    found = await events(owner, q="SUPPORT-TRIAGE-1")
    assert [event["source_event_id"] for event in found] == ["test:1"]
    assert found[0]["denial_reason"].startswith("POST /components")
    detail = (await owner.get(f"/api/v1/audit/events/{found[0]['id']}")).json()
    assert (detail["can_request_access"], detail["decision"]) == (True, "denied")
    assert [e["source_event_id"] for e in await events(owner, actor_kind="service_account")] == ["test:3"]
    assert {e["source"] for e in await events(owner, source="agentos")} == {"agentos"}
    assert await events(owner, q="maya chen", source="control_plane") == []

    actors = (await owner.get("/api/v1/audit/actors")).json()
    assert {"kind": "user", "id": "usr_maya", "display": "Maya Chen", "count": 2} in actors

    created = await owner.post(
        "/api/v1/audit/views", json={"name": "Denied in production", "filters": {"decision": "denied"}}
    )
    assert created.status_code == 201, created.text
    view = created.json()
    assert (view["count"], view["count_capped"], view["shared"], view["editable"]) == (1, False, False, True)
    shared = await owner.post(
        "/api/v1/audit/views", json={"name": "AgentOS", "filters": {"source": "agentos"}, "shared": True}
    )
    assert shared.json()["shared"] is True
    assert shared.json()["owner_id"] is None
    renamed = await owner.patch(f"/api/v1/audit/views/{view['id']}", json={"name": "Denied", "position": 5})
    assert (renamed.json()["name"], renamed.json()["position"]) == ("Denied", 5)
    listed = (await owner.get("/api/v1/audit/views")).json()
    assert [item["name"] for item in listed] == ["AgentOS", "Denied"]
    bad = await owner.post("/api/v1/audit/views", json={"name": "x", "filters": {"decision": "maybe"}})
    assert bad.status_code == 422

    # Counts stop at 1000 ("999+" in the UI).
    assert await ingest(stack, [entry(10 + n, resource_id=f"bulk-{n}") for n in range(1005)]) == 1005
    listed = (await owner.get("/api/v1/audit/views")).json()
    agentos_view = next(item for item in listed if item["name"] == "AgentOS")
    assert (agentos_view["count"], agentos_view["count_capped"]) == (1000, True)

    assert (await owner.delete(f"/api/v1/audit/views/{view['id']}")).status_code == 204
    assert [item["name"] for item in (await owner.get("/api/v1/audit/views")).json()] == ["AgentOS"]
    shares = await events(owner, action="audit.views.share")
    assert len(shares) == 1


async def test_sync_and_background_exports(stack: Stack) -> None:
    owner = await stack.owner()
    _ = await ingest(stack, [entry(n, summary=f"=cmd|{n}") for n in range(5)])

    csv = await owner.get("/api/v1/audit/export", params={"format": "csv", "source": "agentos"})
    assert csv.status_code == 200, csv.text
    assert csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv.headers["content-disposition"]
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("id,occurred_at,actor_kind")
    assert len(lines) == 6
    assert "'=cmd|4" in csv.text  # formulas are defused for spreadsheets

    jsonl = await owner.get("/api/v1/audit/export", params={"format": "jsonl", "source": "agentos"})
    documents = [json.loads(line) for line in jsonl.text.splitlines()]
    assert len(documents) == 5
    assert documents[0]["actor"]["display"] == "Maya Chen"

    _ = await ingest(stack, [entry(100 + n) for n in range(250)])
    too_many = await owner.get("/api/v1/audit/export", params={"format": "csv"})
    assert too_many.status_code == 413
    assert "/api/v1/audit/exports" in too_many.json()["detail"]

    started = await owner.post("/api/v1/audit/exports", json={"format": "jsonl", "filters": {"source": "agentos"}})
    assert started.status_code == 202, started.text
    export_id = started.json()["id"]

    async def status() -> dict[str, Any]:
        return (await owner.get(f"/api/v1/audit/exports/{export_id}")).json()

    done = await wait_for(status, lambda body: body["status"] in {"done", "failed"})
    assert done["status"] == "done", done
    assert done["row_count"] == 255
    assert done["download_url"] == f"/api/v1/audit/exports/{export_id}/download"
    assert [item["id"] for item in (await owner.get("/api/v1/audit/exports")).json()] == [export_id]
    download = await owner.get(done["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/x-ndjson")
    assert len(download.text.splitlines()) == 255

    exported = await events(owner, action="audit.export")
    assert len(exported) == 3  # two downloads and the background file


async def test_hash_chain_verification_finds_tampering(stack: Stack) -> None:
    owner = await stack.owner()
    turned_on = await owner.put("/api/v1/audit/policy", json={"hash_chain": True})
    assert turned_on.status_code == 200, turned_on.text
    for number in range(4):
        _ = await owner.post("/api/v1/audit/views", json={"name": f"Shared {number}", "shared": True})
    chained = [event for event in await events(owner) if event["hash"]]
    assert len(chained) >= 4

    verified = (await owner.post("/api/v1/audit/verify", json={})).json()
    assert verified == {"ok": True, "checked": len(chained), "first_broken_event_id": None}

    victim = sorted(chained, key=lambda event: event["occurred_at"])[1]
    engine = create_engine(stack.settings.database)
    async with engine.begin() as connection:
        _ = await connection.execute(
            text("UPDATE audit_events SET summary = 'nothing to see' WHERE id = :id"), {"id": victim["id"]}
        )
    await engine.dispose()
    broken = (await owner.post("/api/v1/audit/verify", json={})).json()
    assert broken["ok"] is False
    assert broken["first_broken_event_id"] == victim["id"]


def archive_policy(**changes: Any) -> dict[str, Any]:
    return {
        "archive_enabled": True,
        "endpoint": "https://s3.test",
        "bucket": "audit-archive",
        "prefix": "agnostic/prod",
        "region": "eu-west-1",
        "access_key_id": "AKIDEXAMPLEAGNOSTIC",
        "secret_access_key": "test-" + "secret-key",
        "object_lock_mode": "compliance",
        "archive_retention_days": 2555,
        **changes,
    }


async def maintain(stack: Stack) -> Any:
    async with stack.container() as request:
        return await (await request.get(MaintainPartitions))()


async def test_policy_archive_and_restore(stack: Stack) -> None:  # noqa: PLR0915  (one story)
    owner = await stack.owner()
    s3 = FakeS3()
    stack.serve("s3.test", s3.app)

    policy = (await owner.get("/api/v1/audit/policy")).json()
    assert (policy["hot_retention_days"], policy["archive_enabled"], policy["has_secret"]) == (400, False, False)
    incomplete = await owner.put("/api/v1/audit/policy", json={"archive_enabled": True})
    assert incomplete.status_code == 422
    saved = await owner.put("/api/v1/audit/policy", json=archive_policy())
    assert saved.status_code == 200, saved.text
    assert saved.json()["has_secret"] is True
    assert "secret" not in json.dumps({k: v for k, v in saved.json().items() if k != "has_secret"})
    assert (await events(owner, action="audit.policy.update"))[0]["diff"]["lines"]

    check = (await owner.post("/api/v1/audit/policy/test-write")).json()
    assert check["ok"] is True, check
    assert [request["method"] for request in s3.requests] == ["PUT", "GET", "DELETE"]
    assert s3.objects() == {}
    wrong = (await owner.post("/api/v1/audit/policy/test-write", json={"access_key_id": "AKIDSOMEONEELSE"})).json()
    assert wrong["ok"] is False
    assert "InvalidAccessKeyId" in wrong["error"]

    old = [entry(n, days_ago=460) for n in range(7)]
    month = month_key(old[0].occurred_at)
    assert await ingest(stack, old) == 7
    assert len(await events(owner, source="agentos")) == 7

    # Upload fails: nothing is dropped, the error is kept.
    s3.fail_puts = 1
    report = await maintain(stack)
    assert report.failed == [month]
    assert len(await events(owner, source="agentos")) == 7
    assert month in (await owner.get("/api/v1/audit/policy")).json()["last_archive_error"]

    # The read-back doesn't match: still nothing dropped.
    s3.corrupt_reads = True
    assert (await maintain(stack)).failed == [month]
    assert len(await events(owner, source="agentos")) == 7
    s3.corrupt_reads = False

    report = await maintain(stack)
    assert report.archived == [month]
    data_key = f"agnostic/prod/audit-events-{month}.jsonl.zst"
    manifest_key = f"agnostic/prod/audit-events-{month}.manifest.json"
    stored = s3.objects()[data_key]
    manifest = Manifest.parse(s3.objects()[manifest_key].data)
    assert manifest.sha256 == hashlib.sha256(stored.data).hexdigest()
    assert manifest.event_count == 7
    assert stored.lock_mode == "COMPLIANCE"
    assert stored.retain_until is not None
    lines = zstd.decompress(stored.data).splitlines()
    assert sorted(json.loads(line)["source_event_id"] for line in lines) == sorted(e.source_event_id for e in old)
    assert await events(owner, source="agentos") == []

    archives = (await owner.get("/api/v1/audit/archives")).json()
    assert [(a["month"], a["event_count"], a["restored"]) for a in archives] == [(month, 7, False)]
    assert archives[0]["sha256"] == manifest.sha256
    assert (await maintain(stack)).archived == []  # never twice

    restore = await owner.post(f"/api/v1/audit/archives/{month}/restore")
    assert restore.status_code == 202, restore.text
    assert restore.json() == {"month": month, "status": "queued"}
    restored = await wait_for(lambda: events(owner, source="agentos"), lambda found: len(found) == 7)
    assert {event["source_event_id"] for event in restored} == {e.source_event_id for e in old}
    archives = (await owner.get("/api/v1/audit/archives")).json()
    assert archives[0]["restored"] is True
    assert archives[0]["restore_expires_at"] is not None
    assert (await maintain(stack)).archived == []  # restored months stay until their window ends
    assert len(await events(owner, source="agentos")) == 7
    assert (await events(owner, action="audit.restore"))[0]["resource_id"] == month
    assert (await owner.post("/api/v1/audit/archives/1999-01/restore")).status_code == 404


async def test_webhook_sink_delivers_at_least_once(stack: Stack) -> None:  # noqa: PLR0915  (one story)
    owner = await stack.owner()
    receiver = FakeReceiver()
    stack.serve("siem.test", receiver.app)
    secret = "whsec-" + "integration"

    created = await owner.post(
        "/api/v1/audit/sinks",
        json={
            "name": "Splunk HEC",
            "kind": "https_webhook",
            "format": "json",
            "config": {"url": "https://siem.test/hook", "secret": secret, "headers": {"Authorization": "x"}},
        },
    )
    assert created.status_code == 201, created.text
    sink = created.json()
    assert sink["has_secret"] is True
    assert sink["config"] == {"url": "https://siem.test/hook", "header_names": ["Authorization"]}
    assert secret not in created.text

    tested = (await owner.post(f"/api/v1/audit/sinks/{sink['id']}/test")).json()
    assert (tested["ok"], tested["status_code"]) == (True, 204)
    assert json.loads(receiver.received[-1]["body"])[0]["action"] == "audit.sinks.test"
    receiver.received.clear()

    _ = await ingest(stack, [entry(n, occurred_at=utcnow()) for n in range(3)])

    async def deliver() -> dict[str, int]:
        async with stack.container() as request:
            return await (await request.get(DeliverSinks))(utcnow() + timedelta(seconds=30))

    receiver.fail_next = 1
    assert await deliver() == {sink["id"]: 0}
    assert receiver.refused == 1
    failed = (await owner.get("/api/v1/audit/sinks")).json()[0]
    assert (failed["status"], failed["failure_count"], failed["last_event_at"]) == ("ok", 1, None)
    assert "503" in failed["last_error"]

    delivered = await deliver()
    assert delivered[sink["id"]] >= 4  # the sink's own creation and the three events
    (batch,) = receiver.received
    body = batch["body"]
    assert int(batch["headers"]["x-agnostic-event-count"]) == len(json.loads(body))
    signature = batch["headers"]["x-agnostic-signature"]
    timestamp = int(signature.split(",")[0].removeprefix("t="))
    assert verify_webhook_signature(secret.encode(), signature, body, now=timestamp)
    assert batch["headers"]["authorization"] == "x"
    sent = json.loads(body)
    assert {item["source_event_id"] for item in sent} >= {"test:0", "test:1", "test:2"}
    assert [item["occurred_at"] for item in sent] == sorted(item["occurred_at"] for item in sent)

    assert await deliver() == {sink["id"]: 0}  # the cursor moved: nothing twice
    assert len(receiver.received) == 1

    status = (await owner.get("/api/v1/audit/stream-status")).json()
    assert status["streaming"] is True
    assert status["last_event_at"] is not None
    assert status["sinks"][0]["status"] == "ok"

    # Three failures in a row mark the sink failing.
    _ = await ingest(stack, [entry(50, occurred_at=utcnow())])
    receiver.fail_next = 3
    for _ in range(3):
        _ = await deliver()
    assert (await owner.get("/api/v1/audit/stream-status")).json()["sinks"][0]["status"] == "failing"
    paused = await owner.patch(f"/api/v1/audit/sinks/{sink['id']}", json={"enabled": False})
    assert paused.json()["status"] == "paused"
    assert (await owner.get("/api/v1/audit/stream-status")).json()["streaming"] is False
    kept = await owner.patch(f"/api/v1/audit/sinks/{sink['id']}", json={"config": {"url": "https://siem.test/v2"}})
    assert kept.json()["has_secret"] is True
    assert (await owner.delete(f"/api/v1/audit/sinks/{sink['id']}")).status_code == 204
    assert {e["action"] for e in await events(owner, action="audit.sinks.*")} == {
        "audit.sinks.create",
        "audit.sinks.update",
        "audit.sinks.delete",
    }


async def connect(owner: httpx.AsyncClient, fake: FakeAgentOS) -> dict[str, Any]:
    created = await owner.post(
        "/api/v1/instances", json={"endpoint_url": PROD, "display_name": "prod-agentos", "env_tag": "production"}
    )
    assert created.status_code == 201, created.text
    instance: dict[str, Any] = created.json()["instance"]
    keys = (await owner.get(f"/api/v1/instances/{instance['id']}/keys/public")).json()
    fake.public_keys = [key["public_pem"] for key in keys["keys"] if key["status"] == "active"]
    report = (await owner.post(f"/api/v1/instances/{instance['id']}/test")).json()
    assert report["ok"] is True, report["steps"]
    capabilities = {item["name"]: item["status"] for item in report["capabilities"]}
    assert capabilities["authz_store"] == "available"
    return instance


async def test_agentos_authz_trails_are_ingested_once(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    now = int(utcnow().timestamp())
    fake.authz_decisions = [
        {
            "created_at": now - 30,
            "actor": "usr_maya",
            "action": "access.denied",
            "target": "DELETE /sessions/ses_3301c",
            "metadata": {"required": ["sessions:delete"], "token": "j1", "scopes": ["sessions:read"]},
        },
        {
            "created_at": now - 20,
            "actor": "sa:zendesk-bridge",
            "action": "access.allowed",
            "target": "POST /agents/support-triage/runs",
            "metadata": {"required": ["agents:run"], "token": "p1", "scopes": ["agents:run"]},
        },
    ]
    fake.authz_changes = [
        {
            "created_at": now - 10,
            "actor": "usr_dana",
            "action": "user.assigned",
            "target": "usr_maya",
            "before": [],
            "after": ["operator"],
        }
    ]
    instance = await connect(owner, fake)

    async def run() -> dict[str, int]:
        async with stack.container() as request:
            return await (await request.get(IngestAuthz))()

    assert await run() == {instance["id"]: 3}
    ingested = await events(owner, source="agentos")
    assert len(ingested) == 3
    denied = next(event for event in ingested if event["decision"] == "denied")
    assert denied["action"] == "agentos.access"
    assert denied["missing_scopes"] == ["sessions:delete"]
    assert denied["instance_id"] == instance["id"]
    assert denied["via"] == "jwt"
    assert denied["can_request_access"] is True
    allowed = next(event for event in ingested if event["decision"] == "allowed")
    assert (allowed["actor"]["kind"], allowed["via"]) == ("service_account", "native-pat")
    change = next(event for event in ingested if event["action"] == "agentos.user.assigned")
    assert change["diff"]["lines"] == [{"op": "+", "text": "operator"}]

    assert await run() == {instance["id"]: 0}  # cursors and source ids: nothing twice
    fake.authz_decisions.append(
        {"created_at": now - 5, "actor": "usr_maya", "action": "access.allowed", "target": "GET /agents"}
    )
    assert await run() == {instance["id"]: 1}
    assert len(await events(owner, source="agentos")) == 4
    paths = [call["path"] for call in fake.calls if call["path"].startswith("/authz/")]
    assert "/authz/decisions" in paths
    assert "/authz/audit" in paths


async def test_events_stream_shortly_after_they_are_written(
    sqlite_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGNOSTIC_AUDIT__DELIVER_CRON", NEVER)
    monkeypatch.setenv("AGNOSTIC_AUDIT__SETTLE_SECONDS", "0")
    async with running_stack(sqlite_database) as stack:
        owner = await stack.owner()
        receiver = FakeReceiver()
        stack.serve("siem.test", receiver.app)
        created = await owner.post(
            "/api/v1/audit/sinks",
            json={"name": "Live", "kind": "https_webhook", "format": "cef", "config": {"url": "https://siem.test/"}},
        )
        assert created.status_code == 201, created.text
        _ = await owner.post("/api/v1/audit/views", json={"name": "Shared", "shared": True})

        received = await wait_for(lambda: _received(receiver), lambda count: count >= 2, timeout=15)
        assert received >= 2
        lines = [line for request in receiver.received for line in json.loads(request["body"])]
        assert all(line.startswith("CEF:0|Agnostic|Control Plane|") for line in lines)
        assert any("|audit.views.share|" in line for line in lines)


async def _received(receiver: FakeReceiver) -> int:
    return sum(len(json.loads(request["body"])) for request in receiver.received)
