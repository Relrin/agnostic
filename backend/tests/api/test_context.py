"""Context flows against a fake AgentOS: memory duplicates, source runs and optimization, knowledge bases and filtered
content, learning counts and per-user deletion (one instance and every instance), and file provenance."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from tests.api.test_instances_gateway import connect, invite_operator
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack
from tests.unit.test_context_domain import MEMORIES, brief_trace

NOW = datetime.now(UTC).replace(microsecond=0)
BASE = "/api/v1/instances/prod-agentos"
STAGING = "http://staging.agentos.test:7777"


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


def seed_memories(fake: FakeAgentOS) -> None:
    fake.memories = [
        {
            "memory_id": f"mem_48213_{index}",
            "memory": text,
            "topics": ["billing"],
            "agent_id": "support-triage",
            "user_id": "cus_48213",
            "updated_at": (NOW - timedelta(minutes=index)).isoformat(),
        }
        for index, text in enumerate(MEMORIES)
    ]


async def audit_actions(owner: httpx.AsyncClient, action: str) -> list[dict[str, Any]]:
    return (await owner.get("/api/v1/audit/events", params={"action": action})).json()["data"]


async def test_memory_duplicates_source_and_optimization(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    seed_memories(fake)

    duplicates = (await owner.get(f"{BASE}/memories/duplicates", params={"user_id": "cus_48213"})).json()
    assert duplicates["scanned"] == 8
    assert duplicates["partial"] is False
    assert {(item["memory_id"], item["duplicate_of"]) for item in duplicates["duplicates"]} == {
        ("mem_48213_3", "mem_48213_2"),
        ("mem_48213_5", "mem_48213_4"),
    }

    fake.session_items = [
        {
            "session_id": "sess_9c41e2",
            "agent_id": "support-triage",
            "user_id": "cus_48213",
            "created_at": (NOW - timedelta(hours=1)).isoformat(),
            "updated_at": NOW.isoformat(),
        }
    ]
    fake.session_runs["sess_9c41e2"] = [
        {"run_id": "run_a", "created_at": int((NOW - timedelta(minutes=50)).timestamp()), "run_input": "Hello"},
        {
            "run_id": "run_b",
            "created_at": int((NOW - timedelta(minutes=10)).timestamp()),
            "run_input": "My card was charged twice for order #4471.",
            "status": "COMPLETED",
        },
    ]
    source = (await owner.get(f"{BASE}/memories/mem_48213_2/source")).json()
    assert (source["session_id"], source["run_id"]) == ("sess_9c41e2", "run_b")
    assert source["input"] == "My card was charged twice for order #4471."
    assert source["method"] == "session_match"

    fake.memories.append({"memory_id": "manual", "memory": "Added by hand", "user_id": "cus_48213"})
    manual = (await owner.get(f"{BASE}/memories/manual/source")).json()
    assert manual["session_id"] is None
    assert manual["reason"] == "This memory was added directly, not by an agent or team."

    fake.optimized = [{"memory_id": "mem_new", "memory": "Double-charged on order #4471.", "topics": ["billing"]}]
    preview = await owner.post(f"{BASE}/memories/optimize", json={"user_id": "cus_48213"})
    assert preview.status_code == 200, preview.text
    assert (preview.json()["memories_before"], preview.json()["memories_after"], preview.json()["applied"]) == (
        9,
        1,
        False,
    )
    assert len(fake.memories) == 9
    assert await audit_actions(owner, "context.memories.optimized") == []

    applied = (await owner.post(f"{BASE}/memories/optimize", json={"user_id": "cus_48213", "apply": True})).json()
    assert applied["applied"] is True
    assert [memory["memory_id"] for memory in fake.memories] == ["mem_new"]
    [event] = await audit_actions(owner, "context.memories.optimized")
    assert "9 → 1" in event["summary"]


async def test_knowledge_bases_and_filtered_content(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    fake.knowledge_instances = [{"id": "kb_help", "name": "help_center", "db_id": "pg", "table": "help_center"}]
    fake.agent_items = [
        {
            "id": "support-triage",
            "name": "Support triage",
            "knowledge": {"db_id": "pg", "knowledge_table": "help_center"},
        },
        {"id": "billing-agent", "name": "Billing", "knowledge": {"db_id": "pg", "knowledge_table": "billing"}},
        {"id": "plain", "name": "Plain"},
    ]
    fake.knowledge_content["kb_help"] = [
        {
            "id": f"c{index}",
            "name": name,
            "type": mime,
            "status": status,
            "metadata": metadata,
            "updated_at": (NOW - timedelta(days=index)).isoformat(),
        }
        for index, (name, mime, status, metadata) in enumerate(
            [
                ("android-release-notes.md", "text/markdown", "processing", {"product": "mobile"}),
                ("invoices-export-guide.docx", None, "failed", {"category": "billing"}),
                ("refund-policy-2026.pdf", "application/pdf", "completed", {"category": "billing"}),
                ("outage-runbook.md", "text/markdown", "completed", {"category": "incidents"}),
            ]
        )
    ]

    [base] = (await owner.get(f"{BASE}/knowledge/bases")).json()["bases"]
    assert (base["id"], base["entries"]) == ("kb_help", 4)
    assert [reader["id"] for reader in base["used_by"]] == ["support-triage"]
    assert base["vector_dbs"][0]["search_types"] == ["vector", "hybrid"]

    everything = (await owner.get(f"{BASE}/knowledge/content", params={"knowledge_id": "kb_help"})).json()
    assert everything["matching"] == 4
    assert (everything["counts"]["by_status"]["failed"], everything["counts"]["by_status"]["processing"]) == (1, 1)
    assert everything["data"][0]["kind"] == "Markdown"

    billing = (
        await owner.get(
            f"{BASE}/knowledge/content", params={"knowledge_id": "kb_help", "search": "billing", "type": "PDF"}
        )
    ).json()
    assert [row["name"] for row in billing["data"]] == ["refund-policy-2026.pdf"]
    assert billing["counts"]["total"] == 4


async def test_learning_counts_and_deletion(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    fake.learnings = [
        {"learning_id": "user_profile_cus_48213", "learning_type": "user_profile", "user_id": "cus_48213"},
        {"learning_id": "memories_cus_48213", "learning_type": "user_memory", "user_id": "cus_48213"},
        {"learning_id": "lrn_3c9a07", "learning_type": "decision_log", "user_id": "cus_48213"},
        {"learning_id": "lrn_7d11b4", "learning_type": "decision_log", "user_id": "maya"},
        {"learning_id": "lrn_e8b21f", "learning_type": "entity_memory", "user_id": None},
    ]

    counts = (await owner.get(f"{BASE}/learnings/counts")).json()
    assert counts["counts"] == {
        "user_profile": 1,
        "user_memory": 1,
        "session_context": 0,
        "entity_memory": 1,
        "decision_log": 2,
    }
    assert counts["id_schemes"]["user_profile"] == "Deterministic id: user_profile_{user_id}"

    wrong = await owner.post(f"{BASE}/learnings/delete-user", json={"user_id": "cus_48213", "confirm": "cus_4821"})
    assert wrong.status_code == 422
    assert len(fake.learnings) == 5

    one_type = await owner.post(
        f"{BASE}/learnings/delete-user",
        json={"user_id": "cus_48213", "learning_type": "decision_log", "confirm": "cus_48213"},
    )
    assert one_type.json()["deleted"] == 1
    assert {item["learning_id"] for item in fake.learnings} == {
        "user_profile_cus_48213",
        "memories_cus_48213",
        "lrn_7d11b4",
        "lrn_e8b21f",
    }
    [event] = await audit_actions(owner, "context.learnings.user_deleted")
    assert "1 learnings (decision_log) of cus_48213" in event["summary"]

    # Operators read learnings but can't delete them.
    marcus = await invite_operator(stack, owner, instance["id"])
    denied = await marcus.post(f"{BASE}/learnings/delete-user", json={"user_id": "maya", "confirm": "maya"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "scope_missing"


async def test_data_subject_request_covers_every_instance(stack: Stack) -> None:
    owner = await stack.owner()
    prod = stack.runtime("prod.agentos.test")
    staging = stack.runtime("staging.agentos.test", os_id="fake-staging")
    await connect(owner, prod)
    await connect(owner, staging, endpoint=STAGING, display_name="staging-agentos", env_tag="staging")
    for fake in (prod, staging):
        fake.learnings = [
            {"learning_id": "user_profile_cus_48213", "learning_type": "user_profile", "user_id": "cus_48213"},
            {"learning_id": "user_profile_maya", "learning_type": "user_profile", "user_id": "maya"},
        ]

    refused = await owner.post("/api/v1/context/data-subject-requests", json={"user_id": "cus_48213", "confirm": "x"})
    assert refused.status_code == 422

    result = (
        await owner.post("/api/v1/context/data-subject-requests", json={"user_id": "cus_48213", "confirm": "cus_48213"})
    ).json()
    assert {(item["instance"], item["status"], item["deleted"]) for item in result["outcomes"]} == {
        ("prod-agentos", "deleted", 1),
        ("staging-agentos", "deleted", 1),
    }
    assert [item["user_id"] for item in prod.learnings] == ["maya"]
    assert [item["user_id"] for item in staging.learnings] == ["maya"]
    [event] = await audit_actions(owner, "context.data_subject.requested")
    assert "2 instances done, 0 skipped, 0 failed" in event["summary"]


async def test_file_provenance_without_the_bridge(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    path = "reports/daily-brief/2026-10-30.md"
    written = brief_trace("t1", "OK", NOW - timedelta(days=1), "write_file", path)
    read = brief_trace("t2", "OK", NOW - timedelta(hours=2), "read_file", path)
    for body in (written, read):
        fake.trace_details[body["trace_id"]] = body
    fake.traces = [{"trace_id": body["trace_id"], "start_time": body["start_time"]} for body in (written, read)]

    scanned = (await owner.get(f"{BASE}/files/provenance", params={"path": path})).json()
    assert scanned["available"] is True
    assert (scanned["exact"], scanned["scanned_traces"]) == (False, 2)
    assert scanned["written"]["run_id"] == "run_t1"
    assert scanned["written"]["step"] == "Compile brief"
    assert scanned["read_by"] == [{"component_id": "daily-brief", "step": "Compile brief", "count": 1}]

    # Operators hold traces:read but not filesystem:read.
    marcus = await invite_operator(stack, owner, instance["id"])
    assert (await marcus.get(f"{BASE}/files/provenance", params={"path": path})).status_code == 403


async def test_file_provenance_from_the_bridge(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    path = "reports/daily-brief/2026-10-31.md"
    fake.bridge = True
    fake.bridge_files = True
    fake.file_events = [
        {
            "action": "write",
            "tool": "write_file",
            "path": path,
            "trace_id": "t9",
            "run_id": "run_7a0e44",
            "component_kind": "workflow",
            "component_id": "daily-brief",
            "step": "Compile brief",
            "status": "OK",
            "run_status": "ERROR",
            "at": NOW.isoformat(),
        }
    ]
    exact = (await owner.get(f"{BASE}/files/provenance", params={"path": path})).json()
    assert (exact["exact"], exact["scanned_traces"], exact["partial"]) == (True, 3, True)
    assert exact["written"]["run_id"] == "run_7a0e44"
    assert any(call["path"] == "/agnostic/v1/files/provenance" for call in fake.calls)
