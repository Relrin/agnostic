"""Pure rules behind approvals, notifications, the scheduler and the queue."""

from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest

from agnostic_approvals.domain.inbox import (
    ApprovalEvent,
    ApprovalRecord,
    Expiry,
    Route,
    View,
    context_excerpt,
    display_status,
    effective_expiry,
    matching_routes,
    search_matches,
    timeline,
)
from agnostic_notifications.domain.catalog import QuietHours, personal_channels, valid_channels
from agnostic_notifications.domain.channels import InvalidChannelError, redact, validate_config
from agnostic_notifications.domain.messages import Action, Message, email_text, sign, slack_payload, webhook_body
from agnostic_queue.domain.jobs import Checkpoint, QueueJob, attempts_timeline, merge_workers
from agnostic_scheduler.domain.cron import CronError, describe, preview, validate
from agnostic_scheduler.domain.schedules import ScheduleRun, consecutive_failures, target_of

NOW = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)


def record(**overrides: Any) -> ApprovalRecord:
    body: dict[str, Any] = {
        "id": "apv_1",
        "status": "pending",
        "tool_name": "refund_customer",
        "tool_args": {"amount": 49.0},
        "agent_id": "billing-agent",
        "source_name": "billing-agent",
        "user_id": "zd:48121",
        "run_id": "run_1",
        "session_id": "ses_1",
        "created_at": int((NOW - timedelta(hours=2)).timestamp()),
        **overrides,
    }
    return ApprovalRecord.parse(body)


def route(**overrides: Any) -> Route:
    values: dict[str, Any] = {
        "id": "art_1",
        "instance_id": "ins_prod",
        "name": "Billing ops",
        "tool_name": None,
        "component_kind": None,
        "component_ids": (),
        "member_ids": ("usr_maya",),
        "role_ids": (),
        "channels": ("in_app",),
        "channel_ids": (),
        "created_by": None,
        "created_at": NOW,
        "updated_at": NOW,
        **overrides,
    }
    return Route(**values)


# ---------------------------------------------------------------- approvals


def test_effective_expiry_prefers_the_approval_then_the_step_then_the_ttl() -> None:
    own = record(expires_at=int((NOW + timedelta(hours=1)).timestamp()))
    assert effective_expiry(own, 24).source == "approval"
    step = record(workflow_id="refund-review", requirements=[{"timeout_at": (NOW + timedelta(minutes=5)).isoformat()}])
    assert effective_expiry(step, 24) == Expiry(NOW + timedelta(minutes=5), "step_timeout")
    ttl = effective_expiry(record(), 24)
    assert (ttl.source, ttl.at) == ("ttl", NOW - timedelta(hours=2) + timedelta(hours=24))
    assert effective_expiry(record(), 0) == Expiry(None, None)


def test_display_status_shows_expiry_the_agentos_way_and_ours() -> None:
    pending = record()
    assert display_status(pending, effective_expiry(pending, 24), NOW) == "pending"
    assert display_status(pending, effective_expiry(pending, 1), NOW) == "expired"
    enforced = record(status="rejected", resolution_data={"expired": True})
    assert display_status(enforced, Expiry(None, None), NOW) == "expired"
    assert display_status(record(status="rejected"), Expiry(None, None), NOW) == "rejected"


def test_instance_routes_win_over_org_routes_and_specific_over_broad() -> None:
    org = route(id="org", instance_id=None, name="Everyone")
    broad = route(id="broad", name="Support AI")
    tool = route(id="tool", name="Billing ops", tool_name="refund_customer")
    other_tool = route(id="other", tool_name="apply_account_credit")
    team_only = route(id="team", component_kind="team")
    found = matching_routes([org, broad, tool, other_tool, team_only], record(), "ins_prod")
    assert [r.id for r in found] == ["tool", "broad"]
    assert [r.id for r in matching_routes([org, other_tool], record(), "ins_prod")] == ["org"]


def test_timeline_narrates_routing_views_and_the_decision() -> None:
    events = [
        ApprovalEvent(
            "routed", NOW - timedelta(hours=2), {"routed_to": ["Support AI", "Billing ops"], "channels": ["Slack"]}
        ),
        ApprovalEvent("continued", NOW, {"continue_state": "continued"}),
    ]
    views = [View("usr_maya", "Maya Chen", NOW - timedelta(hours=1))]
    waiting = timeline(
        record(),
        status="pending",
        expiry=Expiry(None, None),
        events=events,
        views=views,
        resolver_name=None,
        run_status=None,
    )
    assert [entry.text for entry in waiting] == [
        "Run paused at refund_customer · run_status PAUSED",
        "Routed to Support AI and Billing ops",
        "Viewed by Maya Chen",
        "Waiting for a decision",
    ]
    assert waiting[-1].state == "now"
    approved = record(status="approved", resolved_at=int(NOW.timestamp()))
    done = timeline(
        approved,
        status="approved",
        expiry=Expiry(None, None),
        events=events,
        views=[],
        resolver_name="Maya Chen",
        run_status="COMPLETED",
    )
    assert [entry.text for entry in done][-3:] == ["Approved by Maya Chen", "Run continued", "Run is completed"]
    assert done[-1].state == "end"


