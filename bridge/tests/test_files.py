"""GET /agnostic/v1/files/provenance: file-tool spans read from the OS db, scopes, and the no-db answer."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from agno.db.sqlite import SqliteDb
from agno.os.authz import Authorization
from agno.tracing.schemas import Span, Trace
from fastapi.testclient import TestClient

from agnostic_bridge import SCOPE_MAPPINGS, install
from agnostic_bridge._files import same_file, trace_events
from tests.conftest import OS_ID, make_os

PATH = "/agnostic/v1/files/provenance"
START = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)


def _trace(trace_id: str, status: str, at: datetime) -> Trace:
    return Trace(
        trace_id=trace_id,
        name="daily-brief.run",
        status=status,
        start_time=at,
        end_time=at + timedelta(minutes=6),
        duration_ms=360_000,
        total_spans=3,
        error_count=0 if status == "OK" else 1,
        run_id=f"run_{trace_id}",
        session_id=f"sess_{trace_id}",
        user_id="sa:scheduler",
        agent_id=None,
        team_id=None,
        workflow_id="daily-brief",
        created_at=at,
    )


def _span(trace_id: str, span_id: str, parent: str | None, name: str, kind: str, at: datetime, **attrs: object) -> Span:
    return Span(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=parent,
        name=name,
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=at,
        end_time=at + timedelta(seconds=1),
        duration_ms=1000,
        attributes={"openinference.span.kind": kind, **attrs},
        created_at=at,
    )


def _brief(db: SqliteDb, trace_id: str, status: str, at: datetime, *, tool: str, path: str) -> None:
    db.upsert_trace(_trace(trace_id, status, at))
    db.create_spans(
        [
            _span(trace_id, f"{trace_id}-root", None, "daily-brief", "CHAIN", at),
            _span(trace_id, f"{trace_id}-step", f"{trace_id}-root", "Compile brief", "CHAIN", at),
            _span(
                trace_id,
                f"{trace_id}-tool",
                f"{trace_id}-step",
                tool,
                "TOOL",
                at + timedelta(minutes=5),
                **{"tool.name": tool, "tool.parameters": json.dumps({"path": path, "content": "# Daily brief"})},
            ),
        ]
    )


@pytest.fixture
def db(tmp_path: Path) -> SqliteDb:
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    _brief(db, "t1", "OK", START, tool="write_file", path="reports/daily-brief/2026-10-30.md")
    _brief(
        db,
        "t2",
        "OK",
        START + timedelta(hours=2),
        tool="read_file",
        path="/workspace/reports/daily-brief/2026-10-30.md",
    )
    _brief(db, "t3", "ERROR", START + timedelta(days=1), tool="write_file", path="reports/daily-brief/2026-10-31.md")
    return db


def test_paths_match_under_a_mount_prefix() -> None:
    assert same_file("/workspace/reports/a.md", "reports/a.md")
    assert same_file("./reports/a.md", "reports/a.md")
    assert not same_file("reports/a.md", "reports/b.md")
    assert not same_file("", "reports/a.md")


def test_trace_events_name_the_step_and_tool() -> None:
    trace = {"trace_id": "t", "status": "ERROR", "workflow_id": "daily-brief", "run_id": "run_t"}
    spans = [
        {
            "span_id": "s",
            "parent_span_id": None,
            "name": "Compile brief",
            "attributes": {"openinference.span.kind": "CHAIN"},
        },
        {
            "span_id": "x",
            "parent_span_id": "s",
            "name": "write_file",
            "status_code": "STATUS_CODE_ERROR",
            "start_time": "2026-10-31T03:04:00Z",
            "attributes": {"tool.name": "write_file", "tool.parameters": '{"path": "a.md"}'},
        },
        {"span_id": "y", "parent_span_id": "s", "name": "web_search", "attributes": {"tool.name": "web_search"}},
    ]
    [event] = trace_events(trace, spans, "a.md")
    assert (event.action, event.step, event.status, event.run_status) == ("write", "Compile brief", "ERROR", "ERROR")
    assert (event.component_kind, event.component_id, event.run_id) == ("workflow", "daily-brief", "run_t")
    assert event.at == datetime(2026, 10, 31, 3, 4, tzinfo=timezone.utc)


def test_lists_writes_and_reads_of_the_file_newest_first(db: SqliteDb) -> None:
    client = TestClient(install(make_os(db=db)))

    response = client.get(PATH, params={"path": "reports/daily-brief/2026-10-30.md", "namespace": "workspace"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scanned_traces"] == 3
    assert body["path"] == "reports/daily-brief/2026-10-30.md"
    assert [(event["action"], event["trace_id"]) for event in body["events"]] == [("read", "t2"), ("write", "t1")]
    write = body["events"][1]
    assert (write["tool"], write["step"], write["component_id"], write["session_id"]) == (
        "write_file",
        "Compile brief",
        "daily-brief",
        "sess_t1",
    )


def test_needs_filesystem_and_traces_read(db: SqliteDb, key_pair: tuple[str, str], mint: Callable[..., str]) -> None:
    assert SCOPE_MAPPINGS[f"GET {PATH}"] == ["filesystem:read", "traces:read"]
    authorization = Authorization(
        verification_keys=[key_pair[1]], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    client = TestClient(install(make_os(db=db, authorization=authorization)))
    params = {"path": "reports/daily-brief/2026-10-30.md"}

    denied = client.get(PATH, params=params, headers={"Authorization": f"Bearer {mint(['filesystem:read'])}"})
    allowed = client.get(
        PATH, params=params, headers={"Authorization": f"Bearer {mint(['filesystem:read', 'traces:read'])}"}
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200, allowed.text


def test_without_a_db_there_is_nothing_to_read() -> None:
    response = TestClient(install(make_os())).get(PATH, params={"path": "a.md"})
    assert response.status_code == 503
