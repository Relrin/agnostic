"""Service accounts end to end: native tokens straight against AgentOS, gateway tokens through the gateway,
rotation, revocation, privileged grants, the last-used poll and the ``agnostic tokens`` CLI."""

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from agnostic_kernel.domain_events import DomainEvents
from agnostic_server.tokens import create_lines, list_lines, revoke_lines
from agnostic_service_accounts.application.accounts import ServiceAccounts
from tests.api.test_instances_gateway import PROD, connect
from tests.api.test_operate import audit_events, pending_refund
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

ZENDESK_SCOPES = [
    "agents:support-triage:run",
    "agents:billing-agent:run",
    "teams:escalation-team:run",
    "workflows:ticket-router:run",
    "sessions:read",
    "sessions:write",
]
NATIVE = "agno" + "_pat_"
GATEWAY = "agn" + "_pat_"


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_SERVICE_ACCOUNTS__POLL_CRON", "")
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_APPROVALS__WATCH_CRON", "")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self: DomainEvents, event: str, payload: Mapping[str, Any]) -> None:
        events.append((event, dict(payload)))

    monkeypatch.setattr(DomainEvents, "publish", publish)
    return events


async def create(owner: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await owner.post("/api/v1/service-accounts", json={"instances": ["prod-agentos"], **body})


def bearer(stack: Stack, token: str) -> httpx.AsyncClient:
    client = stack.client()
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def direct(fake: FakeAgentOS, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake.app), base_url=PROD, headers={"Authorization": f"Bearer {token}"}
    )


