"""Context domain rules: likely-duplicate memories, the source run of a memory, file-tool events and provenance,
knowledge content labels, filters and readers, learning deletion confirmation, and upload routes in the gateway."""

from datetime import UTC, datetime, timedelta
from typing import Any

from agnostic_context.domain.files import file_events, same_file, summarize
from agnostic_context.domain.knowledge import ContentFilter, KnowledgeReader, content_kind, count, used_by
from agnostic_context.domain.learnings import confirmed, deletion_scope
from agnostic_context.domain.memories import MemoryText, RunRef, find_duplicates, similarity, source_run, trigrams
from agnostic_gateway.domain.policies import DEFAULT_POLICIES, PolicyTable, is_upload

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

MEMORIES = [
    "Prefers email over phone for follow-ups.",
    "Has a Pro annual plan, renewed in March 2026.",
    "Was double-charged on order #4471; refund requested on 31 Oct.",
    "Was charged twice for order #4471.",
    "Uses the mobile app on Android.",
    "Uses the Android app.",
    "Lives in Europe/Lisbon; replies sent after 18:00 are read the next morning.",
    "Asked twice how to export invoices as CSV.",
]


def test_trigram_similarity_matches_pg_trgm_conventions() -> None:
    assert trigrams("Hi") == frozenset({"  h", " hi", "hi "})
    assert similarity(trigrams("Uses the Android app."), trigrams("uses the android app")) == 1.0
    assert similarity(trigrams(""), trigrams("")) == 0.0


def test_duplicates_flag_the_shorter_memory_of_each_pair() -> None:
    memories = [MemoryText(f"mem_{i}", text, NOW) for i, text in enumerate(MEMORIES)]
    found = find_duplicates(memories, 0.35)
    assert [(item.memory_id, item.duplicate_of) for item in found] == [("mem_5", "mem_4"), ("mem_3", "mem_2")]
    assert found[0].similarity > found[1].similarity >= 0.35


def test_equal_length_duplicates_flag_the_older_memory() -> None:
    older = MemoryText("a", "Uses the Android app.", NOW - timedelta(days=1))
    newer = MemoryText("b", "Uses the android app!", NOW)
    [item] = find_duplicates([older, newer], 0.35)
    assert (item.memory_id, item.duplicate_of) == ("a", "b")


def test_source_run_is_the_newest_run_before_the_memory() -> None:
    runs = [
        RunRef("s1", "r1", NOW - timedelta(hours=3), "first", "COMPLETED"),
        RunRef("s1", "r2", NOW - timedelta(minutes=5), "second", "COMPLETED"),
        RunRef("s2", "r3", NOW + timedelta(minutes=1), "while writing", "COMPLETED"),
        RunRef("s2", "r4", NOW + timedelta(hours=1), "later", "COMPLETED"),
    ]
    match = source_run(runs, NOW)
    assert match is not None
    assert match.run_id == "r3"
    assert source_run(runs[3:], NOW) is None


def brief_trace(trace_id: str, status: str, at: datetime, tool: str, path: str) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "status": status,
        "run_id": f"run_{trace_id}",
        "session_id": f"sess_{trace_id}",
        "workflow_id": "daily-brief",
        "start_time": at.isoformat(),
        "tree": [
            {
                "id": "root",
                "name": "daily-brief",
                "type": "WORKFLOW",
                "spans": [
                    {
                        "id": "step",
                        "name": "Compile brief",
                        "type": "WORKFLOW",
                        "step_type": "step",
                        "spans": [
                            {
                                "id": "tool",
                                "name": tool,
                                "type": "TOOL",
                                "status": "OK",
                                "start_time": (at + timedelta(minutes=4)).isoformat(),
                                "input": f'{{"path": "{path}", "content": "# brief"}}',
                            },
                            {"id": "other", "name": "web_search", "type": "TOOL", "input": '{"query": "x"}'},
                        ],
                    }
                ],
            }
        ],
    }