def test_context_excerpt_and_search() -> None:
    run = {
        "run_input": "Refund order #4471",
        "messages": [
            {"role": "user", "content": "Refund order #4471"},
            {"role": "assistant", "content": [{"type": "text", "text": "Refunding the duplicate."}]},
            {"role": "tool", "content": "{}"},
        ],
    }
    excerpt = context_excerpt(run)
    assert (excerpt.user_message, excerpt.agent_message) == ("Refund order #4471", "Refunding the duplicate.")
    assert context_excerpt(None).user_message is None
    assert search_matches(record(), "Maya", {"zd:48121": "Maya Chen"})
    assert search_matches(record(), "run_1", {})
    assert not search_matches(record(), "nothing", {})


# ---------------------------------------------------------------- notifications


def test_personal_channels_preference_default_routing_and_quiet_hours() -> None:
    assert personal_channels("approval.created", preference=None, org_default=None) == ("in_app",)
    assert personal_channels("approval.created", preference=None, org_default=["email"]) == ("email",)
    assert personal_channels("approval.created", preference=["in_app"], org_default=["email"], forced=["slack"]) == (
        "in_app",
        "slack",
    )
    quiet = QuietHours(time(22, 0), time(7, 0), "Europe/Berlin")
    night = datetime(2026, 11, 3, 23, 30, tzinfo=UTC)  # 00:30 in Berlin
    assert quiet.contains(night)
    assert not quiet.contains(datetime(2026, 11, 3, 12, 0, tzinfo=UTC))
    assert personal_channels(
        "approval.created", preference=["in_app", "slack"], org_default=None, quiet=quiet, now=night
    ) == ("in_app",)
    with pytest.raises(ValueError, match="Unknown channels"):
        valid_channels(["pager"])


def test_channel_config_validation_keeps_secrets_and_redacts_them() -> None:
    config = validate_config("slack", {"mode": "bot", "token": "xoxb-123456789", "channel": "C0OPS"})
    assert config == {"mode": "bot", "token": "xoxb-123456789", "channel": "C0OPS", "direct_messages": True}
    kept = validate_config("slack", {"channel": "C0NEW", "token": ""}, config)
    assert kept["token"] == "xoxb-123456789"
    assert redact(kept)["token"] == "…6789"
    assert validate_config("email", {"to": "ops@northwind.dev"}) == {"to": ["ops@northwind.dev"]}
    with pytest.raises(InvalidChannelError):
        validate_config("webhook", {"url": "ftp://nope"})
    with pytest.raises(InvalidChannelError):
        validate_config("slack", {"mode": "bot"})


def test_messages_render_link_buttons_email_and_signed_webhooks() -> None:
    message = Message(
        event_type="approval.created",
        title="refund_customer needs approval",
        body="agent billing-agent · amount=49.0 <script>",
        url="https://agnostic.example/i/prod/approvals?approval=apv_1",
        actions=(Action("Approve", "https://agnostic.example/x&intent=approve", "primary"),),
        context="prod-agentos",
    )
    payload = slack_payload(message)
    assert "&lt;script&gt;" in payload["blocks"][0]["text"]["text"]
    button = payload["blocks"][1]["elements"][0]
    assert (button["url"], button["style"]) == ("https://agnostic.example/x&intent=approve", "primary")
    assert "action_id" in button
    assert "value" not in button  # links only: no interactive callbacks
    subject, text = email_text(message)
    assert subject == "refund_customer needs approval"
    assert "Approve: https://agnostic.example/x&intent=approve" in text
    body = webhook_body(message, delivery_id="ndl_1", sent_at="2026-11-03T15:00:00+00:00")
    assert sign("secret", body) == sign("secret", body)
    assert sign("secret", body) != sign("other", body)
    assert Message.from_dict(message.to_dict()) == message


# ---------------------------------------------------------------- scheduler


@pytest.mark.parametrize(
    ("expression", "sentence"),
    [
        ("0 3 * * *", "Every day at 03:00"),
        ("0 */6 * * *", "Every 6 hours, on the hour"),
        ("*/30 8-18 * * 1-5", "Every 30 minutes, 08:00–18:59, Monday to Friday"),
        ("30 7 * * 1", "Every Monday at 07:30"),
        ("0 9 * * 5", "Every Friday at 09:00"),
        ("0 9 1,15 * *", "On the 1st and 15th of the month at 09:00"),
        ("0 9 * * 6,0", "On weekends at 09:00"),
        ("5 4 L * *", "Custom schedule: 5 4 L * *"),
    ],
)
def test_cron_sentences(expression: str, sentence: str) -> None:
    assert describe(expression) == sentence


