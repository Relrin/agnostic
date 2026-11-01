"""Connecting instances and calling them through the gateway, against a fake AgentOS that verifies our JWTs."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import jwt
import pytest

from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

PROD = "http://prod.agentos.test:7777"


@pytest.fixture
async def stack(sqlite_database: str) -> AsyncIterator[Stack]:
    async with running_stack(sqlite_database) as running:
        yield running


async def connect(owner: httpx.AsyncClient, fake: FakeAgentOS, endpoint: str = PROD, **body: Any) -> dict[str, Any]:
    created = await owner.post(
        "/api/v1/instances",
        json={"endpoint_url": endpoint, "display_name": "prod-agentos", "env_tag": "production", **body},
    )
    assert created.status_code == 201, created.text
    instance: dict[str, Any] = created.json()["instance"]
    keys = (await owner.get(f"/api/v1/instances/{instance['id']}/keys/public")).json()
    fake.public_keys = [key["public_pem"] for key in keys["keys"] if key["status"] == "active"]
    return instance


async def invite_operator(stack: Stack, owner: httpx.AsyncClient, instance_id: str) -> httpx.AsyncClient:
    roles = {role["slug"]: role["id"] for role in (await owner.get("/api/v1/access/roles")).json()}
    invited = await owner.post(
        "/api/v1/invitations",
        json={
            "email": "marcus@localhost.company",
            "bindings": [{"role_id": roles["operator"], "instance_id": instance_id}],
        },
    )
    token = invited.json()["accept_url"].rsplit("/", 1)[1]
    marcus = stack.client()
    joined = await marcus.post(
        f"/api/v1/invitations/{token}/accept",
        json={"display_name": "Marcus Chen", "password": "marcus's long password"},
    )
    marcus.headers["X-CSRF-Token"] = joined.json()["csrf_token"]
    return marcus


async def test_connect_wizard_and_test_connection(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")

    probe = (await owner.post("/api/v1/instances/probe", json={"endpoint_url": PROD + "/"})).json()
    assert probe["ok"] is True
    assert [step["id"] for step in probe["steps"]] == ["dns", "connect", "info"]
    assert probe["discovery"]["os_id"] == "fake-prod"

    created = await owner.post(
        "/api/v1/instances", json={"endpoint_url": PROD, "display_name": "prod-agentos", "env_tag": "production"}
    )
    instance = created.json()["instance"]
    assert (instance["slug"], instance["status"], instance["auth_mode"]) == ("prod-agentos", "pending", "jwt")

    keys = (await owner.get(f"/api/v1/instances/{instance['id']}/keys/public")).json()
    assert keys["audience"] == "fake-prod"
    assert keys["issuer"] == "http://agnostic.test"
    assert "JWT_VERIFICATION_KEY=" in keys["env_snippet"]
    assert 'audience="fake-prod"' in keys["python_snippet"]

    # Before the runtime trusts our key: a key-mismatch diagnosis.
    failed = (await owner.post(f"/api/v1/instances/{instance['id']}/test")).json()
    assert failed["ok"] is False
    auth_step = next(step for step in failed["steps"] if step["id"] == "auth")
    assert auth_step["status"] == "failed"
    assert "JWT_VERIFICATION_KEY" in auth_step["hint"]

    fake.public_keys = [keys["keys"][0]["public_pem"]]
    report = (await owner.post("/api/v1/instances/prod-agentos/test")).json()
    assert report["ok"] is True, report["steps"]
    assert report["instance"]["status"] == "connected"
    statuses = {step["id"]: step["status"] for step in report["steps"]}
    assert statuses == {"dns": "ok", "connect": "ok", "info": "ok", "auth": "ok", "rbac": "ok"}
    capabilities = {item["name"]: item["status"] for item in report["capabilities"]}
    assert capabilities["jwt_rbac"] == "available"
    assert capabilities["approvals"] == "disabled"
    assert capabilities["components"] == "available"
    assert capabilities["durable_queue"] == "unsupported"

    fake.name = "Fake prod (renamed)"  # a changed /config: a new snapshot next to the loaded one
    again = await owner.post(f"/api/v1/instances/{instance['id']}/test")
    assert again.status_code == 200
    assert again.json()["ok"] is True

    config = (await owner.get(f"/api/v1/instances/{instance['id']}/config")).json()
    assert config["databases"] == ["prod-db"]
    assert config["sections"]["queue"] == {"durable": True, "queue_per_session": False}

    # The token the runtime saw: issuer, audience, the system subject.
    claims = fake.calls[-1]["claims"]
    assert claims["iss"] == "http://agnostic.test"
    assert claims["aud"] == "fake-prod"


async def test_diagnostics_for_each_failure(stack: Stack) -> None:
    owner = await stack.owner()
    dns = (await owner.post("/api/v1/instances/probe", json={"endpoint_url": "http://nowhere.invalid:7777"})).json()
    assert [(s["id"], s["status"]) for s in dns["steps"]] == [("dns", "failed")]

    refused = (await owner.post("/api/v1/instances/probe", json={"endpoint_url": "http://down.agentos.test"})).json()
    assert refused["steps"][-1]["id"] == "connect"
    assert refused["steps"][-1]["status"] == "failed"

    _ = stack.runtime("old.agentos.test", agno_version="3.0.4")
    old = (await owner.post("/api/v1/instances/probe", json={"endpoint_url": "http://old.agentos.test"})).json()
    assert old["steps"][-1]["id"] == "version"
    assert "too old" in old["steps"][-1]["detail"]
    rejected = await owner.post("/api/v1/instances", json={"endpoint_url": "http://old.agentos.test"})
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "discovery_failed"

    fake = stack.runtime("aud.agentos.test", os_id="aud-os")
    instance = await connect(owner, fake, "http://aud.agentos.test")
    fake.audience = "something-else"
    report = (await owner.post(f"/api/v1/instances/{instance['id']}/test")).json()
    auth = next(step for step in report["steps"] if step["id"] == "auth")
    assert auth["status"] == "failed"
    assert 'audience="aud-os"' in auth["hint"]

    fake.audience = "aud-os"
    fake.enforce_scopes = False
    report = (await owner.post(f"/api/v1/instances/{instance['id']}/test")).json()
    rbac = next(step for step in report["steps"] if step["id"] == "rbac")
    assert rbac["status"] == "warning"


async def test_gateway_operator_denied_with_explanation(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])

    access = (await marcus.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()
    assert access["roles"] == ["Operator"]
    assert "sessions:read" in access["token_scopes"]
    assert "sessions:delete" not in access["token_scopes"]
    assert len(access["token_scopes"]) == 21

    listed = await marcus.get("/api/v1/instances/prod-agentos/os/sessions", params={"limit": 5})
    assert listed.status_code == 200
    assert listed.headers["x-agnostic-instance"] == "prod-agentos"
    seen = fake.calls[-1]
    assert seen["claims"]["sub"].startswith("usr_")
    assert seen["claims"]["agnostic"]["name"] == "Marcus Chen"
    assert "sessions:read" in seen["claims"]["scopes"]
    assert "cookie" not in seen["headers"]
    assert "x-csrf-token" not in seen["headers"]
    assert seen["headers"]["x-request-id"] == listed.headers["x-request-id"]

    calls_before = len(fake.calls)
    denied = await marcus.delete("/api/v1/instances/prod-agentos/os/sessions/x")
    assert denied.status_code == 403
    body = denied.json()
    assert body["code"] == "scope_missing"
    assert body["missing_scopes"] == ["sessions:delete"]
    assert body["route"] == "DELETE /sessions/{session_id}"
    assert "needs `sessions:delete` on prod-agentos" in body["explanation"]
    assert "Marcus Chen has Operator there, which doesn't include it" in body["explanation"]
    assert len(fake.calls) == calls_before  # never reached the runtime

    # The Owner (implicit full access) may.
    assert (await owner.delete("/api/v1/instances/prod-agentos/os/sessions/x")).status_code == 204

    denials = (await owner.get("/api/v1/audit/events", params={"action": "gateway.denied"})).json()["data"]
    assert len(denials) == 1
    assert denials[0]["actor"]["display"] == "Marcus Chen"
    assert denials[0]["missing_scopes"] == ["sessions:delete"]
    assert denials[0]["instance_id"] == instance["id"]
    writes = (await owner.get("/api/v1/audit/events", params={"action": "gateway.request"})).json()["data"]
    assert any(event["resource_display"] == "DELETE /sessions/x" for event in writes)

    explain = (
        await owner.post(
            "/api/v1/access/explain",
            json={"user_id": seen["claims"]["sub"], "scope": "sessions:delete", "instance": "prod-agentos"},
        )
    ).json()
    assert explain["allowed"] is False
    assert explain["alternatives"] == [{"kind": "role", "label": "Instance admin", "role_name": None}]
    assert explain["explanation"].endswith("Instance admin includes it.")

    # Unknown routes fail closed for everyone but admins.
    unknown = await marcus.get("/api/v1/instances/prod-agentos/os/brand-new-route")
    assert unknown.status_code == 403
    assert unknown.json()["required_scopes"] == ["agent_os:admin"]


async def test_gateway_streams_sse_and_bodies(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])

    events: list[str] = []
    async with marcus.stream(
        "POST",
        "/api/v1/instances/prod-agentos/os/agents/support-triage/runs",
        data={"message": "Where is my refund?", "stream": "true"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        events.extend(
            [line.removeprefix("event: ") async for line in response.aiter_lines() if line.startswith("event: ")]
        )
    assert events == ["RunStarted", "RunContent", "RunCompleted"]

    # A large body streams through (Operator can't write sessions; the Owner can).
    payload = b"x" * (3 * 1024 * 1024)
    created = await owner.post(
        "/api/v1/instances/prod-agentos/os/sessions", content=payload, headers={"content-type": "application/json"}
    )
    assert created.status_code == 201
    assert created.json() == {"received_bytes": len(payload)}


async def test_gateway_error_mapping_and_cache(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)

    disabled = await owner.get("/api/v1/instances/prod-agentos/os/approvals/count")
    assert disabled.status_code == 503
    assert disabled.json()["code"] == "capability_disabled"
    assert "Approvals are not enabled" in disabled.json()["detail"]

    first = await owner.get(f"/api/v1/instances/{instance['id']}/os/config")
    assert first.status_code == 200
    calls = len(fake.calls)
    second = await owner.get(f"/api/v1/instances/{instance['id']}/os/config")
    assert second.headers["x-agnostic-cache"] == "hit"
    assert len(fake.calls) == calls

    fake.public_keys = []
    rejected = await owner.get("/api/v1/instances/prod-agentos/os/sessions")
    assert rejected.status_code == 502
    assert rejected.json()["code"] == "instance_auth_failed"
    assert "Test connection" in rejected.json()["detail"]

    stack.routes.runtimes.pop("prod.agentos.test")
    gone = await owner.get("/api/v1/instances/prod-agentos/os/sessions")
    assert gone.status_code == 502
    assert gone.json()["code"] == "instance_unreachable"


async def test_key_rotation_and_jwks(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    jwks_url = f"/.well-known/agnostic/instances/{instance['id']}/jwks.json"
    first_kid = (await stack.client().get(jwks_url)).json()["keys"][0]["kid"]

    staged = (await owner.post(f"/api/v1/instances/{instance['id']}/keys/rotate", json={"action": "stage"})).json()
    assert [key["status"] for key in staged["keys"]] == ["active", "next"]
    jwks = (await stack.client().get(jwks_url)).json()["keys"]
    assert len(jwks) == 2
    assert jwks[0]["kty"] == "RSA"

    # The runtime trusts both (JWKS file / bridge refresh), so activation doesn't break running sessions.
    fake.public_keys = [key["public_pem"] for key in staged["keys"]]
    activated = (
        await owner.post(f"/api/v1/instances/{instance['id']}/keys/rotate", json={"action": "activate"})
    ).json()
    assert [key["status"] for key in activated["keys"]] == ["active"]
    assert activated["keys"][0]["kid"] != first_kid
    response = await owner.get("/api/v1/instances/prod-agentos/os/sessions")
    assert response.status_code == 200
    token = fake.calls[-1]["headers"]["authorization"].removeprefix("Bearer ")
    assert jwt.get_unverified_header(token)["kid"] == activated["keys"][0]["kid"]

    verified = (await owner.post(f"/api/v1/instances/{instance['id']}/keys/verify", json={"token": token})).json()
    assert verified["valid"] is True
    assert verified["key_status"] == "active"
    garbage = (
        await owner.post(f"/api/v1/instances/{instance['id']}/keys/verify", json={"token": "not-a-jwt-at-all"})
    ).json()
    assert garbage["valid"] is False


async def test_instance_admin_rules(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    marcus = await invite_operator(stack, owner, instance["id"])
    assert (await marcus.get("/api/v1/instances")).status_code == 200  # Members see instances
    forbidden = await marcus.post(f"/api/v1/instances/{instance['id']}/keys/rotate", json={"action": "stage"})
    assert forbidden.status_code == 403

    renamed = await owner.patch(
        f"/api/v1/instances/{instance['id']}", json={"display_name": "Production", "version": instance["version"]}
    )
    assert renamed.json()["display_name"] == "Production"
    stale = await owner.patch(
        f"/api/v1/instances/{instance['id']}", json={"display_name": "Prod", "version": instance["version"]}
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"

    wrong = await owner.delete(f"/api/v1/instances/{instance['id']}", params={"confirm": "nope"})
    assert wrong.status_code == 422
    assert (
        await owner.delete(f"/api/v1/instances/{instance['id']}", params={"confirm": "prod-agentos"})
    ).status_code == 204
    assert (await owner.get("/api/v1/instances")).json() == []