def test_file_events_and_provenance_summary() -> None:
    path = "reports/daily-brief/2026-10-30.md"
    write = file_events(brief_trace("t1", "OK", NOW - timedelta(days=2), "write_file", path), path)
    reads = [
        *file_events(brief_trace("t2", "OK", NOW - timedelta(days=1), "read_file", f"/workspace/{path}"), path),
        *file_events(brief_trace("t3", "OK", NOW, "read_file", path), path),
    ]
    old_read = file_events(brief_trace("t0", "OK", NOW - timedelta(days=3), "read_file", path), path)
    other = file_events(brief_trace("t4", "OK", NOW, "write_file", "reports/other.md"), path)
    assert other == []
    [event] = write
    assert (event.action, event.step, event.component_kind, event.component_id) == (
        "write",
        "Compile brief",
        "workflow",
        "daily-brief",
    )

    summary = summarize(path, [*write, *reads, *old_read], exact=False, scanned_traces=4)
    assert summary.written is not None
    assert summary.written.trace_id == "t1"
    assert summary.partial is False
    assert [(reader.component_id, reader.step, reader.count) for reader in summary.read_by] == [
        ("daily-brief", "Compile brief", 2)
    ]

    failed = file_events(brief_trace("t5", "ERROR", NOW, "write_file", path), path)
    assert summarize(path, [*write, *failed], exact=True, scanned_traces=2).partial is True


def test_same_file_ignores_mount_prefixes() -> None:
    assert same_file("/workspace/a/b.md", "a/b.md")
    assert same_file("./a/b.md", "a/b.md")
    assert not same_file("a/b.md", "a/c.md")


def test_content_kinds_filters_and_counts() -> None:
    assert content_kind("text/markdown", "x") == "Markdown"
    assert content_kind("application/pdf", None) == "PDF"
    assert content_kind(None, "guide.docx") == "DOCX"
    assert content_kind(None, "https://help.example.com") == "URL"
    assert content_kind("github", "docs/") == "GitHub"
    assert content_kind("application/octet-stream", "blob") == "Other"

    rows: list[dict[str, Any]] = [
        {
            "name": "refund-policy.pdf",
            "type": "application/pdf",
            "status": "completed",
            "metadata": {"category": "billing"},
        },
        {"name": "android.md", "type": "text/markdown", "status": "processing", "metadata": {"product": "mobile"}},
        {"name": "invoices.docx", "type": None, "status": "failed", "metadata": {"category": "billing"}},
    ]
    assert [row["name"] for row in rows if ContentFilter(search="category: billing").matches(row)] == [
        "refund-policy.pdf",
        "invoices.docx",
    ]
    assert [row["name"] for row in rows if ContentFilter(status="failed", kind="docx").matches(row)] == [
        "invoices.docx"
    ]
    assert not ContentFilter().active
    counts = count(rows)
    assert (counts.total, counts.by_status["failed"], counts.by_status["processing"]) == (3, 1, 1)
    assert counts.by_kind == {"DOCX": 1, "Markdown": 1, "PDF": 1}


def test_used_by_matches_table_and_database() -> None:
    readers = [
        KnowledgeReader("support-triage", "agent", "Support triage", "pg", "help_center"),
        KnowledgeReader("kb-researcher", "agent", "KB researcher", None, "help_center"),
        KnowledgeReader("billing-agent", "agent", "Billing", "other-db", "help_center"),
        KnowledgeReader("ops", "team", "Ops", "pg", "billing_policies"),
    ]
    assert [reader.id for reader in used_by("pg", "help_center", readers)] == ["support-triage", "kb-researcher"]


def test_learning_deletion_needs_the_exact_user_id() -> None:
    assert confirmed("cus_48213", " cus_48213 ")
    assert not confirmed("cus_48213", "cus_4821")
    assert not confirmed("", "")
    assert deletion_scope(None) == "all learning types"
    assert deletion_scope("user_profile") == "user_profile"


def test_knowledge_uploads_get_the_upload_limit() -> None:
    assert is_upload("post", "knowledge/content")
    assert is_upload("POST", "/knowledge/content/")
    assert not is_upload("GET", "knowledge/content")
    assert not is_upload("POST", "sessions")
    policy, _ = PolicyTable(DEFAULT_POLICIES).match("GET", "/agnostic/v1/files/provenance")
    assert policy.scopes == ("filesystem:read", "traces:read")
