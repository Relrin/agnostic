"""Ask your OS and the explainers against a fake AgentOS, with a scripted model answering on the embedded worker.

Covers the org's AI settings (the key is write-only), "Why did daily-brief fail last night?" answered from the
schedule and the trace with links to both, a person without ``traces:read`` told what they can't see, every tool
only reading, explanations reused until regenerated, limits and budgets, attachments, conversations, retention and
a disabled module.
"""

import json
import re
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from agnostic_assistant.application.ports import AssistantStore
from agnostic_assistant.application.tools import Ledger, ToolBox, ToolCatalog, ToolLimits
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.tools import Redaction
from tests.api.test_instances_gateway import connect
from tests.api.test_observe_evals import daily_brief_pair, summary
from tests.api.test_sources import eventually
from tests.support.scripted_model import Call, Script, Seen
from tests.support.stack import Stack, running_stack

NOW = datetime.now(UTC)
BASE = "/api/v1/instances/prod-agentos/assistant"
QUESTION = "Why did daily-brief fail last night?"
DATA = re.compile(r'<data source="tool:(?P<tool>[^"]+)">\n(?P<body>.*?)\n</data>', re.DOTALL)


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    monkeypatch.setenv("AGNOSTIC_ASSISTANT__PRUNE_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


def data(seen: Seen, tool: str) -> Any:
    """The JSON a tool returned, out of its quoted block (a tool message, or gathered into the question)."""
    blocks = [m for text in (seen.results.get(tool, ""), seen.question) for m in DATA.finditer(text)]
    match = next((m for m in blocks if m.group("tool") == tool), None)
    return json.loads(match.group("body")) if match else None


async def enable(owner: httpx.AsyncClient, **changes: Any) -> dict[str, Any]:
    body = {"enabled": True, "models": {"assistant": "ollama:qwen3:8b"}, **changes}
    response = await owner.put("/api/v1/assistant/settings", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def seed_daily_brief(fake: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    today, yesterday = daily_brief_pair(fake)
    fake.traces = [summary(today) | {"run_id": "run_b"}, summary(yesterday) | {"run_id": "run_y"}]
    fake.schedules = [{"id": "sch_1", "name": "daily-brief", "enabled": True, "cron_expr": "0 3 * * *"}]
    fake.schedule_runs["sch_1"] = [
        {
            "id": "r2",
            "status": "failed",
            "attempt": 2,
            "error": "Timeout in web_search after 30 s",
            "triggered_at": int((NOW - timedelta(hours=1)).timestamp()),
            "run_id": "run_b",
        },
        {
            "id": "r1",
            "status": "failed",
            "error": "Timeout",
            "triggered_at": int((NOW - timedelta(hours=1, minutes=5)).timestamp()),
            "run_id": "run_b",
        },
    ]
    return today, yesterday


def investigate() -> Script:
    """Looks at the schedule's runs, finds the failed run's trace, reads it, and names the failing span."""

    def trace_id(seen: Seen) -> Mapping[str, Any]:
        found = data(seen, "search_traces") or {"traces": [{}]}
        return {"trace_id": found["traces"][0].get("trace_id", "missing")}

    def answer(seen: Seen) -> str:
        if "cannot see" in seen.system and "traces" in seen.system and "get_trace" not in seen.results:
            runs = data(seen, "get_schedule_runs") or {"runs": []}
            error = runs["runs"][0]["error"] if runs["runs"] else "an error"
            return f"daily-brief failed with: {error}. I can't see traces with your access (needs traces:read)."
        trace = data(seen, "get_trace") or {"spans": []}
        failing = next((span for span in trace["spans"] if span.get("error")), None)
        if failing is None:
            return "I couldn't find the failing step."
        return f"daily-brief failed because `web_search` timed out: {failing['error']}"

    return Script(
        calls=(
            Call("get_schedule_runs", {"schedule": "daily-brief"}),
            Call("search_traces", {"component_id": "daily-brief", "component_kind": "workflow", "status": "ERROR"}),
            Call("get_trace", trace_id),
        ),
        answer=answer,
    )


async def settled(client: httpx.AsyncClient, message_id: str) -> dict[str, Any]:
    async def probe() -> dict[str, Any] | None:
        body = (await client.get(f"{BASE}/messages/{message_id}")).json()
        return body if body["status"] in {"completed", "failed", "cancelled"} else None

    return await eventually(probe, f"answer {message_id}")


def sse(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


async def ask(client: httpx.AsyncClient, question: str = QUESTION, **form: Any) -> httpx.Response:
    files = form.pop("files", None)
    return await client.post(f"{BASE}/questions", data={"question": question, **form}, files=files)


async def test_settings_are_admin_only_and_the_key_is_write_only(stack: Stack) -> None:
    owner = await stack.owner()
    await connect(owner, stack.runtime("prod.agentos.test"))

    status = (await owner.get("/api/v1/assistant/status")).json()
    assert status["features"] == {"assistant": False, "summaries": False, "suggestions": False}
    assert (await owner.get("/api/v1/system/features")).json()["features"]["assistant"] is False

    no_model = await owner.put("/api/v1/assistant/settings", json={"enabled": True})
    assert no_model.status_code == 422
    bad = await owner.put("/api/v1/assistant/settings", json={"models": {"assistant": "skynet:t-800"}})
    assert bad.status_code == 422
    assert "Unknown provider" in bad.json()["detail"]

    saved = await enable(owner, endpoint="http://ollama.internal:11434", api_key="sk-secret-1", data_notice="Local")
    assert saved["has_api_key"] is True
    assert "sk-secret-1" not in json.dumps(saved)
    assert saved["models"]["summaries"] is None
    stale = await owner.put("/api/v1/assistant/settings", json={"retention_days": 30, "version": 0})
    assert stale.status_code == 409

    status = (await owner.get("/api/v1/assistant/status")).json()
    assert status["features"] == {"assistant": True, "summaries": True, "suggestions": True}
    assert (status["can_use"], status["provider"], status["data_notice"]) == (True, "ollama", "Local")
    features = (await owner.get("/api/v1/system/features")).json()["features"]
    assert features == {"assistant": True, "assistant.summaries": True, "assistant.suggestions": True}

    check = (await owner.post("/api/v1/assistant/settings/check", json={})).json()
    assert check["ok"] is True, check
    model, connection = stack.models.built[-1]
    assert (model, connection.endpoint, connection.api_key) == (
        "ollama:qwen3:8b",
        "http://ollama.internal:11434",
        "sk-secret-1",
    )

    events = (await owner.get("/api/v1/audit/events", params={"action": "assistant.settings.update"})).json()["data"]
    assert events
    assert "sk-secret-1" not in json.dumps(events)
    assert any("API key: replaced" in line["text"] for line in events[-1]["diff"]["lines"])

    off = await owner.put("/api/v1/assistant/settings", json={"features": {"summaries": False}})
    assert off.json()["features"] == {"assistant": True, "summaries": False, "suggestions": True}


async def test_why_did_daily_brief_fail_last_night(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    today, _ = seed_daily_brief(fake)
    await enable(owner)
    stack.models.script = investigate()

    accepted = await ask(owner, context="page:home")
    assert accepted.status_code == 202, accepted.text
    message_id = accepted.json()["message_id"]
    answer = await settled(owner, message_id)

    assert answer["status"] == "completed", answer
    assert answer["generated"] is True
    assert "`web_search` timed out" in answer["content"]
    assert "TimeoutError: web_search exceeded the 30 s tool timeout" in answer["content"]
    assert [call["name"] for call in answer["tool_calls"]] == ["get_schedule_runs", "search_traces", "get_trace"]
    assert {call["status"] for call in answer["tool_calls"]} == {"done"}
    paths = {source["path"] for source in answer["sources"]}
    assert f"/i/prod-agentos/traces/{today['trace_id']}" in paths
    assert "/i/prod-agentos/scheduler?schedule=sch_1" in paths
    assert answer["input_tokens"] > 0

    seen = stack.models.script.seen[-1]
    assert "untrusted data" in seen.system
    assert "cannot see" not in seen.system
    assert '<data source="page">' in seen.question

    # The stream of a settled answer replays it: chips, sources, then the completed event.
    stream = await owner.get(f"{BASE}/messages/{message_id}/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    events = sse(stream.text)
    assert events[0]["event"] == "answer.started"
    assert [e["name"] for e in events if e["event"] == "answer.tool_started"] == [
        "get_schedule_runs",
        "search_traces",
        "get_trace",
    ]
    assert events[-1]["event"] == "answer.completed"
    assert next(e for e in events if e["event"] == "answer.sources")["sources"]

    # Audited with the tools and sources, not the question.
    audited = (await owner.get("/api/v1/audit/events", params={"action": "assistant.ask"})).json()["data"]
    assert len(audited) == 1
    assert "get_trace" in audited[0]["summary"]
    assert QUESTION not in json.dumps(audited)
    assert any(today["trace_id"] in line["text"] for line in audited[0]["diff"]["lines"])

    conversation = (await owner.get(f"{BASE}/conversations")).json()
    assert [item["title"] for item in conversation] == [QUESTION]


async def test_without_traces_read_the_answer_says_what_it_cannot_see(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    seed_daily_brief(fake)
    await enable(owner)
    stack.models.script = investigate()

    role = await owner.post(
        "/api/v1/access/roles", json={"name": "Schedule watcher", "permissions": {"schedules": ["read"]}}
    )
    assert role.status_code == 201, role.text
    invited = await owner.post(
        "/api/v1/invitations",
        json={
            "email": "vera@localhost.company",
            "bindings": [{"role_id": role.json()["id"], "instance_id": instance["id"]}],
        },
    )
    token = invited.json()["accept_url"].rsplit("/", 1)[1]
    vera = stack.client()
    joined = await vera.post(
        f"/api/v1/invitations/{token}/accept", json={"display_name": "Vera Lind", "password": "vera's long password"}
    )
    vera.headers["X-CSRF-Token"] = joined.json()["csrf_token"]
    assert (await vera.get("/api/v1/assistant/status")).json()["can_use"] is True

    accepted = await ask(vera)
    assert accepted.status_code == 202, accepted.text
    answer = await settled(vera, accepted.json()["message_id"])

    assert answer["status"] == "completed", answer
    assert [call["name"] for call in answer["tool_calls"]] == ["get_schedule_runs"]
    assert "can't see traces" in answer["content"]
    assert "Timeout in web_search after 30 s" in answer["content"]
    assert all("/traces/" not in source["path"] for source in answer["sources"])
    seen = stack.models.script.seen[-1]
    assert "traces (needs traces:read)" in seen.system

    # Someone else's answer doesn't exist for the owner.
    assert (await owner.get(f"{BASE}/messages/{answer['id']}")).status_code == 404


async def test_every_tool_only_reads(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    today, _ = seed_daily_brief(fake)
    me = (await owner.get("/api/v1/me")).json()
    arguments: dict[str, dict[str, Any]] = {
        "get_trace": {"trace_id": today["trace_id"]},
        "compare_trace": {"trace_id": today["trace_id"]},
        "get_session": {"session_id": "ses_1"},
        "get_schedule_runs": {"schedule": "daily-brief"},
        "explain_permission": {"resource": "traces", "verb": "read"},
        "get_component_config": {"component_id": "support-triage"},
        "diff_versions": {"component_id": "support-triage", "from_version": 1, "to_version": 2},
    }
    stack.routes.requests.clear()
    async with stack.container() as request:
        catalog = await request.get(ToolCatalog)
        toolbox = await request.get(ToolBox)
        instance = await (await request.get(InstancesFacade)).get("prod-agentos")
        assert instance is not None
        principal = Principal(kind="user", id=me["id"], display_name=me["display_name"], via="job")
        names = {spec.name for spec in catalog.specs()}
        assert names >= {
            "search_traces", "get_trace", "compare_trace", "list_sessions", "get_session", "get_metrics",
            "list_approvals", "list_schedules", "get_schedule_runs", "search_audit", "explain_permission",
            "get_component_config", "diff_versions", "list_eval_results",
        }  # fmt: skip
        ledger = Ledger()
        for spec in catalog.specs():
            result = await toolbox.call(
                request,
                principal,
                instance,
                spec,
                arguments.get(spec.name, {}),
                redaction=Redaction(tool_args=True, user_messages=True),
                limits=ToolLimits(30, 12_000),
                ledger=ledger,
            )
            assert result.startswith(f'<data source="tool:{spec.name}">')
            if spec.name == "get_trace":
                assert '"tool_args":"[redacted]"' in result
                assert '"user_message":"[redacted]"' in result
    assert stack.routes.requests, "the tools read nothing"
    assert {method for method, _, _ in stack.routes.requests} == {"GET"}


async def test_explanations_are_reused_until_regenerated(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    today, _ = seed_daily_brief(fake)
    await enable(owner, features={"summaries": False})

    body = {"kind": "trace.diagnosis", "subject": {"trace_id": today["trace_id"]}}
    off = await owner.post(f"{BASE}/explanations", json=body)
    assert off.status_code == 409
    assert off.json()["code"] == "ai_feature_off"
    await enable(owner, features={"summaries": True})

    stack.models.script = Script(answer=lambda seen: f"Polished: {data(seen, 'compare_trace')['diagnosis']}")
    first = await owner.post(f"{BASE}/explanations", json=body)
    assert first.status_code == 202, first.text
    explained = await settled(owner, first.json()["message_id"])
    assert explained["status"] == "completed", explained
    assert explained["content"].startswith("Polished: ")
    assert explained["content"].endswith("so the workflow never reached `Write brief`.")
    assert [call["name"] for call in explained["tool_calls"]] == ["compare_trace"]
    assert explained["conversation_id"] is None
    assert "Rewrite the comparison's diagnosis" in stack.models.script.seen[-1].system

    again = (await owner.post(f"{BASE}/explanations", json=body)).json()
    assert (again["message_id"], again["reused"]) == (first.json()["message_id"], True)
    fresh = (await owner.post(f"{BASE}/explanations", json=body | {"regenerate": True})).json()
    assert fresh["reused"] is False
    assert fresh["message_id"] != first.json()["message_id"]

    unknown = await owner.post(f"{BASE}/explanations", json={"kind": "horoscope", "subject": {}})
    assert unknown.status_code == 422
    material = await owner.post(f"{BASE}/explanations", json=body | {"material": {"x": 1}})
    assert material.status_code == 422

    # Structured kinds come back as clean JSON, whatever the model wraps them in.
    stack.models.script = Script(
        answer=lambda seen: (
            'Sure!\n```json\n{"person": "usr_1", "resource": "agents", "verb": "publish", '
            '"component": "support-triage", "instance": "prod-agentos"}\n```'
        )
    )
    parsed = await owner.post(
        f"{BASE}/explanations",
        json={
            "kind": "access.question",
            "subject": {"question": "Can Maya publish support-triage on prod?"},
            "material": {"people": [{"id": "usr_1", "name": "Maya"}], "instances": ["prod-agentos"]},
        },
    )
    structured = await settled(owner, parsed.json()["message_id"])
    assert json.loads(structured["content"]) == {
        "person": "usr_1",
        "resource": "agents",
        "verb": "publish",
        "component": "support-triage",
        "instance": "prod-agentos",
    }


async def test_rate_limit_and_monthly_budget(stack: Stack) -> None:
    owner = await stack.owner()
    await connect(owner, stack.runtime("prod.agentos.test"))
    await enable(owner, requests_per_minute=1)

    assert (await ask(owner, "First?")).status_code == 202
    limited = await ask(owner, "Second?")
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"

    await enable(owner, requests_per_minute=100, monthly_token_budget=5)
    first = await ask(owner, "Third?")
    if first.status_code == 202:
        await settled(owner, first.json()["message_id"])
    over = await ask(owner, "Fourth?")
    assert over.status_code == 429
    assert over.json()["code"] == "ai_budget_exhausted"
    status = (await owner.get("/api/v1/assistant/status")).json()
    assert status["budget"]["org_tokens"] >= 5
    assert status["budget"]["org_limit"] == 5


async def test_attachments_conversations_and_retention(stack: Stack) -> None:
    owner = await stack.owner()
    await connect(owner, stack.runtime("prod.agentos.test"))
    await enable(owner)
    stack.models.script = Script(answer=lambda seen: f"Seen {seen.images} image(s).")

    log = b"03:00:31 ERROR web_search: TimeoutError after 30 s\n"
    files = [("files", ("run.log", log, "text/plain")), ("files", ("screen.png", b"\x89PNG fake", "image/png"))]
    first = await ask(owner, "What does this log say?", files=files)
    assert first.status_code == 202, first.text
    answered = await settled(owner, first.json()["message_id"])
    assert answered["content"] == "Seen 1 image(s)."
    seen = stack.models.script.seen[-1]
    assert '<data source="attachment:run.log">' in seen.question
    assert "TimeoutError after 30 s" in seen.question

    binary = await ask(owner, "And this?", files=[("files", ("dump.bin", b"\x00\x01", "application/octet-stream"))])
    assert binary.status_code == 422

    conversation_id = first.json()["conversation_id"]
    follow = await ask(owner, "And yesterday?", conversation_id=conversation_id)
    assert follow.json()["conversation_id"] == conversation_id
    await settled(owner, follow.json()["message_id"])
    thread = (await owner.get(f"{BASE}/conversations/{conversation_id}")).json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant", "user", "assistant"]
    assert [a["name"] for a in thread["messages"][0]["attachments"]] == ["run.log", "screen.png"]

    async with stack.container() as request:
        store = await request.get(AssistantStore)
        assert await store.prune(utcnow() - timedelta(days=1)) == 0
        assert await store.prune(utcnow() + timedelta(days=1)) == 1
        await store.commit()
    assert (await owner.get(f"{BASE}/conversations/{conversation_id}")).status_code == 404

    other = await ask(owner, "Something else")
    other_id = other.json()["conversation_id"]
    await settled(owner, other.json()["message_id"])
    assert (await owner.delete(f"{BASE}/conversations/{other_id}")).status_code == 204
    assert (await owner.get(f"{BASE}/conversations")).json() == []
    deleted = (await owner.get("/api/v1/audit/events", params={"action": "assistant.conversation.delete"})).json()
    assert len(deleted["data"]) == 1


async def test_a_failing_model_fails_the_answer_with_a_sentence(stack: Stack) -> None:
    owner = await stack.owner()
    await connect(owner, stack.runtime("prod.agentos.test"))
    await enable(owner)

    def broken(seen: Seen) -> str:
        raise ConnectionError("connection refused by http://ollama.internal:11434")

    stack.models.script = Script(answer=broken)
    accepted = await ask(owner, "Hello?")
    failed = await settled(owner, accepted.json()["message_id"])
    assert failed["status"] == "failed"
    assert "connection refused" in (failed["error"] or "")
    events = sse((await owner.get(f"{BASE}/messages/{failed['id']}/events")).text)
    assert events[-1]["event"] == "answer.failed"


async def test_disabled_module_leaves_nothing_behind(sqlite_database: str) -> None:
    async with running_stack(sqlite_database, modules={"disabled": ["assistant"]}) as stack:
        owner = await stack.owner()
        assert (await owner.get("/api/v1/assistant/status")).status_code == 404
        assert (await owner.post(f"{BASE}/questions", data={"question": "Hi"})).status_code == 404
        assert "assistant" not in (await owner.get("/api/v1/system/features")).json()["features"]
        scopes = (await owner.get("/api/v1/me/access")).json()["control_plane_scopes"]
        assert "assistant:use" not in scopes
