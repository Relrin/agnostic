"""Flows against a fake AgentOS: inline approval decisions (delegated elevation), the Home overview, the
realtime event stream and command-palette search."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from agnostic_approvals.application.poller import ApprovalsCountPoller
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from tests.api.test_instances_gateway import connect, invite_operator
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

NOW = datetime.now(UTC)


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__CONTINUE_RETRY_DELAYS", "[0.01, 0.01]")
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_NOTIFICATIONS__HEARTBEAT_SECONDS", "0.05")
    monkeypatch.setenv("AGNOSTIC_NOTIFICATIONS__MAX_STREAM_SECONDS", "0.3")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


def pending_refund(fake: FakeAgentOS, *, owner: str = "usr_dana", approval_id: str = "apr_1") -> dict[str, Any]:
    fake.approvals_enabled = True
    approval = {
        "id": approval_id,
        "run_id": "run_9f2c41",
        "session_id": "ses_7f3a91c2",
        "status": "pending",
        "agent_id": "support-triage",
        "team_id": None,
        "workflow_id": None,
        "user_id": owner,
        "tool_name": "refund_customer",
        "tool_args": {"customer_id": "cus_8812", "amount": 49.0, "reason": "requested in chat"},
        "requirements": [
            {
                "tool_execution": {
                    "tool_call_id": "call_1",
                    "tool_name": "refund_customer",
                    "tool_args": {"customer_id": "cus_8812", "amount": 49.0, "reason": "requested in chat"},
                    "requires_confirmation": True,
                }
            }
        ],
        "context": {},
        "created_at": int((NOW - timedelta(hours=2, minutes=14)).timestamp()),
    }
    fake.approvals[approval_id] = approval
    return approval


async def audit_events(owner: httpx.AsyncClient, action: str) -> list[dict[str, Any]]:
    return (await owner.get("/api/v1/audit/events", params={"action": action})).json()["data"]


async def test_operator_approves_someone_elses_run_with_edited_args(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    pending_refund(fake)
    fake.continue_conflicts = 1  # the durable ticket still owns the run once: decide retries

    decided = await marcus.post(
        "/api/v1/instances/prod-agentos/approvals/apr_1/decide",
        json={
            "decision": "approve",
            "note": "partial refund",
            "edited_args": {"customer_id": "cus_8812", "amount": 45.0, "reason": "requested in chat"},
        },
    )
    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert (body["status"], body["continue_state"], body["args_changed"]) == ("approved", "continued", ["amount"])

    # Both AgentOS calls ran as Instance admin for one request each, with Marcus as the subject.
    resolution = fake.resolutions[-1]
    claims = resolution["claims"]
    marcus_id = (await marcus.get("/api/v1/me")).json()["id"]
    assert claims["sub"] == marcus_id
    assert claims["scopes"] == ["agent_os:admin"]
    assert claims["exp"] - claims["iat"] == 60
    assert claims["agnostic"]["via"] == "elevated"
    assert resolution["body"]["status"] == "approved"
    assert resolution["body"]["resolved_by"].startswith("Marcus Chen")
    assert resolution["body"]["resolution_data"]["diff"] == {"amount": {"before": 49.0, "after": 45.0}}

    continuation = fake.continuations[-1]
    assert continuation["form"]["user_id"] == "usr_dana"
    assert continuation["form"]["background"] == "true"
    tools = json.loads(continuation["form"]["tools"])
    assert tools[0]["confirmed"] is True
    assert tools[0]["tool_args"]["amount"] == 45.0
    jtis = {call["claims"]["jti"] for call in fake.calls if call["claims"]["agnostic"]["via"] == "elevated"}
    assert len(jtis) == len([c for c in fake.calls if c["claims"]["agnostic"]["via"] == "elevated"])  # never reused

    decisions = await audit_events(owner, "approvals.decided")
    assert decisions[0]["diff"] == {"tool_args": {"amount": {"before": 49.0, "after": 45.0}}}
    assert decisions[0]["summary"] == "Marcus Chen approved refund_customer on support-triage"
    elevated = await audit_events(owner, "gateway.elevated")
    assert {event["scope_checked"] for event in elevated} == {"approvals:write"}
    assert len(elevated) >= 4  # get, resolve, continue (409), continue

    # Idempotent: a second decide returns the first outcome without touching AgentOS again.
    resolutions = len(fake.resolutions)
    again = await marcus.post("/api/v1/instances/prod-agentos/approvals/apr_1/decide", json={"decision": "reject"})
    assert again.json() == body
    assert len(fake.resolutions) == resolutions


async def test_reject_and_already_resolved(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    pending_refund(fake, approval_id="apr_2")
    fake.approvals["apr_2"]["status"] = "approved"

    resolved = await owner.post("/api/v1/instances/prod-agentos/approvals/apr_2/decide", json={"decision": "reject"})
    assert resolved.status_code == 200
    assert (resolved.json()["already_resolved"], resolved.json()["status"]) == (True, "approved")
    assert fake.resolutions == []

    pending_refund(fake, approval_id="apr_3")
    rejected = await owner.post("/api/v1/instances/prod-agentos/approvals/apr_3/decide", json={"decision": "reject"})
    assert rejected.json()["status"] == "rejected"
    tools = json.loads(fake.continuations[-1]["form"]["tools"])
    assert tools[0]["confirmed"] is False
    assert tools[0]["tool_args"]["amount"] == 49.0  # edits are ignored when rejecting

    missing = await owner.post("/api/v1/instances/prod-agentos/approvals/nope/decide", json={"decision": "approve"})
    assert missing.status_code == 404


async def test_decide_needs_approvals_write_and_enabled_elevation(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    pending_refund(fake)

    roles = {role["slug"]: role["id"] for role in (await owner.get("/api/v1/access/roles")).json()}
    invited = await owner.post(
        "/api/v1/invitations",
        json={
            "email": "vera@localhost.company",
            "bindings": [{"role_id": roles["viewer"], "instance_id": instance["id"]}],
        },
    )
    token = invited.json()["accept_url"].rsplit("/", 1)[1]
    viewer = stack.client()
    joined = await viewer.post(
        f"/api/v1/invitations/{token}/accept", json={"display_name": "Vera Viewer", "password": "vera's long password"}
    )
    viewer.headers["X-CSRF-Token"] = joined.json()["csrf_token"]
    denied = await viewer.post("/api/v1/instances/prod-agentos/approvals/apr_1/decide", json={"decision": "approve"})
    assert denied.status_code == 403
    assert denied.json()["missing_scopes"] == ["approvals:write"]

    turned_off = await owner.patch(f"/api/v1/instances/{instance['id']}", json={"elevation_enabled": False})
    assert turned_off.json()["elevation_enabled"] is False
    refused = await owner.post("/api/v1/instances/prod-agentos/approvals/apr_1/decide", json={"decision": "approve"})
    assert refused.status_code == 403
    assert refused.json()["code"] == "elevation_disabled"
    assert "Only Instance admins" in refused.json()["detail"]


async def test_overview_aggregates_and_filters(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    pending_refund(fake)
    today = NOW.date()
    fake.metrics_rows = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "agent_runs_count": 10,
            "team_runs_count": 0,
            "workflow_runs_count": 0,
            "agent_sessions_count": 4,
            "model_metrics": [{"model_id": "mock-1", "count": 10}],
        }
        for offset in range(14)
    ]
    fake.traces = [
        {
            "trace_id": f"tr_{index}",
            "status": "ERROR" if index < 3 else "OK",
            "start_time": (NOW - timedelta(hours=index)).isoformat(),
            "end_time": (NOW - timedelta(hours=index) + timedelta(milliseconds=200 * (index + 1))).isoformat(),
            "duration": "1s",
            "error_count": 1 if index < 3 else 0,
            "agent_id": "support-triage",
        }
        for index in range(20)
    ]
    fake.schedules = [{"id": "sch_1", "name": "daily-brief", "enabled": True}]
    fake.schedule_runs["sch_1"] = [
        {
            "id": "r2",
            "status": "failed",
            "error": "Timeout in web_search after 30 s",
            "triggered_at": int(NOW.timestamp()) - 60,
            "run_id": "run_b",
        },
        {
            "id": "r1",
            "status": "failed",
            "error": "Timeout",
            "triggered_at": int(NOW.timestamp()) - 86_400,
            "run_id": "run_a",
        },
    ]

    overview = (await owner.get("/api/v1/instances/prod-agentos/overview", params={"range": "7d"})).json()
    assert overview["cached"] is False
    assert overview["counts"] == {"agents": 2, "teams": 0, "workflows": 0}
    assert overview["kpis"]["runs"]["value"] == 80  # 8 calendar days in a 7-day window ending now
    assert overview["kpis"]["error_rate"]["value"] == pytest.approx(3 / 20)
    assert overview["kpis"]["p95_latency_ms"]["value"] == pytest.approx(3800)  # nearest rank: 19th of 20
    assert overview["model_usage"][0]["model_id"] == "mock-1"
    assert overview["pending_approvals"] == 1
    kinds = [item["kind"] for item in overview["attention"]]
    assert set(kinds) == {"approval_backlog", "error_spike", "schedule_failing"}
    backlog = next(item for item in overview["attention"] if item["kind"] == "approval_backlog")
    assert backlog["title"] == "1 approval waiting"
    assert backlog["detail"].startswith("`refund_customer` on support-triage · oldest 2h 1")
    assert backlog["action"] == {"label": "Review", "target": "approvals?tool=refund_customer"}
    schedule = next(item for item in overview["attention"] if item["kind"] == "schedule_failing")
    assert schedule["title"] == "daily-brief failed twice"
    triage = next(item for item in overview["primitives"] if item["id"] == "support-triage")
    assert (triage["runs"], triage["errors"]) == (20, 3)
    assert overview["activity"] is not None

    again = (await owner.get("/api/v1/instances/prod-agentos/overview", params={"range": "7d"})).json()
    assert again["cached"] is True

    fake.approvals_enabled = False
    fresh = (await owner.get("/api/v1/instances/prod-agentos/overview", params={"refresh": "true"})).json()
    assert "approvals" in fresh["unavailable"]
    assert fresh["pending_approvals"] is None


async def test_overview_hides_what_the_viewer_cannot_see(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    overview = (await marcus.get("/api/v1/instances/prod-agentos/overview")).json()
    assert overview["activity"] is None
    assert overview["unavailable"]["activity"] == "You don't have audit:read."
    assert "schedules" not in overview["unavailable"] or "schedules:read" not in overview["unavailable"]["schedules"]


async def test_event_stream_replays_and_filters(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    async with stack.container() as request:
        bus = await request.get(EventBus)
        await bus.publish(
            instance_channel(instance["id"]), RealtimeEvent("approvals.count", {"count": 3}, instance_id=instance["id"])
        )
        await bus.publish(
            instance_channel("ins_other"), RealtimeEvent("approvals.count", {"count": 9}, instance_id="ins_other")
        )

    response = await owner.get("/api/v1/events", headers={"Last-Event-ID": "0"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [block for block in response.text.split("\n\n") if block.strip()]
    assert frames[0].startswith("event: ready")
    counts = [block for block in frames if "event: approvals.count" in block]
    assert len(counts) == 1
    data = json.loads(counts[0].rsplit("data: ", 1)[1])
    assert data == {"count": 3, "instance_id": instance["id"]}
    assert ": keepalive" in response.text


async def test_approvals_count_endpoint_and_poller(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    unavailable = (await owner.get("/api/v1/instances/prod-agentos/approvals/count")).json()
    assert unavailable == {"instance_id": instance["id"], "count": None, "available": False}

    pending_refund(fake)
    async with stack.container() as request:
        target = await (await request.get(InstancesFacade)).get(instance["id"])
        assert target is not None
        poller = await request.get(ApprovalsCountPoller)
        assert await poller.poll(target, force=True) == 1
    counted = (await owner.get("/api/v1/instances/prod-agentos/approvals/count")).json()
    assert counted["count"] == 1


async def test_search_finds_people_and_instances(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    people = (await owner.get("/api/v1/search", params={"q": "daniel"})).json()["data"]
    assert people[0]["kind"] == "member"
    assert people[0]["title"] == "Daniel Okafor"
    instances = (await owner.get("/api/v1/search", params={"q": "prod-age"})).json()["data"]
    assert any(hit["kind"] == "instance" and hit["url_path"] == "/i/prod-agentos/home" for hit in instances)
    assert (await owner.get("/api/v1/search", params={"q": "zzz-nothing"})).json()["data"] == []
