"""Control flows against a fake AgentOS: the approvals inbox, routing and expiry; notifications (inbox, preferences,
Slack); schedules with previews and custom endpoints; the durable queue through delegated elevation."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from agnostic_approvals.application.watch import WatchApprovals
from agnostic_kernel.testing import wait_for
from agnostic_scheduler.application.watch import WatchScheduleFailures
from tests.api.test_instances_gateway import connect, invite_operator
from tests.api.test_operate import audit_events, pending_refund
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

NOW = datetime.now(UTC)


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__CONTINUE_RETRY_DELAYS", "[0.01]")
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_APPROVALS__WATCH_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SCHEDULER__WATCH_CRON", "")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    monkeypatch.setenv("AGNOSTIC_NOTIFICATIONS__DELIVERY_RETRIES", "0")
    async with running_stack(sqlite_database) as running:
        yield running


async def watch_approvals(stack: Stack, now: datetime | None = None) -> Any:
    async with stack.container() as request:
        return await (await request.get(WatchApprovals))(now)


async def user_id(client: httpx.AsyncClient) -> str:
    return str((await client.get("/api/v1/me")).json()["id"])


def slack_channel(**config: Any) -> dict[str, Any]:
    return {
        "kind": "slack",
        "name": "Slack · billing-ops",
        "config": {"mode": "bot", "token": "xoxb-test-token", "channel": "C0BILLING", **config},
        "events": [],
    }


# ---------------------------------------------------------------- approvals


async def test_inbox_lists_counts_and_details_with_views(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    pending_refund(fake, approval_id="apv_7Kq2")
    resolved = pending_refund(fake, approval_id="apv_7Jz1")
    resolved.update(status="approved", resolved_by="Maya Chen (usr_maya)", resolved_at=int(NOW.timestamp()))
    fake.runs["run_9f2c41"] = {
        "run_id": "run_9f2c41",
        "session_id": "ses_7f3a91c2",
        "status": "PAUSED",
        "run_input": "My card was charged twice for order #4471. Can you refund one of them?",
        "messages": [
            {"role": "user", "content": "My card was charged twice for order #4471. Can you refund one of them?"},
            {"role": "assistant", "content": "Found two identical $49.00 charges. Refunding the duplicate."},
        ],
    }

    # Under user isolation Marcus (an Operator) still sees Dana's approvals: the control plane reads them.
    listed = await marcus.get("/api/v1/instances/prod-agentos/approvals", params={"status": "pending"})
    assert listed.status_code == 200, listed.text
    rows = listed.json()["data"]
    assert [row["id"] for row in rows] == ["apv_7Kq2"]
    assert rows[0]["type"] == "blocking"
    assert rows[0]["source_kind"] == "agent"
    assert rows[0]["expires_at"] is None  # no org TTL, and AgentOS sets none

    counts = (await marcus.get("/api/v1/instances/prod-agentos/approvals/counts")).json()
    assert (counts["pending"], counts["approved"], counts["expired"]) == (1, 1, 0)

    searched = await marcus.get("/api/v1/instances/prod-agentos/approvals", params={"status": "pending", "q": "4471x"})
    assert searched.json()["data"] == []
    by_tool = await marcus.get(
        "/api/v1/instances/prod-agentos/approvals", params={"status": "pending", "tool": "refund_customer"}
    )
    assert len(by_tool.json()["data"]) == 1

    detail = (await marcus.get("/api/v1/instances/prod-agentos/approvals/apv_7Kq2")).json()
    assert detail["context"]["user_message"].startswith("My card was charged twice")
    assert detail["context"]["agent_message"].startswith("Found two identical")
    assert detail["can_resolve"] is True
    assert detail["views"][0]["name"] == "Marcus Chen"
    texts = [entry["text"] for entry in detail["timeline"]]
    assert texts[0] == "Run paused at refund_customer · run_status PAUSED"
    assert "Viewed by Marcus Chen" in texts
    assert detail["timeline"][-1]["state"] == "now"

    again = (await marcus.get("/api/v1/instances/prod-agentos/approvals/apv_7Kq2")).json()
    assert len(again["views"]) == 1  # a person counts once

    viewer_scopes = await owner.get("/api/v1/instances/prod-agentos/approvals/apv_7Jz1")
    assert viewer_scopes.json()["status"] == "approved"
    assert viewer_scopes.json()["can_resolve"] is False


async def test_routing_notifies_routed_people_in_app_and_on_slack(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    daniel_id = await user_id(owner)

    channel = await owner.post("/api/v1/notifications/channels", json=slack_channel())
    assert channel.status_code == 201, channel.text
    assert channel.json()["config"]["token"] == "…oken"  # secrets never come back in full
    roles = {role["slug"]: role["id"] for role in (await owner.get("/api/v1/access/roles")).json()}

    denied = await marcus.post("/api/v1/approvals/routes", json={"name": "Everyone", "role_ids": [roles["operator"]]})
    assert denied.status_code == 403  # org-wide rules need settings:write
    route = await marcus.post(
        "/api/v1/instances/prod-agentos/approvals/routes",
        json={
            "name": "Billing ops",
            "tool_name": "refund_customer",
            "member_ids": [daniel_id],
            "role_ids": [roles["operator"]],
            "channels": ["in_app", "slack"],
            "channel_ids": [channel.json()["id"]],
        },
    )
    assert route.status_code == 201, route.text
    assert route.json()["roles"] == [{"id": roles["operator"], "name": "Operator"}]

    pending_refund(fake, approval_id="apv_7Kq2")
    summary = await watch_approvals(stack)
    assert summary.routed == 1
    assert (await watch_approvals(stack)).routed == 0  # routed once

    inbox = (await marcus.get("/api/v1/notifications")).json()["data"]
    assert inbox[0]["kind"] == "approval.created"
    assert inbox[0]["link"] == "/i/prod-agentos/approvals?approval=apv_7Kq2"
    assert (await marcus.get("/api/v1/notifications/unread-count")).json()["unread"] == 1

    messages = await wait_for(lambda: _messages(stack), lambda found: len(found) >= 2)
    posted = next(m for m in messages if m["channel"] == "C0BILLING")
    buttons = next(block for block in posted["blocks"] if block["type"] == "actions")["elements"]
    assert [button["text"]["text"] for button in buttons] == ["Approve", "Reject"]
    assert buttons[0]["url"] == "http://agnostic.test/i/prod-agentos/approvals?approval=apv_7Kq2&intent=approve"
    assert any(m["channel"] == "U0DANIEL" for m in messages)  # Daniel's DM: the route forces Slack

    detail = (await owner.get("/api/v1/instances/prod-agentos/approvals/apv_7Kq2")).json()
    assert detail["routed_to"] == ["Billing ops"]
    assert any(entry["text"] == "Routed to Billing ops" for entry in detail["timeline"])

    read = await marcus.post("/api/v1/notifications/read", json={})
    assert read.json() == {"changed": 1, "unread": 0}


async def _messages(stack: Stack) -> list[dict[str, Any]]:
    return stack.slack.messages()


async def test_expiry_from_org_ttl_shown_then_enforced(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    pending_refund(fake, approval_id="apv_old")
    assert (await owner.patch("/api/v1/org", json={"settings": {"approval_ttl_hours": 1}})).status_code == 200

    shown = (await owner.get("/api/v1/instances/prod-agentos/approvals", params={"status": "expired"})).json()
    assert [row["id"] for row in shown["data"]] == ["apv_old"]
    assert shown["data"][0]["expiry_source"] == "ttl"
    assert shown["data"][0]["expiry_enforced"] is False
    await watch_approvals(stack)
    assert fake.resolutions == []  # not enforced by default: faithful to AgentOS

    policy = await owner.put("/api/v1/instances/prod-agentos/approvals/policy", json={"enforce_expiry": True})
    assert policy.json()["enforce_expiry"] is True
    summary = await watch_approvals(stack)
    assert summary.expired == 1
    resolution = fake.resolutions[-1]["body"]
    assert (resolution["status"], resolution["resolution_data"]["expired"]) == ("rejected", True)
    assert fake.continuations[-1]["run_id"] == "run_9f2c41"

    expired = (await owner.get("/api/v1/instances/prod-agentos/approvals", params={"status": "expired"})).json()
    assert expired["data"][0]["expiry_enforced"] is True
    assert [e["summary"] for e in await audit_events(owner, "approvals.expired")] == [
        "refund_customer on prod-agentos expired without a decision"
    ]


async def test_reminder_before_expiry(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    approval = pending_refund(fake, approval_id="apv_soon")
    approval["expires_at"] = int((NOW + timedelta(minutes=30)).timestamp())
    summary = await watch_approvals(stack)
    assert summary.reminded == 1
    kinds = [item["kind"] for item in (await owner.get("/api/v1/notifications")).json()["data"]]
    assert "approval.expiring" in kinds


# ---------------------------------------------------------------- notifications


async def test_preferences_defaults_quiet_hours_and_channels(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])

    mine = (await marcus.get("/api/v1/me/notification-preferences")).json()
    created = next(p for p in mine["events"] if p["event"]["name"] == "approval.created")
    assert (created["channels"], created["custom"], mine["slack_available"]) == (["in_app"], False, False)

    updated = await marcus.put(
        "/api/v1/me/notification-preferences",
        json={"events": {"approval.created": ["in_app", "slack"]}, "quiet_hours": {"start": "22:00", "end": "07:00"}},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert next(p for p in body["events"] if p["event"]["name"] == "approval.created")["channels"] == [
        "in_app",
        "slack",
    ]
    assert body["quiet_hours"] == {"start": "22:00", "end": "07:00", "timezone": "UTC"}
    bad = await marcus.put("/api/v1/me/notification-preferences", json={"events": {"nope": ["in_app"]}})
    assert bad.status_code == 422

    assert (await marcus.get("/api/v1/notifications/channels")).status_code == 403
    assert (await marcus.put("/api/v1/notifications/defaults", json={"events": {}})).status_code == 403
    defaults = await owner.put(
        "/api/v1/notifications/defaults", json={"events": {"schedule.failed": ["in_app", "email"]}}
    )
    assert defaults.json()["events"]["schedule.failed"] == ["in_app", "email"]

    hook = await owner.post(
        "/api/v1/notifications/channels",
        json={
            "kind": "webhook",
            "name": "Ops webhook",
            "config": {"url": "https://receiver.test/agnostic", "secret": "s3cret-value"},
            "events": ["schedule.failed"],
        },
    )
    assert hook.status_code == 201
    tested = await owner.post(f"/api/v1/notifications/channels/{hook.json()['id']}/test")
    assert tested.json()["status"] == "sent"
    sent = stack.slack.requests[-1]
    assert sent["headers"]["X-Agnostic-Signature"].startswith("sha256=")

    broken = await owner.post("/api/v1/notifications/channels", json=slack_channel(token="xoxb-wrong"))
    failed = await owner.post(f"/api/v1/notifications/channels/{broken.json()['id']}/test")
    assert (failed.json()["status"], failed.json()["error"]) == (
        "failed",
        "Slack chat.postMessage failed: invalid_auth",
    )
    assert [e["action"] for e in await audit_events(owner, "notifications.channel.created")] == [
        "notifications.channel.created",
        "notifications.channel.created",
    ]


# ---------------------------------------------------------------- scheduler


def daily_brief(fake: FakeAgentOS) -> dict[str, Any]:
    schedule = {
        "id": "sch_daily",
        "name": "daily-brief",
        "description": "Morning brief for support leads",
        "method": "POST",
        "endpoint": "/workflows/daily-brief/runs",
        "payload": {"message": "Write today's brief", "stream": False},
        "cron_expr": "0 3 * * *",
        "timezone": "UTC",
        "timeout_seconds": 900,
        "max_retries": 1,
        "retry_delay_seconds": 300,
        "enabled": True,
        "user_id": None,
        "next_run_at": 1793000000,
    }
    fake.schedules.append(schedule)
    fake.schedule_runs["sch_daily"] = [
        {
            "id": "r3",
            "schedule_id": "sch_daily",
            "attempt": 2,
            "status": "failed",
            "error": "timed out in web_search",
            "run_id": "run_c47e90",
            "triggered_at": 1792990000,
            "completed_at": 1792990031,
        },
        {
            "id": "r2",
            "schedule_id": "sch_daily",
            "attempt": 1,
            "status": "failed",
            "error": "timed out",
            "run_id": "run_d81f2a",
            "triggered_at": 1792989700,
            "completed_at": 1792989731,
        },
        {
            "id": "r1",
            "schedule_id": "sch_daily",
            "attempt": 1,
            "status": "completed",
            "triggered_at": 1792900000,
            "completed_at": 1792900041,
        },
    ]
    return schedule


async def test_schedules_list_preview_disable_and_custom_endpoints(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    daily_brief(fake)

    listed = (await marcus.get("/api/v1/instances/prod-agentos/schedules")).json()
    row = listed["data"][0]
    assert (row["human"], row["target_kind"], row["target_id"]) == ("Every day at 03:00", "workflow", "daily-brief")
    assert row["consecutive_failures"] == 2
    assert row["last_runs"][0]["attempt_label"] == "retry 1 of 1"

    preview = await marcus.post(
        "/api/v1/instances/prod-agentos/schedules/preview",
        json={"cron_expr": "*/30 8-18 * * 1-5", "timezone": "America/New_York", "start": "2026-10-30T23:00:00Z"},
    )
    body = preview.json()
    assert body["human"] == "Every 30 minutes, 08:00–18:59, Monday to Friday"
    assert body["runs"][0]["utc"].startswith("2026-11-02T13:00:00")
    assert body["notes"] == [
        "Daylight saving ends Sun 1 Nov in America/New_York: these runs move from 12:00 to 13:00 UTC."
    ]
    invalid = await marcus.post(
        "/api/v1/instances/prod-agentos/schedules/preview", json={"cron_expr": "61 * * * *", "timezone": "UTC"}
    )
    assert invalid.status_code == 422
    assert invalid.json()["fields"] == ["minute"]

    disabled = await marcus.post(
        "/api/v1/instances/prod-agentos/schedules/sch_daily/disable",
        json={"reason": "Paused until web_search is fixed"},
    )
    assert disabled.json()["enabled"] is False
    assert disabled.json()["disabled_note"]["by_name"] == "Marcus Chen"
    enabled = await marcus.post("/api/v1/instances/prod-agentos/schedules/sch_daily/enable")
    assert enabled.json()["disabled_note"] is None

    custom = {"name": "nightly-cleanup", "cron_expr": "0 2 * * *", "endpoint": "/custom/cleanup"}
    refused = await marcus.post("/api/v1/instances/prod-agentos/schedules", json=custom)
    assert refused.status_code == 403  # Instance admin only, checked before anything reaches AgentOS
    assert not any(s["name"] == "nightly-cleanup" for s in fake.schedules)
    created = await owner.post("/api/v1/instances/prod-agentos/schedules", json=custom)
    assert created.status_code == 201, created.text
    assert created.json()["target_kind"] == "custom"
    audited = await audit_events(owner, "schedules.create")
    assert audited[0]["links"]["target"] == "custom"

    run_target = await marcus.post(
        "/api/v1/instances/prod-agentos/schedules",
        json={"name": "kb-sync", "cron_expr": "0 */6 * * *", "endpoint": "/agents/kb-researcher/runs"},
    )
    assert run_target.status_code == 201, run_target.text
    triggered = await marcus.post(f"/api/v1/instances/prod-agentos/schedules/{run_target.json()['id']}/trigger")
    assert triggered.json()["status"] == "running"


async def test_failure_watcher_announces_each_failure_once(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    daily_brief(fake)

    async def watch() -> int:
        async with stack.container() as request:
            return await (await request.get(WatchScheduleFailures))()

    assert await watch() == 1
    assert await watch() == 0
    item = (await owner.get("/api/v1/notifications")).json()["data"][0]
    assert (item["kind"], item["title"]) == ("schedule.failed", "daily-brief failed twice")


# ---------------------------------------------------------------- queue


def failed_job(fake: FakeAgentOS) -> None:
    fake.queue_enabled = True
    fake.queue_jobs["run_5c81e0"] = {
        "id": "run_5c81e0",
        "component_type": "agent",
        "component_id": "support-triage",
        "session_id": "ses_50112",
        "user_id": "zd:50112",
        "status": "failed",
        "attempt": 2,
        "max_attempts": 2,
        "idempotency_key": "zd-50112-msg-3",
        "locked_by": "worker-1a2b",
        "error": "ModelProviderError: 529",
        "created_at": 1792990000,
        "completed_at": 1792990074,
    }
    fake.queue_jobs["run_7d22c1"] = {
        "id": "run_7d22c1",
        "component_type": "agent",
        "component_id": "support-triage",
        "status": "running",
        "attempt": 1,
        "max_attempts": 2,
        "locked_by": "worker-1a2b",
        "created_at": 1792990100,
    }
    fake.checkpoints["run_5c81e0"] = [
        {"checkpoint_id": "1", "message_index": 3, "message_role": "tool", "message_preview": "kb_lookup: 3 articles"},
        {"checkpoint_id": "2", "message_index": 5, "message_role": "tool", "message_preview": "zendesk_search: #50112"},
    ]
    fake.bridge_workers = {
        "replica_id": "prod-agentos-0",
        "worker_id": "worker-1a2b",
        "deployment_id": "2026-10-31.2",
        "heartbeat_at": int(datetime.now(UTC).timestamp()),
        "max_concurrency": 4,
        "in_flight": ["run_7d22c1"],
        "queue": {"configured": True, "durable": True, "max_queue_depth": 1000, "lock_grace_seconds": 60},
        "scheduler": {"enabled": True, "poll_interval_seconds": 15},
    }


async def test_operator_recovers_a_failed_job_through_elevation(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    failed_job(fake)

    overview = await marcus.get("/api/v1/instances/prod-agentos/queue/overview")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert (body["summary"]["access"], body["summary"]["counts"]["failed"]) == ("elevated", 1)
    assert body["workers"][0] | {"heartbeat_at": None} == {
        "name": "prod-agentos-0",
        "worker_id": "worker-1a2b",
        "heartbeat_at": None,
        "slots_busy": 1,
        "slots_total": 4,
        "deployment": "2026-10-31.2",
        "source": "bridge",
    }
    assert body["config"]["max_queue_depth"] == 1000

    jobs = (await marcus.get("/api/v1/instances/prod-agentos/queue/jobs", params={"status": "failed"})).json()
    assert [job["id"] for job in jobs["data"]] == ["run_5c81e0"]
    detail = (await marcus.get("/api/v1/instances/prod-agentos/queue/jobs/run_5c81e0")).json()
    assert [c["message_index"] for c in detail["checkpoints"]] == [3, 5]
    assert detail["checkpoints"][1]["title"] == "After zendesk_search"
    assert detail["attempts"][-1]["text"] == "Attempt 2 ended in ERROR · job marked failed"

    resumed = await marcus.post(
        "/api/v1/instances/prod-agentos/queue/jobs/run_5c81e0/resume", json={"message_index": 5}
    )
    assert resumed.status_code == 200, resumed.text
    continuation = fake.continuations[-1]
    assert (continuation["form"]["continue_from"], continuation["form"]["session_id"]) == ("5", "ses_50112")
    assert continuation["claims"]["scopes"] == ["agent_os:admin"]

    requeued = await marcus.post("/api/v1/instances/prod-agentos/queue/jobs/run_5c81e0/requeue", json={})
    assert requeued.json()["status"] == "queued"
    cancelled = await marcus.post("/api/v1/instances/prod-agentos/queue/jobs/run_7d22c1/cancel")
    assert cancelled.json()["status"] == "cancelled"

    elevated = await audit_events(owner, "gateway.elevated")
    assert {event["scope_checked"] for event in elevated} == {"queue:operate"}
    actions = {event["action"] for event in await audit_events(owner, "queue.resume")}
    assert actions == {"queue.resume"}
    assert len(await audit_events(owner, "queue.requeue")) == 1
    assert len(await audit_events(owner, "queue.cancel")) == 1


async def test_queue_without_queue_operate_shows_counts_only(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    failed_job(fake)
    roles = {role["slug"]: role["id"] for role in (await owner.get("/api/v1/access/roles")).json()}
    invited = await owner.post(
        "/api/v1/invitations",
        json={
            "email": "vera@localhost.company",
            "bindings": [{"role_id": roles["viewer"], "instance_id": instance["id"]}],
        },
    )
    token = invited.json()["accept_url"].rsplit("/", 1)[1]
    vera = stack.client()
    joined = await vera.post(
        f"/api/v1/invitations/{token}/accept", json={"display_name": "Vera Lin", "password": "vera's long password"}
    )
    vera.headers["X-CSRF-Token"] = joined.json()["csrf_token"]

    summary = (await vera.get("/api/v1/instances/prod-agentos/queue/summary")).json()
    assert (summary["access"], summary["counts"]["running"]) == (None, 1)
    assert "queue:operate" in summary["explanation"]
    refused = await vera.get("/api/v1/instances/prod-agentos/queue/jobs")
    assert (refused.status_code, refused.json()["code"]) == (403, "queue_requires_admin")


async def test_privileged_grants_reach_owners_and_administrators(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    roles = {role["slug"]: role["id"] for role in (await owner.get("/api/v1/access/roles")).json()}

    granted = await owner.post(
        "/api/v1/access/bindings",
        json={"user_id": await user_id(marcus), "instance": "prod-agentos", "role_id": roles["instance-admin"]},
    )
    assert granted.status_code == 201, granted.text

    async def bell() -> list[dict[str, Any]]:
        return (await owner.get("/api/v1/notifications")).json()["data"]

    items = await wait_for(bell, lambda found: any(i["kind"] == "access.privileged_grant" for i in found))
    grant = next(i for i in items if i["kind"] == "access.privileged_grant")
    assert grant["title"] == "Daniel Okafor gave Marcus Chen Instance admin on prod-agentos"
    assert grant["link"] == "/access/people"
