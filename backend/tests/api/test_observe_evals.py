"""Flows against a fake AgentOS: trace comparison and span statistics, the Metrics page with price tables and CSV,
and evaluations from dataset to version comparison and publish gate (batches run on the embedded job worker)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from agnostic_kernel.ephemeral import EphemeralStore
from tests.api.test_instances_gateway import connect, invite_operator
from tests.support.stack import Stack, running_stack
from tests.unit.test_observe_traces_metrics import daily_brief_today, daily_brief_yesterday

NOW = datetime.now(UTC)
BASE = "/api/v1/instances/prod-agentos"


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


def shifted(value: Any, delta: timedelta) -> Any:
    """Move every start/end time of a trace body by ``delta``."""
    if isinstance(value, list):
        return [shifted(item, delta) for item in value]
    if isinstance(value, dict):
        moved: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"start_time", "end_time"} and isinstance(item, str):
                moved[key] = (datetime.fromisoformat(item) + delta).isoformat()
            else:
                moved[key] = shifted(item, delta)
        return moved
    return value


def summary(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        key: detail[key]
        for key in ("trace_id", "name", "status", "start_time", "end_time", "workflow_id", "user_id")
        if key in detail
    } | {"error_count": 0 if detail["status"] == "OK" else 1, "duration": "1s"}


def daily_brief_pair(fake: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    today = shifted(daily_brief_today(), NOW - timedelta(hours=1) - datetime(2026, 11, 1, 3, 0, tzinfo=UTC))
    yesterday = shifted(daily_brief_yesterday(), NOW - timedelta(days=1) - datetime(2026, 11, 1, 3, 0, tzinfo=UTC))
    for body in (today, yesterday):
        body["user_id"] = "sa:scheduler"
        fake.trace_details[body["trace_id"]] = body
    fake.traces = [summary(today), summary(yesterday)]
    return today, yesterday


async def test_trace_comparison_with_the_last_successful_run(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    today, yesterday = daily_brief_pair(fake)

    first = await owner.get(f"{BASE}/traces/{today['trace_id']}/comparison")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["baseline"]["trace_id"] == yesterday["trace_id"]
    assert body["baseline"]["version"] == 3
    assert body["same_version"] is True
    assert body["cached"] is False
    assert body["generated"] is False
    assert body["diagnosis"].endswith("so the workflow never reached `Write brief`.")
    states = {row["name"]: row["state"] for row in body["rows"]}
    assert states["web_search"] == "error"
    assert states["Write brief"] == "not_run"
    search = next(row for row in body["rows"] if row["name"] == "web_search")
    assert (search["baseline"]["count"], search["current"]["count"]) == (1, 2)
    assert {ghost["span_id"] for ghost in body["ghosts"]} >= {"web_search@1.7"}

    again = (await owner.get(f"{BASE}/traces/{today['trace_id']}/comparison")).json()
    assert again["cached"] is True
    assert again["diagnosis"] == body["diagnosis"]

    # The baseline itself has no earlier successful run.
    alone = (await owner.get(f"{BASE}/traces/{yesterday['trace_id']}/comparison")).json()
    assert alone["baseline"] is None
    assert alone["reason"] == "No successful run of daily-brief before this one."

    # Under user isolation an operator can't read the scheduler's trace, cached or not.
    marcus = await invite_operator(stack, owner, instance["id"])
    hidden = await marcus.get(f"{BASE}/traces/{today['trace_id']}/comparison")
    assert hidden.status_code == 404


async def test_span_stats_are_cached_per_window(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    daily_brief_pair(fake)

    stats = (await owner.get(f"{BASE}/traces/span-stats", params={"window": "7d"})).json()
    assert stats["traces_scanned"] == 2
    assert stats["sampled"] is False
    assert stats["cached"] is False
    names = [item["name"] for item in stats["stats"]]
    assert names[0] == "daily-brief.run"
    search = next(item for item in stats["stats"] if item["name"] == "web_search")
    assert (search["count"], search["errors"], search["kind"]) == (3, 2, "tool")

    fake.traces = []
    cached = (await owner.get(f"{BASE}/traces/span-stats", params={"window": "7d"})).json()
    assert cached["cached"] is True
    assert cached["stats"] == stats["stats"]


def session_item(session_id: str, component: str, user: str, models: dict[str, tuple[int, int]]) -> dict[str, Any]:
    details = [
        {"id": model, "provider": "anthropic", "input_tokens": i, "output_tokens": o}
        for model, (i, o) in models.items()
    ]
    return {
        "session_id": session_id,
        "session_type": "agent",
        "agent_id": component,
        "user_id": user,
        "created_at": (NOW - timedelta(days=1)).isoformat(),
        "updated_at": (NOW - timedelta(hours=2)).isoformat(),
        "metrics": {
            "input_tokens": sum(i for i, _ in models.values()),
            "output_tokens": sum(o for _, o in models.values()),
            "details": {"model": details},
        },
    }


async def test_metrics_summary_prices_and_csv(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    today = NOW.date()
    fake.metrics_rows = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "agent_runs_count": 10,
            "team_runs_count": 2,
            "workflow_runs_count": 3,
            "agent_sessions_count": 4,
            "users_count": 2,
            "token_metrics": {"input_tokens": 1_000_000, "output_tokens": 200_000, "cache_read_tokens": 100_000},
            "model_metrics": [{"model_id": "claude-opus-5-5", "model_provider": "anthropic", "count": 15}],
        }
        for offset in range(3)
    ]
    fake.session_items = [
        session_item("s1", "support-triage", "u1", {"claude-opus-5-5": (1_000_000, 100_000)}),
        session_item("s2", "billing-agent", "u2", {"claude-opus-5-5": (500_000, 50_000)}),
    ]
    fake.traces = [
        {"trace_id": f"t{i}", "status": "OK", "agent_id": "support-triage", "start_time": NOW.isoformat()}
        for i in range(4)
    ]

    saved = await owner.put(
        f"{BASE}/price-table",
        json={
            "prices": [{"model_id": "claude-opus-5-5", "provider": "anthropic", "input_per_1m": 5, "output_per_1m": 25}]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["prices"][0]["source"] == "instance"

    params = {"from": (today - timedelta(days=2)).isoformat(), "to": today.isoformat()}
    body = (await owner.get(f"{BASE}/metrics/summary", params=params)).json()
    assert body["totals"]["runs"] == {"agent": 30, "team": 6, "workflow": 9, "total": 45}
    assert body["totals"]["sessions"] == 12
    assert body["totals"]["active_users"] == 2
    assert body["totals"]["tokens"]["input"] == 3_000_000
    assert [day["runs"]["total"] for day in body["days"]] == [15, 15, 15]
    triage = next(item for item in body["components"] if item["id"] == "support-triage")
    assert (triage["runs"], triage["sessions"], triage["approximate"]) == (4, 1, False)
    assert triage["models"][0]["model_id"] == "claude-opus-5-5"
    assert triage["estimated_cost"] == pytest.approx(5 + 2.5)
    # 1.5 M of the 3 M input tokens (and 150 k of 600 k output) come from sessions; the rest is the gap.
    assert body["gap_tokens"]["input"] == 1_500_000
    assert body["cost"]["approximate"] is True
    assert body["cost"]["total"] == pytest.approx(7.5 + 3.75 + (1_500_000 * 5 + 450_000 * 25) / 1e6)

    csv = await owner.get(f"{BASE}/metrics/export.csv", params=params)
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.splitlines()
    assert lines[0].startswith("component,type,primary_model")
    assert lines[1].startswith("support-triage,agent,claude-opus-5-5,0,4,1,1000000")

    marcus = await invite_operator(stack, owner, instance["id"])
    denied = await marcus.put(f"{BASE}/price-table", json={"prices": []})
    assert denied.status_code == 403
    assert (await marcus.get(f"{BASE}/price-table")).json()["prices"][0]["input_per_1m"] == 5

    org = await owner.put(
        "/api/v1/price-table",
        json={"prices": [{"model_id": "claude-haiku-5-5", "input_per_1m": 1, "output_per_1m": 5}]},
    )
    assert org.status_code == 200
    effective = (await owner.get(f"{BASE}/price-table")).json()["prices"]
    assert {(row["model_id"], row["source"]) for row in effective} == {
        ("claude-haiku-5-5", "org"),
        ("claude-opus-5-5", "instance"),
    }
    assert (await marcus.put("/api/v1/price-table", json={"prices": []})).status_code == 403


# ---------------------------------------------------------------- evaluations

CASES = [
    ("Charged twice for #4471, refund one", "billing / high; call refund_customer"),
    ("Refund for last year's annual plan?", "billing / normal; explain 30-day policy, no refund call"),
    ("App crashes when I export a report", "technical / high"),
    ("Invoice shows the wrong VAT number", "billing / normal; route to billing-agent"),
    ("Cancel my plan and refund this month", "billing / normal; prorated refund via refund_customer"),
]
SCORES = {"current": [10, 9, 10, 9, 6], 4: [10, 3, 4, 9, 10]}


def respond(body: dict[str, Any], path: str) -> dict[str, Any]:
    version = body.get("version") if path.startswith("/agnostic") else None
    position = next(i for i, (text, _) in enumerate(CASES) if text == body["input"])
    score = SCORES[version or "current"][position]
    return {
        "eval_data": {
            "avg_score": score,
            "results": [{"output": f"answer {position + 1}", "score": score, "reason": f"reason {position + 1}"}],
        }
    }


async def wait_for(client: httpx.AsyncClient, batch_id: str) -> dict[str, Any]:
    for _ in range(200):
        detail = (await client.get(f"{BASE}/eval-batches/{batch_id}")).json()
        if detail["batch"]["status"] in {"completed", "failed", "cancelled"}:
            return detail
        await asyncio.sleep(0.05)
    raise AssertionError(f"evaluation {batch_id} didn't finish")


async def create_dataset(owner: httpx.AsyncClient) -> dict[str, Any]:
    """The five billing cases; a case without its expected output is refused."""
    created = await owner.post(
        f"{BASE}/eval-datasets",
        json={
            "name": "billing-tickets-v2",
            "eval_type": "accuracy",
            "cases": [{"input": text, "expected_output": expected} for text, expected in CASES],
        },
    )
    assert created.status_code == 201, created.text
    dataset = created.json()
    assert (dataset["case_count"], [case["position"] for case in dataset["cases"]]) == (5, [1, 2, 3, 4, 5])
    bad = await owner.post(f"{BASE}/eval-datasets/{dataset['id']}/cases", json={"cases": [{"input": "no expectation"}]})
    assert bad.status_code == 422
    return dataset


async def test_dataset_batches_compare_and_gate(stack: Stack) -> None:
    owner = await stack.owner()
    owner_id = (await owner.get("/api/v1/me")).json()["id"]
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    fake.eval_responder = respond

    dataset = await create_dataset(owner)

    capabilities = (await owner.get(f"{BASE}/evals/capabilities")).json()
    assert capabilities["versions"] is False
    assert "isn't installed" in capabilities["reason"]

    started = await owner.post(
        f"{BASE}/eval-batches",
        json={"dataset_id": dataset["id"], "component_kind": "agent", "component_id": "support-triage"},
    )
    assert started.status_code == 202, started.text
    assert (started.json()["via_bridge"], started.json()["version_label"]) == (False, "current")
    current = await wait_for(owner, started.json()["id"])
    assert current["batch"]["status"] == "completed"
    assert current["batch"]["summary"]["avg"] == pytest.approx(8.8)
    assert current["batch"]["result"] == "8.80 avg"
    assert [item["score"] for item in current["items"]] == [10, 9, 10, 9, 6]
    assert {request["path"] for request in fake.eval_requests} == {"/eval-runs"}
    assert {request["claims"]["sub"] for request in fake.eval_requests} == {owner_id}
    assert fake.eval_requests[0]["body"]["agent_id"] == "support-triage"

    draft = {"dataset_id": dataset["id"], "component_kind": "agent", "component_id": "support-triage", "version": 4}
    refused = await owner.post(f"{BASE}/eval-batches", json=draft)
    assert refused.status_code == 409
    assert refused.json()["code"] == "bridge_required"

    fake.bridge = True
    fake.component_stages[("support-triage", 4)] = "draft"
    store = await stack.container.get(EphemeralStore)
    await store.delete(f"evals:bridge:{instance['id']}")
    started_v4 = await owner.post(
        f"{BASE}/eval-batches", json={**draft, "judge": {"model_id": "claude-opus-5-5", "provider": "anthropic"}}
    )
    assert started_v4.status_code == 202, started_v4.text
    assert started_v4.json()["version_label"] == "v4 draft"
    v4 = await wait_for(owner, started_v4.json()["id"])
    assert v4["batch"]["summary"]["avg"] == pytest.approx(7.2)
    assert v4["baseline"]["id"] == current["batch"]["id"]
    bridge_calls = [request for request in fake.eval_requests if request["path"] == "/agnostic/v1/evals/run"]
    assert len(bridge_calls) == 5
    assert {(call["body"]["version"], call["body"]["model_id"]) for call in bridge_calls} == {(4, "claude-opus-5-5")}

    comparison = (
        await owner.get(f"{BASE}/eval-batches/{v4['batch']['id']}/compare", params={"with": current["batch"]["id"]})
    ).json()
    assert comparison["before"]["id"] == current["batch"]["id"]
    assert comparison["counts"] == {"regressions": 2, "fixes": 1, "below_before": 1, "below_after": 2}
    assert [row["change"] for row in comparison["rows"]] == ["same", "regression", "regression", "same", "fix"]
    assert comparison["insight"] == (
        "v4 draft fixes case 5 but regresses cases 2 and 3 (9 → 3, 10 → 4) compared with current."
    )

    off = await check_gate(owner, dataset["id"])

    results = (await owner.get(f"{BASE}/eval-results", params={"component_id": "support-triage", "version": 4})).json()
    assert [batch["id"] for batch in results] == [v4["batch"]["id"]]

    await check_listing_and_access(stack, owner, fake, instance["id"], dataset["id"], draft, off)

    events = (await owner.get("/api/v1/audit/events", params={"action": "evals.batch.started"})).json()["data"]
    assert len(events) == 2


async def check_gate(owner: httpx.AsyncClient, dataset_id: str) -> dict[str, Any]:
    """Turn the publish gate on (the draft would be blocked), then off; returns the gate as switched off."""
    gate = await owner.put(
        f"{BASE}/eval-gates",
        json={
            "component_kind": "agent",
            "component_id": "support-triage",
            "dataset_id": dataset_id,
            "min_average": 8.5,
            "enabled": True,
        },
    )
    assert gate.status_code == 200, gate.text
    assert (gate.json()["state"], gate.json()["consequence"]) == (
        "would_block",
        "v4 draft (7.20) would be blocked from publishing.",
    )
    off = await owner.put(
        f"{BASE}/eval-gates",
        json={
            "component_kind": "agent",
            "component_id": "support-triage",
            "dataset_id": dataset_id,
            "min_average": 8.5,
            "enabled": False,
        },
    )
    assert off.json()["id"] == gate.json()["id"]
    assert off.json()["consequence"] == "Off: Publish ignores this eval."

    return off.json()


async def check_listing_and_access(
    stack: Stack,
    owner: httpx.AsyncClient,
    fake: Any,
    instance_id: str,
    dataset_id: str,
    draft: dict[str, Any],
    gate: dict[str, Any],
) -> None:
    """The evaluations table mixes in AgentOS runs made elsewhere; operators read but don't run or gate."""
    fake.eval_runs.append(
        {
            "id": "eval_cli",
            "eval_type": "reliability",
            "name": "billing tool calls",
            "agent_id": "billing-agent",
            "eval_data": {"eval_status": "FAILED", "missing_tool_calls": ["refund_customer"]},
            "created_at": NOW.isoformat(),
        }
    )
    listed = (await owner.get(f"{BASE}/evaluations")).json()
    sources = [(row["source"], row["id"]) for row in listed["data"]]
    assert ("agentos", "eval_cli") in sources
    assert sum(1 for source, _ in sources if source == "batch") == 2
    assert not any(row_id.startswith("eval_") and row_id != "eval_cli" for _, row_id in sources)
    standalone = next(row for row in listed["data"] if row["id"] == "eval_cli")
    assert (standalone["result"], standalone["bad"]) == ("Failed", True)

    imported = await owner.post(
        f"{BASE}/eval-datasets/{dataset_id}/import",
        json={"format": "jsonl", "content": '{"input": "Where is my invoice?", "expected_output": "billing / low"}'},
    )
    assert imported.json() == {"imported": 1}

    marcus = await invite_operator(stack, owner, instance_id)
    assert (await marcus.get(f"{BASE}/evaluations")).status_code == 200
    denied = await marcus.post(f"{BASE}/eval-batches", json=draft)
    assert denied.status_code == 403
    assert (await marcus.put(f"{BASE}/eval-gates", json=gate | {"enabled": True})).status_code == 403
