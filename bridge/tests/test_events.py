"""GET /agnostic/v1/events: approvals and failed schedule runs from the OS db, paging by since, isolation, no db."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.os.authz import Authorization
from fastapi.testclient import TestClient

from agnostic_bridge import SCOPE_MAPPINGS, BridgeEvent, install
from agnostic_bridge._events import page_of
from tests.conftest import OS_ID, make_os

PATH = "/agnostic/v1/events"
T0 = 1_793_000_000
ALICE = "alice@example.com"
BOB = "bob@example.com"


def _approval(db: SqliteDb, approval_id: str, at: int, user_id: str) -> None:
    db.create_approval(
        {
            "id": approval_id,
            "run_id": f"run_{approval_id}",
            "session_id": f"sess_{approval_id}",
            "status": "pending",
            "source_type": "agent",
            "approval_type": "required",
            "pause_type": "confirmation",
            "tool_name": "send_email",
            "tool_args": {"to": "team@example.com"},
            "agent_id": "writer",
            "user_id": user_id,
            "created_at": at,
            "expires_at": at + 3600,
        }
    )


def _schedule(db: SqliteDb, schedule_id: str, user_id: str) -> None:
    db.create_schedule(
        {
            "id": schedule_id,
            "name": schedule_id,
            "method": "POST",
            "endpoint": "/workflows/noop/runs",
            "cron_expr": "0 3 * * *",
            "timezone": "UTC",
            "timeout_seconds": 600,
            "max_retries": 0,
            "retry_delay_seconds": 60,
            "enabled": True,
            "user_id": user_id,
            "created_at": T0 - 86_400,
        }
    )


def _run(db: SqliteDb, run_id: str, schedule_id: str, status: str, created: int, completed: int | None, user: str):
    db.create_schedule_run(
        {
            "id": run_id,
            "schedule_id": schedule_id,
            "attempt": 1,
            "triggered_at": created,
            "completed_at": completed,
            "status": status,
            "run_id": f"run_{run_id}",
            "session_id": f"sess_{run_id}",
            "error": "boom" if status == "failed" else None,
            "user_id": user,
            "created_at": created,
        }
    )


@pytest.fixture
def db(tmp_path: Path) -> SqliteDb:
    """Alice: approvals at T0+10 and T0+30, a run that failed at T0+20 (started before T0), a succeeded run.
    Bob: an approval at T0+40 and a failed run at T0+50."""
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    _approval(db, "ap1", T0 + 10, ALICE)
    _approval(db, "ap2", T0 + 30, ALICE)
    _approval(db, "ap3", T0 + 40, BOB)
    _schedule(db, "brief", ALICE)
    _schedule(db, "digest", BOB)
    _run(db, "sr1", "brief", "failed", T0 - 300, T0 + 20, ALICE)
    _run(db, "sr2", "brief", "success", T0 + 25, T0 + 26, ALICE)
    _run(db, "sr3", "digest", "failed", T0 + 45, T0 + 50, BOB)
    return db


def _secured_os(public_pem: str, **kwargs: Any) -> AgentOS:
    authorization = Authorization(
        verification_keys=[public_pem], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    return make_os(authorization=authorization, **kwargs)


def _ids(body: dict[str, Any]) -> list[str]:
    return [event["id"] for event in body["events"]]


def test_lists_events_oldest_first(db: SqliteDb) -> None:
    response = TestClient(install(make_os(db=db))).get(PATH, params={"since": T0})

    assert response.status_code == 200, response.text
    body = response.json()
    assert _ids(body) == [
        "approval.created:ap1",
        "schedule_run.failed:sr1",
        "approval.created:ap2",
        "approval.created:ap3",
        "schedule_run.failed:sr3",
    ]
    assert body["next_since"] == T0 + 50
    approval = body["events"][0]
    assert (approval["type"], approval["at"]) == ("approval.created", T0 + 10)
    assert {key: approval["data"][key] for key in ("id", "run_id", "status", "tool_name", "user_id", "expires_at")} == {
        "id": "ap1",
        "run_id": "run_ap1",
        "status": "pending",
        "tool_name": "send_email",
        "user_id": ALICE,
        "expires_at": T0 + 3610,
    }
    assert body["events"][1]["data"] == {
        "id": "sr1",
        "schedule_id": "brief",
        "run_id": "run_sr1",
        "session_id": "sess_sr1",
        "status": "failed",
        "error": "boom",
        "attempt": 1,
        "triggered_at": T0 - 300,
        "completed_at": T0 + 20,
    }


def test_since_and_limit_page_through(db: SqliteDb) -> None:
    client = TestClient(install(make_os(db=db)))

    first = client.get(PATH, params={"since": T0, "limit": 2}).json()
    second = client.get(PATH, params={"since": first["next_since"], "limit": 2}).json()
    third = client.get(PATH, params={"since": second["next_since"], "limit": 2}).json()
    last = client.get(PATH, params={"since": third["next_since"], "limit": 2}).json()

    assert (_ids(first), first["next_since"]) == (["approval.created:ap1", "schedule_run.failed:sr1"], T0 + 20)
    assert (_ids(second), second["next_since"]) == (["approval.created:ap2", "approval.created:ap3"], T0 + 40)
    assert (_ids(third), third["next_since"]) == (["schedule_run.failed:sr3"], T0 + 50)
    assert (_ids(last), last["next_since"]) == ([], T0 + 50)


def test_since_defaults_to_everything(db: SqliteDb) -> None:
    body = TestClient(install(make_os(db=db))).get(PATH).json()
    assert len(body["events"]) == 5


@pytest.mark.parametrize("limit", [0, 501])
def test_limit_is_bounded(db: SqliteDb, limit: int) -> None:
    assert TestClient(install(make_os(db=db))).get(PATH, params={"limit": limit}).status_code == 422


def test_a_page_never_ends_inside_a_second() -> None:
    def event(name: str, at: int) -> BridgeEvent:
        return BridgeEvent(id=f"approval.created:{name}", type="approval.created", at=at, data={})

    events = [event("a", 1), event("b", 2), event("c", 2), event("d", 3)]
    assert [e.id for e in page_of(events, 2)] == ["approval.created:a"]
    assert [e.id for e in page_of(events, 3)] == ["approval.created:a", "approval.created:b", "approval.created:c"]
    # one second alone overflows the page: take all of it rather than stall
    assert [e.at for e in page_of(events[1:], 1)] == [2, 2]


def test_isolated_callers_see_their_own_rows(db: SqliteDb, key_pair: tuple[str, str], mint: Callable[..., str]) -> None:
    client = TestClient(install(_secured_os(key_pair[1], db=db, user_isolation=True)))
    scopes = ["approvals:read", "schedules:read"]

    alice = client.get(PATH, params={"since": T0}, headers={"Authorization": f"Bearer {mint(scopes, sub=ALICE)}"})
    admin = client.get(
        PATH, params={"since": T0}, headers={"Authorization": f"Bearer {mint(['agent_os:admin'], sub=ALICE)}"}
    )

    assert alice.status_code == 200, alice.text
    assert _ids(alice.json()) == ["approval.created:ap1", "schedule_run.failed:sr1", "approval.created:ap2"]
    assert len(admin.json()["events"]) == 5


@pytest.mark.parametrize(
    ("scopes", "status"),
    [
        (["approvals:read", "schedules:read"], 200),
        (["agent_os:admin"], 200),
        (["approvals:read"], 403),
        (["schedules:read"], 403),
    ],
)
def test_needs_approvals_and_schedules_read(
    db: SqliteDb, key_pair: tuple[str, str], mint: Callable[..., str], scopes: list[str], status: int
) -> None:
    assert SCOPE_MAPPINGS[f"GET {PATH}"] == ["approvals:read", "schedules:read"]
    client = TestClient(install(_secured_os(key_pair[1], db=db)))
    response = client.get(PATH, headers={"Authorization": f"Bearer {mint(scopes)}"})
    assert response.status_code == status, response.text
    assert client.get(PATH).status_code == 401


def test_a_db_without_schedules_still_reports_approvals(db: SqliteDb, monkeypatch: pytest.MonkeyPatch) -> None:
    def unsupported(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    monkeypatch.setattr(db, "get_schedules", unsupported)

    body = TestClient(install(make_os(db=db))).get(PATH, params={"since": T0}).json()

    assert _ids(body) == ["approval.created:ap1", "approval.created:ap2", "approval.created:ap3"]


def test_without_a_db_there_is_nothing_to_read() -> None:
    response = TestClient(install(make_os())).get(PATH)
    assert response.status_code == 503