def token_of(created: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(item for item in created["tokens"] if item["kind"] == kind)


async def test_zendesk_bridge_native_and_gateway_tokens(  # noqa: PLR0915  (one story, start to end)
    stack: Stack, published: list[tuple[str, dict[str, Any]]]
) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    body: dict[str, Any] = {
        "name": "zendesk-bridge",
        "description": "Forwards Zendesk tickets to the support agents and posts replies back.",
        "scopes": ZENDESK_SCOPES,
        "expires_in": "never",
        "kinds": ["native", "gateway"],
        "forwards_user_id": True,
    }

    # sessions:write is privileged: an explicit confirmation first.
    refused = await create(owner, **body)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "privileged_confirmation_required"
    assert refused.json()["privileged_scopes"] == ["sessions:write"]
    assert fake.service_accounts == {}

    response = await create(owner, **body, confirm_privileged=True)
    assert response.status_code == 201, response.text
    created = response.json()
    account = created["account"]
    assert account["principal"] == "sa:zendesk-bridge"
    assert account["source_label"] == "Custom scopes"
    assert account["scope_count"] == 6
    assert account["expiry_warning"] is True
    assert account["privileged"] is True
    assert [i["slug"] for i in account["instances"]] == ["prod-agentos"]
    assert "user isolation applies" in account["isolation_note"]
    assert "--kind native \\\n  --kind gateway" in account["cli_command"]
    native = token_of(created, "native")
    gateway = token_of(created, "gateway")
    assert native["token"].startswith(NATIVE)
    assert native["instance"]["id"] == instance["id"]
    assert gateway["token"].startswith(GATEWAY)
    assert gateway["prefix"] == gateway["token"][:12]
    assert "/agents/billing-agent/runs" in native["curl"]
    assert "/api/v1/instances/prod-agentos/os/agents/billing-agent/runs" in gateway["curl"]
    assert [event for event, _ in published] == ["service_accounts.privileged_created"]

    # AgentOS got one service account, with exactly these scopes and no expiry.
    (remote,) = fake.service_accounts.values()
    assert remote["principal"] == "sa:zendesk-bridge"
    assert sorted(item["scope"] for item in remote["scopes"]) == sorted(ZENDESK_SCOPES)
    assert remote["expires_at"] is None
    assert native["prefix"] == remote["token_prefix"]

    # The native token works straight against the runtime, with per-agent run scopes.
    async with direct(fake, native["token"]) as runtime:
        triage = await runtime.post("/agents/support-triage/runs", data={"message": "Ticket 4411", "user_id": "x"})
        assert triage.status_code == 200, triage.text
        assert fake.run_requests[-1]["user_id"] == "sa:zendesk-bridge"
        billing = await runtime.post("/agents/billing-agent/runs", data={"message": "Refund?"})
        assert billing.status_code == 200
        other = await runtime.post("/agents/research-agent/runs", data={"message": "Hi"})
        assert other.status_code == 403
        deleted = await runtime.delete("/sessions/ses_1")
        assert deleted.status_code == 403
    async with direct(fake, NATIVE + "x" * 32) as stranger:
        assert (await stranger.get("/sessions")).status_code == 401

    # The gateway token: the control plane mints svc_<name> plus the agnostic.principal claim.
    pat = bearer(stack, gateway["token"])
    run = await pat.post(
        "/api/v1/instances/prod-agentos/os/agents/support-triage/runs",
        data={"message": "Ticket 4412", "user_id": "zd:ticket-user-9"},
    )
    assert run.status_code == 200, run.text
    claims = fake.calls[-1]["claims"]
    assert claims["sub"] == "svc_zendesk-bridge"
    assert claims["agnostic"]["principal"] == "sa:zendesk-bridge"
    assert claims["agnostic"]["via"] == "gateway-pat"
    assert claims["agnostic"]["instance"] == instance["id"]
    assert sorted(claims["scopes"]) == sorted(ZENDESK_SCOPES)
    assert fake.run_requests[-1]["form"]["user_id"] == "zd:ticket-user-9"  # it forwards user_id
    denied = await pat.delete("/api/v1/instances/prod-agentos/os/sessions/ses_1")
    assert denied.status_code == 403
    assert denied.json()["missing_scopes"] == ["sessions:delete"]
    assert "sa:zendesk-bridge" in denied.json()["detail"]

    # Bearer tokens skip the cookie session; a made-up one is a 401.
    assert (
        await bearer(stack, GATEWAY + "y" * 32).get("/api/v1/instances/prod-agentos/os/sessions")
    ).status_code == 401

    detail = (await owner.get(f"/api/v1/service-accounts/{account['id']}")).json()
    assert {item["source"] for item in detail["scope_items"]} == {"custom"}
    assert [t["status"] for t in detail["native_tokens"]] == ["active"]
    assert detail["gateway_tokens"][0]["last_used_at"] is not None
    listed = (await owner.get("/api/v1/service-accounts")).json()
    assert [(row["name"], row["created_by"]["name"]) for row in listed] == [("zendesk-bridge", "Daniel Okafor")]
    assert listed[0]["last_used_at"] is not None
    actions = [event["action"] for event in (await owner.get("/api/v1/audit/events")).json()["data"]]
    assert "service_accounts.create" in actions
    assert actions.count("tokens.create") == 2


async def test_scoped_service_accounts_cant_resolve_approvals(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    _ = await connect(owner, fake)
    roles = {role["slug"]: role["id"] for role in (await owner.get("/api/v1/access/roles")).json()}
    created = await create(
        owner,
        name="slack-bot",
        description="Posts approval requests to Slack and answers questions with support-triage.",
        role_id=roles["viewer"],
        scopes=["agents:support-triage:run", "approvals:write"],
        kinds=["gateway"],
        confirm_privileged=True,
    )
    assert created.status_code == 201, created.text
    account = created.json()["account"]
    assert account["source_label"] == "Access role: Viewer + 2 scopes"
    assert "404 on resolve" in account["isolation_note"]
    pending_refund(fake)
    pat = bearer(stack, token_of(created.json(), "gateway")["token"])

    passthrough = await pat.post(
        "/api/v1/instances/prod-agentos/os/approvals/apr_1/resolve", json={"status": "approved", "resolved_by": "x"}
    )
    assert passthrough.status_code == 403, passthrough.text
    assert passthrough.json()["code"] == "service_account_denied"
    assert "Scoped service accounts can't resolve approvals" in passthrough.json()["detail"]

    typed = await pat.post("/api/v1/instances/prod-agentos/approvals/apr_1/decide", json={"decision": "approve"})
    assert typed.status_code == 403, typed.text
    assert "Scoped service accounts can't resolve approvals" in typed.json()["detail"]
    assert fake.resolutions == []
    assert fake.approvals["apr_1"]["status"] == "pending"

    denials = [e for e in await audit_events(owner, "gateway.denied") if e["actor"]["kind"] == "service_account"]
    assert len(denials) == 2
    assert all(event["actor"]["display"] == "sa:slack-bot" for event in denials)
    assert all("Scoped service accounts can't resolve approvals" in event["summary"] for event in denials)
    assert all("Scoped service accounts can't resolve approvals" in event["denial_reason"] for event in denials)
    assert {event["resource_display"] for event in denials} == {
        "POST /approvals/apr_1/resolve",
        "GET /approvals/apr_1",
    }


async def test_gateway_rotation_grace_and_revocation(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    _ = await connect(owner, fake)
    created = await create(
        owner,
        name="ci-evals",
        description="Runs eval suites from CI on every pull request.",
        scopes=["agents:read", "agents:run", "evals:read"],
        expires_in="30d",
        kinds=["gateway"],
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["account"]["id"]
    assert fake.service_accounts == {}  # gateway only: nothing provisioned on the runtime
    old = token_of(created.json(), "gateway")
    old_client = bearer(stack, old["token"])
    assert (await old_client.get("/api/v1/instances/prod-agentos/os/agents")).status_code == 200

    # Without forwards_user_id, a user_id the caller sends is dropped (query string and form).
    run = await old_client.post(
        "/api/v1/instances/prod-agentos/os/agents/support-triage/runs",
        params={"user_id": "someone-else"},
        data={"message": "Nightly evals", "user_id": "someone-else"},
    )
    assert run.status_code == 200, run.text
    assert "user_id" not in fake.run_requests[-1]["form"]
    assert "user_id" not in fake.run_requests[-1]["query"]
    assert fake.run_requests[-1]["form"]["message"] == "Nightly evals"
    assert fake.run_requests[-1]["sub"] == "svc_ci-evals"

    rotated = await owner.post(f"/api/v1/service-accounts/{account_id}/tokens", json={"kind": "gateway"})
    assert rotated.status_code == 201, rotated.text
    assert rotated.json()["replaced_id"] == old["id"]
    grace = datetime.fromisoformat(rotated.json()["grace_until"])
    assert 23 * 3600 < (grace - datetime.now(UTC)).total_seconds() <= 24 * 3600
    new = rotated.json()["token"]
    assert new["token"] != old["token"]
    tokens = {t["id"]: t for t in rotated.json()["account"]["gateway_tokens"]}
    assert tokens[old["id"]]["status"] == "active"
    assert tokens[old["id"]]["revoke_reason"] == "rotated"

    # Both work during the grace period.
    assert (await old_client.get("/api/v1/instances/prod-agentos/os/agents")).status_code == 200
    new_client = bearer(stack, new["token"])
    assert (await new_client.get("/api/v1/instances/prod-agentos/os/agents")).status_code == 200

    revoked = await owner.delete(f"/api/v1/service-accounts/{account_id}/tokens/{old['prefix']}")
    assert revoked.status_code == 200, revoked.text
    assert (await old_client.get("/api/v1/instances/prod-agentos/os/agents")).status_code == 401
    assert (await new_client.get("/api/v1/instances/prod-agentos/os/agents")).status_code == 200
    actions = [event["action"] for event in (await owner.get("/api/v1/audit/events")).json()["data"]]
    assert {"tokens.rotate", "tokens.revoke"} <= set(actions)


async def test_privileged_creation_needs_confirmation_and_announces_it(
    stack: Stack, published: list[tuple[str, dict[str, Any]]]
) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    _ = await connect(owner, fake)
    body: dict[str, Any] = {"name": "token-minter", "scopes": ["service_accounts:write", "agents:read"]}

    preview = (
        await owner.post("/api/v1/service-accounts/preview", json={**body, "instances": ["prod-agentos"]})
    ).json()
    assert preview["principal"] == "sa:token-minter"
    assert preview["privileged_scopes"] == ["service_accounts:write"]
    assert "--yes-privileged" in preview["cli_command"]

    refused = await create(owner, **body)
    assert refused.status_code == 422
    assert published == []
    created = await create(owner, **body, confirm_privileged=True)
    assert created.status_code == 201, created.text
    (remote,) = fake.service_accounts.values()
    assert {item["scope"] for item in remote["scopes"]} == {"service_accounts:write", "agents:read"}

    ((event, payload),) = published
    assert event == "service_accounts.privileged_created"
    assert payload["principal"] == "sa:token-minter"
    assert payload["privileged_scopes"] == ["service_accounts:write"]
    assert payload["instances"] == ["prod-agentos"]
    assert payload["created_by_name"] == "Daniel Okafor"
    assert set(payload) >= {"service_account_id", "name", "scopes", "created_by"}

    duplicate = await create(owner, **body, confirm_privileged=True)
    assert duplicate.status_code == 409


async def test_delete_revokes_native_tokens_on_the_instance(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    _ = await connect(owner, fake)
    created = await create(
        owner, name="slack-bot", scopes=["agents:read", "sessions:read"], kinds=["native", "gateway"]
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["account"]["id"]
    native = token_of(created.json(), "native")["token"]
    gateway = token_of(created.json(), "gateway")["token"]
    async with direct(fake, native) as runtime:
        assert (await runtime.get("/sessions")).status_code == 200

    # Native rotation: revoke, then recreate under the same name.
    rotated = await owner.post(
        f"/api/v1/service-accounts/{account_id}/tokens", json={"kind": "native", "instance": "prod-agentos"}
    )
    assert rotated.status_code == 201, rotated.text
    statuses = sorted(t["status"] for t in rotated.json()["account"]["native_tokens"])
    assert statuses == ["active", "revoked"]
    async with direct(fake, native) as runtime:
        assert (await runtime.get("/sessions")).status_code == 401
    native = rotated.json()["token"]["token"]

    deleted = await owner.delete(f"/api/v1/service-accounts/{account_id}")
    assert deleted.status_code == 204, deleted.text
    assert all(account["revoked_at"] is not None for account in fake.service_accounts.values())
    async with direct(fake, native) as runtime:
        assert (await runtime.get("/sessions")).status_code == 401
    assert (await bearer(stack, gateway).get("/api/v1/instances/prod-agentos/os/sessions")).status_code == 401
    assert (await owner.get(f"/api/v1/service-accounts/{account_id}")).status_code == 404
    assert (await owner.get("/api/v1/service-accounts")).json() == []
    assert "service_accounts.delete" in [e["action"] for e in await audit_events(owner, "service_accounts.delete")]

    # The name is free again.
    again = await create(owner, name="slack-bot", scopes=["agents:read"], kinds=["gateway"])
    assert again.status_code == 201, again.text


async def test_poll_updates_last_used_and_revocations(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    _ = await connect(owner, fake)
    created = await create(owner, name="ci-evals", scopes=["agents:read"])
    assert created.status_code == 201, created.text
    account_id = created.json()["account"]["id"]
    used_at = int(datetime(2026, 11, 2, 9, 30, tzinfo=UTC).timestamp())
    fake.touch_service_account("ci-evals", at=used_at)

    async with stack.container() as request:
        report = await (await request.get(ServiceAccounts)).poll()
    assert report.updated == 1

    detail = (await owner.get(f"/api/v1/service-accounts/{account_id}")).json()
    assert datetime.fromisoformat(detail["native_tokens"][0]["last_used_at"]).timestamp() == used_at
    assert datetime.fromisoformat(detail["last_used_at"]).timestamp() == used_at

    # Revoked on the runtime itself (os.agno.com): the next poll notices.
    for remote in fake.service_accounts.values():
        remote["revoked_at"] = used_at + 60
    async with stack.container() as request:
        _ = await (await request.get(ServiceAccounts)).poll()
    detail = (await owner.get(f"/api/v1/service-accounts/{account_id}")).json()
    assert detail["native_tokens"][0]["status"] == "revoked"


async def test_cli_create_list_and_revoke(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    _ = await connect(owner, fake)

    lines = await create_lines(
        stack.container,
        "airflow-nightly",
        instances=["prod-agentos"],
        role=None,
        scopes=["agents:read", "agents:support-triage:run"],
        expires_in="90d",
        kinds=["native", "gateway"],
        forwards_user_id=False,
        created_by="daniel@localhost.company",
        yes_privileged=False,
    )
    assert lines[0].startswith("created sa:airflow-nightly")
    assert any(line.startswith(NATIVE) for line in lines)
    assert any(line.startswith(GATEWAY) for line in lines)
    listed = (await owner.get("/api/v1/service-accounts")).json()
    assert listed[0]["created_by"]["name"] == "Daniel Okafor"

    table = await list_lines(stack.container)
    assert table[0].startswith("sa:airflow-nightly")
    assert "active" in table[0]
    assert await revoke_lines(stack.container, "airflow-nightly", None) == [
        "deleted sa:airflow-nightly: every token revoked, its grants removed"
    ]
    assert await list_lines(stack.container) == ["No service accounts yet."]