def test_cron_preview_warns_about_daylight_saving() -> None:
    start = datetime(2026, 10, 30, 23, 0, tzinfo=UTC)
    result = preview("*/30 8-18 * * 1-5", "America/New_York", start=start)
    assert result.runs[0].local.isoformat() == "2026-11-02T08:00:00-05:00"
    assert result.runs[0].utc.strftime("%H:%M") == "13:00"
    assert result.notes == [
        "Daylight saving ends Sun 1 Nov in America/New_York: these runs move from 12:00 to 13:00 UTC."
    ]
    repeated = preview("30 1 * * *", "America/New_York", start=datetime(2026, 10, 31, 12, tzinfo=UTC))
    assert any("happens twice" in note for note in repeated.notes)
    assert preview("0 3 * * *", "UTC", start=start).notes == []
    assert preview("0 3 * * *", "Europe/Berlin", start=datetime(2026, 12, 1, tzinfo=UTC)).notes == []


def test_cron_validation_names_bad_fields() -> None:
    with pytest.raises(CronError) as bad:
        validate("61 * * * *")
    assert bad.value.fields == ("minute",)
    with pytest.raises(CronError):
        validate("* * *")
    with pytest.raises(CronError):
        preview("0 3 * * *", "Mars/Olympus", start=NOW)


def test_schedule_targets_runs_and_failure_streaks() -> None:
    assert target_of("POST", "/workflows/daily-brief/runs").kind == "workflow"
    assert target_of("POST", "/agents/kb-researcher/runs/").id == "kb-researcher"
    assert target_of("GET", "/agents/kb-researcher/runs").kind == "custom"
    assert target_of("POST", "/custom/cleanup").kind == "custom"
    runs = [
        ScheduleRun.parse({"id": "3", "status": "failed", "attempt": 2}),
        ScheduleRun.parse({"id": "2", "status": "error"}),
        ScheduleRun.parse({"id": "1", "status": "completed"}),
        ScheduleRun.parse({"id": "0", "status": "failed"}),
    ]
    assert consecutive_failures(runs) == 2
    assert runs[0].attempt_label(1) == "retry 1 of 1"
    paused = ScheduleRun.parse(
        {
            "status": "completed",
            "requirements": [{"x": 1}],
            "triggered_at": 1792900000,
            "completed_at": 1792900000 + 33 * 60,
        }
    )
    assert (paused.states, paused.attempt_label(0)) == (["PAUSED", "COMPLETED"], "paused 33 min for confirmation")


# ---------------------------------------------------------------- queue


def job(**overrides: Any) -> QueueJob:
    body: dict[str, Any] = {
        "id": "run_5c81e0",
        "component_type": "agent",
        "component_id": "support-triage",
        "status": "failed",
        "attempt": 2,
        "max_attempts": 2,
        "idempotency_key": "zd-50112-msg-3",
        "locked_by": "worker-1",
        "created_at": int(NOW.timestamp()),
        **overrides,
    }
    return QueueJob.parse(body)


def test_attempts_timeline_and_detail() -> None:
    entries = attempts_timeline(job(), retry_delay_seconds=30)
    assert [entry.text for entry in entries] == [
        "Accepted · 202 with run_id",
        "Attempt 1 was retried",
        "Attempt 2 claimed by worker-1",
        "Attempt 2 ended in ERROR · job marked failed",
    ]
    assert entries[-1].detail == "max_attempts 2 reached"
    assert job().detail("ERROR") == "run ERROR"
    assert job(status="queued", locked_by=None).detail() == "not claimed"
    assert job().family == "agents"


def test_workers_merge_bridge_snapshots_with_running_jobs() -> None:
    snapshots = [
        {
            "replica_id": "prod-0",
            "worker_id": "worker-1",
            "heartbeat_at": int(NOW.timestamp()),
            "max_concurrency": 4,
            "in_flight": ["a"],
        },
        {"replica_id": "prod-1", "worker_id": "worker-9", "heartbeat_at": int((NOW - timedelta(hours=1)).timestamp())},
    ]
    running = [job(id="a", status="running"), job(id="b", status="running", locked_by="worker-2")]
    workers = merge_workers(snapshots, running, now=NOW, stale_after=timedelta(minutes=2))
    assert [(w.name, w.slots_busy, w.source) for w in workers] == [("prod-0", 1, "bridge"), ("worker-2", 1, "jobs")]


def test_checkpoint_titles() -> None:
    tool = Checkpoint.parse(
        {
            "checkpoint_id": "2",
            "message_index": 5,
            "message_role": "tool",
            "message_preview": "zendesk_search: ticket #50112",
        },
        1,
    )
    assert (tool.number, tool.message_index, tool.title) == (2, 5, "After zendesk_search")
    end = Checkpoint.parse({"message_index": 9, "reason": "end"}, 3)
    assert (end.number, end.title) == (3, "End of the run")
