"""The whole API on SQLite with the embedded job worker: no Docker, no Redis."""

from collections.abc import AsyncIterator
from typing import Any

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


async def migrate(database_url: str) -> None:
    engine = create_engine(make_settings(database_url).database)
    await migrations_runner.upgrade(engine, list(load_modules().installed.values()))
    await engine.dispose()


@pytest.fixture
async def client(sqlite_database: str) -> AsyncIterator[httpx.AsyncClient]:
    await migrate(sqlite_database)
    app = create_app(make_settings(sqlite_database))
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_greeting_gets_a_reply_from_the_embedded_worker(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/v1/hello/greetings", json={"message": "  hello   world "})
    assert created.status_code == 201
    body = created.json()
    assert body["message"] == "hello world"
    assert body["status"] == "pending"

    async def fetch() -> dict[str, Any]:
        response = await client.get(f"/api/v1/hello/greetings/{body['id']}")
        return response.json()

    replied = await wait_for(fetch, lambda g: g["status"] == "replied")
    assert replied["reply"] == "Hello! You said: “hello world” (2 words)."


async def test_cursor_pagination(client: httpx.AsyncClient) -> None:
    for n in range(3):
        assert (await client.post("/api/v1/hello/greetings", json={"message": f"m{n}"})).status_code == 201
    first = (await client.get("/api/v1/hello/greetings", params={"limit": 2})).json()
    assert [g["message"] for g in first["data"]] == ["m2", "m1"]
    assert first["next_cursor"]
    second = (await client.get("/api/v1/hello/greetings", params={"limit": 2, "cursor": first["next_cursor"]})).json()
    assert [g["message"] for g in second["data"]] == ["m0"]
    assert second["next_cursor"] is None


async def test_problem_responses(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/hello/greetings/hel_01M6A0EEZEQ373S26F20142FZ5")
    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/problem+json"
    assert missing.json()["code"] == "not_found"
    assert missing.json()["request_id"] == missing.headers["x-request-id"]

    malformed = await client.get("/api/v1/hello/greetings/not-an-id")
    assert malformed.status_code == 404

    invalid = await client.post("/api/v1/hello/greetings", json={"message": ""})
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["loc"] == ["body", "message"]

    blank = await client.post("/api/v1/hello/greetings", json={"message": "   "})
    assert blank.status_code == 422
    assert blank.json()["detail"] == "A greeting needs some text."

    bad_cursor = await client.get("/api/v1/hello/greetings", params={"cursor": "!!"})
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
    assert response.status_code == 503
    checks = {c["name"]: c["ok"] for c in response.json()["checks"]}
    assert checks == {"database": True, "cache": False, "migrations": True}


async def test_system_modules(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/system/modules")).json()
    assert body["enabled"][0]["name"] == "hello"
    assert "hello.compose_reply" in body["enabled"][0]["jobs"]


def test_openapi_has_stable_operation_ids(sqlite_database: str) -> None:
    schema = create_app(make_settings(sqlite_database)).openapi()
    operation_ids = {op["operationId"] for path in schema["paths"].values() for op in path.values()}
    assert {"hello_list_greetings", "hello_create_greeting", "hello_get_greeting", "system_list_modules"} <= (
        operation_ids
    )


async def test_disabling_hello_removes_routes_and_jobs(sqlite_database: str) -> None:
    await migrate(sqlite_database)
    settings = make_settings(sqlite_database, modules={"disabled": ["hello"]})
    app = create_app(settings)
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not any(path.startswith("/api/v1/hello") for path in paths)
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            assert (await http.get("/api/v1/hello/greetings")).status_code == 404
            assert (await http.get("/api/v1/system/modules")).json() == {"enabled": [], "disabled": ["hello"]}


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
