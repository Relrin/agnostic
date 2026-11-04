"""The whole API on SQLite with the embedded job worker: no Docker, no Redis."""

from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from agnostic_kernel import migrations_runner
from agnostic_kernel.db import create_engine
from agnostic_kernel.errors import AppError, ConflictError
from agnostic_kernel.modules import load_modules
from agnostic_kernel.testing import make_settings, wait_for
from agnostic_server.app import create_app
from tests.support.probe import with_probe


async def migrate(database_url: str) -> None:
    engine = create_engine(make_settings(database_url).database)
    await migrations_runner.upgrade(engine, list(load_modules().installed.values()))
    await engine.dispose()


@pytest.fixture
async def client(sqlite_database: str) -> AsyncIterator[httpx.AsyncClient]:
    await migrate(sqlite_database)
    app = create_app(make_settings(sqlite_database), modules=with_probe())
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_job_runs_in_the_embedded_worker(client: httpx.AsyncClient) -> None:
    started = await client.post("/api/v1/probe/jobs", json={"value": "hi"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]

    async def fetch() -> httpx.Response:
        return await client.get(f"/api/v1/probe/jobs/{job_id}")

    done = await wait_for(fetch, lambda response: response.status_code == 200)
    assert done.json() == {"job_id": job_id, "progress": 1.0, "message": "echoed", "result": {"echo": "hi"}}


async def test_cursor_pagination(client: httpx.AsyncClient) -> None:
    first = (await client.get("/api/v1/probe/items", params={"limit": 2})).json()
    assert first["data"] == ["item-0", "item-1"]
    second = (await client.get("/api/v1/probe/items", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    third = (await client.get("/api/v1/probe/items", params={"limit": 2, "cursor": second["next_cursor"]})).json()
    assert third == {"data": ["item-4"], "next_cursor": None, "total_estimate": None}


async def test_problem_responses(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/probe/jobs/999999")
    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/problem+json"
    assert missing.json()["code"] == "not_found"
    assert missing.json()["request_id"] == missing.headers["x-request-id"]

    malformed = await client.get("/api/v1/probe/jobs/not-a-number")
    assert malformed.status_code == 422

    invalid = await client.post("/api/v1/probe/jobs", json={"value": ""})
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["loc"] == ["body", "value"]

    bad_cursor = await client.get("/api/v1/probe/items", params={"cursor": "!!"})
    assert bad_cursor.json()["code"] == "validation_failed"

    unknown = await client.get("/api/v1/nowhere")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "not_found"


async def test_request_id_is_accepted_or_generated(client: httpx.AsyncClient) -> None:
    echoed = await client.get("/healthz", headers={"X-Request-Id": "trace-123"})
    assert echoed.headers["x-request-id"] == "trace-123"
    generated = await client.get("/healthz", headers={"X-Request-Id": "bad id with spaces"})
    assert generated.headers["x-request-id"].startswith("req_")


async def test_readiness_reports_missing_cache(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200  # SQLite installs keep ephemeral state in process
    checks = {c["name"]: c["ok"] for c in response.json()["checks"]}
    assert checks == {"database": True, "cache": True, "migrations": True}


async def test_readiness_reports_missing_redis(sqlite_database: str) -> None:
    await migrate(sqlite_database)
    app = create_app(make_settings(sqlite_database, cache={"mode": "redis"}))
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get("/readyz")
    # A cache outage degrades the replica but keeps it in rotation (only the database and migrations gate it).
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    checks = {c["name"]: c["ok"] for c in response.json()["checks"]}
    assert checks == {"database": True, "cache": False, "migrations": True}


async def test_system_modules(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/system/modules")).json()
    modules = {module["name"]: module for module in body["enabled"]}
    assert modules["probe"]["jobs"] == ["probe.echo"]
    assert "audit.maintain_partitions" in modules["audit"]["jobs"]
    assert set(modules) >= {"audit", "settings", "identity", "org", "instances", "access", "gateway"}
    assert modules["gateway"]["depends_on"] == ["access", "instances", "settings", "audit"]


def test_openapi_has_stable_operation_ids(sqlite_database: str) -> None:
    schema = create_app(make_settings(sqlite_database)).openapi()
    operation_ids = {op["operationId"] for path in schema["paths"].values() for op in path.values()}
    assert {"auth_login", "me_get_me", "instances_list_instances", "system_list_modules"} <= operation_ids


async def test_disabling_a_module_removes_its_routes(sqlite_database: str) -> None:
    await migrate(sqlite_database)
    # approvals, assistant, context, observe, evals, queue, scheduler, studio and sources call AgentOS through the
    # gateway, so they go with it.
    disabled = [
        "approvals",
        "assistant",
        "context",
        "evals",
        "gateway",
        "observe",
        "queue",
        "scheduler",
        "sources",
        "studio",
    ]
    settings = make_settings(sqlite_database, modules={"disabled": disabled})
    app = create_app(settings)
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any(path.startswith("/api/v1/gateway") or path.endswith("/os/{path:path}") for path in paths)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            assert (await http.get("/api/v1/gateway/policies")).status_code == 404
            body = (await http.get("/api/v1/system/modules")).json()
            assert "gateway" not in {module["name"] for module in body["enabled"]}
            assert set(body["disabled"]) == set(disabled)


async def test_unhandled_and_app_errors(sqlite_database: str) -> None:
    app: FastAPI = create_app(make_settings(sqlite_database))

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaput")

    @app.get("/conflict")
    async def conflict() -> None:
        raise ConflictError("taken", extra={"field": "slug"})

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/boom")
        assert response.status_code == 500
        assert response.json()["code"] == AppError.code
        assert response.json()["request_id"] == response.headers["x-request-id"]
        clash = await http.get("/conflict")
        assert clash.status_code == 409
        assert clash.json()["field"] == "slug"
