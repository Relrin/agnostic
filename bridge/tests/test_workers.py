"""GET /agnostic/v1/workers: no queue, a running durable worker, a worker holding runs, and the admin gate."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from agno.db.sqlite import SqliteDb
from agno.job_queue.config import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os.authz import Authorization
from agno.os.job_queue import _SyncStoreAdapter
from agno.run import concurrency
from fastapi.testclient import TestClient

from agnostic_bridge import SCOPE_MAPPINGS, install
from tests.conftest import OS_ID, make_os

PATH = "/agnostic/v1/workers"


@pytest.fixture(autouse=True)
def _restore_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    """AgentOS(queue=...) sets agno's process-wide background cap; put it back after each test."""
    monkeypatch.setattr(concurrency, "_configured_limit", None)


def test_without_a_queue_reports_nothing_configured() -> None:
    response = TestClient(install(make_os(), replica_id="replica-a")).get(PATH)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["replica_id"] == "replica-a"
    assert (body["worker_id"], body["deployment_id"], body["max_concurrency"]) == (None, None, None)
    assert body["in_flight"] == []
    assert isinstance(body["heartbeat_at"], int) and body["heartbeat_at"] > 0
    queue = body["queue"]
    assert (queue["configured"], queue["durable"]) == (False, False)
    assert all(value is None for key, value in queue.items() if key not in ("configured", "durable"))
    assert body["scheduler"] == {"enabled": False, "poll_interval_seconds": None}


def test_running_durable_worker() -> None:
    config = QueueConfig(durable=True, db=InMemoryQueueStore(), max_concurrency=4, deployment_id="blue")
    app = install(make_os(queue=config), replica_id="replica-a")

    with TestClient(app) as client:  # the lifespan starts the worker
        worker = app.state.queue_worker
        body = client.get(PATH).json()

    assert body["worker_id"] == worker.worker_id
    assert body["deployment_id"] == "blue"
    assert body["max_concurrency"] == 4
    assert body["in_flight"] == []
    assert body["queue"] == {
        "configured": True,
        "durable": True,
        "db": "InMemoryQueueStore",
        "table": None,
        "max_queue_depth": 1000,
        "max_attempts": 1,
        "retry_delay_seconds": 30.0,
        "timeout_seconds": 3600.0,
        "lock_grace_seconds": 60.0,
        "stop_timeout_seconds": 30.0,
        "poll_interval": 1.0,
        "retention_seconds": 86400.0,
    }


def test_worker_holding_runs_on_a_sync_db(tmp_path: Path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    config = QueueConfig(durable=True, lock_grace_seconds=10, max_attempts=3, timeout_seconds=None)
    app = install(make_os(db=db, queue=config))
    # A started worker over a sync Postgres-style store, without starting one: SqliteDb has no queue contract.
    app.state.queue_worker = SimpleNamespace(
        worker_id="worker-1234",
        config=config,
        store=_SyncStoreAdapter(db),
        stop_timeout=9,
        _in_flight={"run-b": object(), "run-a": object()},
    )

    body = TestClient(app).get(PATH).json()

    assert body["worker_id"] == "worker-1234"
    assert body["in_flight"] == ["run-a", "run-b"]
    assert body["max_concurrency"] == concurrency.DEFAULT_BACKGROUND_MAX_CONCURRENCY
    queue = body["queue"]
    assert (queue["db"], queue["table"]) == ("SqliteDb", "agno_jobs")
    assert (queue["max_attempts"], queue["timeout_seconds"], queue["stop_timeout_seconds"]) == (3, None, 9.0)


def test_non_durable_queue_has_no_worker() -> None:
    body = TestClient(install(make_os(queue=QueueConfig(max_concurrency=0)))).get(PATH).json()

    assert body["worker_id"] is None
    assert body["max_concurrency"] is None  # 0 = uncapped
    assert (body["queue"]["configured"], body["queue"]["durable"], body["queue"]["db"]) == (True, False, None)
    assert body["queue"]["stop_timeout_seconds"] == 30.0


def test_scheduler_runs_with_a_db(tmp_path: Path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    with_db = TestClient(install(make_os(db=db, scheduler=True, scheduler_poll_interval=5))).get(PATH).json()
    without_db = TestClient(install(make_os(scheduler=True))).get(PATH).json()

    assert with_db["scheduler"] == {"enabled": True, "poll_interval_seconds": 5.0}
    assert without_db["scheduler"] == {"enabled": False, "poll_interval_seconds": None}


@pytest.mark.parametrize(
    ("scopes", "status"),
    [(["agent_os:admin"], 200), (["config:read"], 403), (["config:read", "schedules:read"], 403), ([], 403)],
)
def test_admin_only(key_pair: tuple[str, str], mint: Callable[..., str], scopes: list[str], status: int) -> None:
    assert SCOPE_MAPPINGS[f"GET {PATH}"] == ["agent_os:admin"]
    authorization = Authorization(
        verification_keys=[key_pair[1]], algorithm="RS256", verify_audience=True, audience=OS_ID
    )
    client = TestClient(install(make_os(authorization=authorization)))

    response = client.get(PATH, headers={"Authorization": f"Bearer {mint(scopes)}"})

    assert response.status_code == status, response.text
    assert client.get(PATH).status_code == 401
