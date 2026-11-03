"""Groups, editable roles and temporary access, end to end through the API and the gateway."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from agnostic_access.application.requests import TemporaryAccess
from agnostic_kernel.db import utcnow
from agnostic_kernel.testing import wait_for
from tests.api.test_instances_gateway import connect
from tests.support.stack import Stack, running_stack


@pytest.fixture
async def stack(sqlite_database: str) -> AsyncIterator[Stack]:
    async with running_stack(sqlite_database) as running:
        yield running


async def invite(stack: Stack, owner: httpx.AsyncClient, email: str, name: str) -> tuple[httpx.AsyncClient, str]:
    invited = await owner.post("/api/v1/invitations", json={"email": email})
    assert invited.status_code == 201, invited.text
    token = invited.json()["accept_url"].rsplit("/", 1)[1]
    client = stack.client()
    joined = await client.post(
        f"/api/v1/invitations/{token}/accept", json={"display_name": name, "password": f"{name}'s long password"}
    )
    assert joined.status_code == 200, joined.text
    client.headers["X-CSRF-Token"] = joined.json()["csrf_token"]
    me = (await client.get("/api/v1/me")).json()
    return client, me["id"]


async def roles_by_slug(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    return {role["slug"]: role for role in (await client.get("/api/v1/access/roles")).json()}


async def test_operator_edit_reaches_group_members_on_their_next_request(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    instance = await connect(owner, fake)
    maya, maya_id = await invite(stack, owner, "maya@localhost.company", "Maya Chen")

    # No access yet: a member without bindings.
    assert (await maya.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()["roles"] == []

    group = await owner.post(
        "/api/v1/directory/groups", json={"name": "Support AI", "member_ids": [maya_id], "description": "Tier 2"}
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    assert group.json()["sync_label"] == "Manual"
    operator = (await roles_by_slug(owner))["operator"]
    bound = await owner.post(
        "/api/v1/access/bindings",
        json={
            "principal_kind": "group",
            "principal_id": group_id,
            "instance": "prod-agentos",
            "role_id": operator["id"],
        },
    )
    assert bound.status_code == 201, bound.text

    access = (await maya.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()
    assert access["roles"] == ["Operator"]
    assert {grant["via_group_name"] for grant in access["grants"] if grant["source"] == "binding"} == {"Support AI"}
    explained = (
        await owner.post(
            "/api/v1/access/explain",
            json={
                "user_id": maya_id,
                "resource": "agents",
                "verb": "run",
                "component": "billing-agent",
                "instance": "prod-agentos",
            },
        )
    ).json()
    assert explained["allowed"] is True
    assert explained["via_group"] == "Support AI"
    assert "via Support AI" in explained["explanation"]

    assert (await maya.get("/api/v1/instances/prod-agentos/os/sessions")).status_code == 200
    assert "knowledge:write" not in fake.calls[-1]["claims"]["scopes"]

    # The demo edit: +knowledge:write, −approvals:delete.
    permissions = {resource: list(actions) for resource, actions in operator["permissions"].items()}
    permissions["knowledge"] = ["read", "write"]
    permissions["approvals"] = ["read", "write"]
    draft = {
        "name": operator["name"],
        "description": operator["description"],
        "color": operator["color"],
        "permissions": permissions,
        "run_scope": operator["run_scope"],
        "bindable_instance_ids": operator["bindable_instance_ids"],
    }
    preview = (await owner.post(f"/api/v1/access/roles/{operator['id']}/preview", json=draft)).json()
    assert preview["added"] == ["knowledge:write"]
    assert preview["removed"] == ["approvals:delete"]
    assert preview["reach"]["people"] == 1
    assert preview["reach"]["sentence"] == "1 person and 1 group (Support AI)"
    assert preview["redeploy"] is False
    assert len(preview["role"]["scopes"]) == len(operator["scopes"])

    stale = await owner.patch(f"/api/v1/access/roles/{operator['id']}", json={**draft, "version": 99})
    assert stale.status_code == 409
    saved = await owner.patch(f"/api/v1/access/roles/{operator['id']}", json={**draft, "version": operator["version"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["role"]["version"] == operator["version"] + 1

    assert (await maya.get("/api/v1/instances/prod-agentos/os/sessions")).status_code == 200
    scopes = fake.calls[-1]["claims"]["scopes"]
    assert "knowledge:write" in scopes
    assert "approvals:delete" not in scopes

    versions = (await owner.get(f"/api/v1/access/roles/{operator['id']}/versions")).json()
    assert [version["version"] for version in versions] == [operator["version"] + 1]
    audit = (await owner.get("/api/v1/audit/events", params={"action": "roles.update"})).json()["data"]
    assert audit[0]["diff"]["lines"] == [
        {"op": "add", "text": "knowledge:write"},
        {"op": "remove", "text": "approvals:delete"},
    ]
    assert "No redeploy" in audit[0]["diff"]["note"]

    # Leaving the group takes the access away.
    assert (await owner.delete(f"/api/v1/directory/groups/{group_id}/members/{maya_id}")).status_code == 200
    assert (await maya.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()["roles"] == []
    assert instance["id"]


async def test_custom_roles_are_validated_versioned_and_not_deleted_while_bound(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    _, lena_id = await invite(stack, owner, "lena@localhost.company", "Lena Ito")

    unknown = await owner.post("/api/v1/access/roles", json={"name": "Odd", "permissions": {"agents": ["teleport"]}})
    assert unknown.status_code == 422
    assert "agents:teleport" in unknown.json()["detail"]

    created = await owner.post(
        "/api/v1/access/roles",
        json={
            "name": "Billing runner",
            "color": "#7DA6FF",
            "permissions": {"agents": ["read", "run"], "sessions": ["read"]},
            "run_scope": {"agents": ["billing-agent"]},
        },
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["kind"] == "custom"
    assert role["slug"] == "billing-runner"
    assert role["scopes"] == ["agents:billing-agent:run", "agents:read", "sessions:read"]

    copy = (await owner.post(f"/api/v1/access/roles/{role['id']}/duplicate", json={})).json()
    assert copy["name"] == "Billing runner copy"

    binding = await owner.post(
        "/api/v1/access/bindings", json={"user_id": lena_id, "instance": "prod-agentos", "role_id": role["id"]}
    )
    assert binding.status_code == 201
    blocked = await owner.delete(f"/api/v1/access/roles/{role['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["bindings"][0]["principal_name"] == "Lena Ito"

    assert (await owner.delete(f"/api/v1/access/bindings/{binding.json()['id']}")).status_code == 204
    assert (await owner.delete(f"/api/v1/access/roles/{role['id']}")).status_code == 204
    assert (await owner.delete("/api/v1/access/roles/rol_operator")).status_code == 422

    # Built-ins can be reset after an edit.
    operator = (await roles_by_slug(owner))["operator"]
    edited = {
        "name": "Operator",
        "description": operator["description"],
        "color": operator["color"],
        "permissions": {"agents": ["read"]},
    }
    assert (
        await owner.patch(f"/api/v1/access/roles/{operator['id']}", json={**edited, "version": operator["version"]})
    ).status_code == 200
    reset = (await owner.post(f"/api/v1/access/roles/{operator['id']}/reset")).json()
    assert reset["role"]["scopes"] == operator["scopes"]


async def test_temporary_access_is_requested_approved_and_expires(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    priya, priya_id = await invite(stack, owner, "priya@localhost.company", "Priya Nair")
    roles = await roles_by_slug(owner)

    too_long = await priya.post(
        "/api/v1/access/requests",
        json={"instance": "prod-agentos", "role_id": roles["builder"]["id"], "reason": "Hotfix", "duration_hours": 999},
    )
    assert too_long.status_code == 422
    asked = await priya.post(
        "/api/v1/access/requests",
        json={
            "instance": "prod-agentos",
            "role_id": roles["builder"]["id"],
            "reason": "Hotfix INC-42",
            "duration_hours": 4,
        },
    )
    assert asked.status_code == 201, asked.text
    request_id = asked.json()["id"]

    assert (await priya.post(f"/api/v1/access/requests/{request_id}/approve", json={})).status_code == 403

    async def bell(client: httpx.AsyncClient) -> list[dict[str, Any]]:
        return (await client.get("/api/v1/notifications")).json()["data"]

    asked_items = await wait_for(
        lambda: bell(owner), lambda found: any(i["kind"] == "access.request_created" for i in found)
    )
    notice = next(i for i in asked_items if i["kind"] == "access.request_created")
    assert notice["title"] == "Priya Nair asks for Builder on prod-agentos"
    pending = (await owner.get("/api/v1/access/requests", params={"status": "pending"})).json()
    assert [(item["id"], item["can_decide"]) for item in pending] == [(request_id, True)]

    approved = (await owner.post(f"/api/v1/access/requests/{request_id}/approve", json={"note": "ok"})).json()
    assert approved["status"] == "approved"
    expires = datetime.fromisoformat(approved["expires_at"])
    assert timedelta(hours=3, minutes=59) < expires - datetime.now(UTC) <= timedelta(hours=4)
    access = (await priya.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()
    assert access["roles"] == ["Builder"]
    decided = await wait_for(
        lambda: bell(priya), lambda found: any(i["kind"] == "access.request_decided" for i in found)
    )
    assert next(i for i in decided if i["kind"] == "access.request_decided")["title"].startswith(
        "Daniel Okafor approved your request for Builder"
    )

    # Direct grants respect the org's limit too.
    over = await owner.post(
        "/api/v1/access/temporary",
        json={
            "principal_id": priya_id,
            "instance": "prod-agentos",
            "scopes": ["knowledge:delete"],
            "reason": "cleanup",
            "duration_hours": 500,
        },
    )
    assert over.status_code == 422

    # Expiry: the sweep removes the binding and closes the request.
    async with stack.container() as request:
        temporary = await request.get(TemporaryAccess)
        binding = await temporary.c.bindings.get(approved["binding_id"])
        assert binding is not None
        await temporary.c.bindings.delete(binding.id)
        await temporary.c.bindings.add(replace(binding, expires_at=utcnow() - timedelta(minutes=1)))
        await temporary.c.bindings.commit()
        assert await temporary.expire() == 1

    assert (await priya.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()["roles"] == []
    closed = (await priya.get("/api/v1/access/requests", params={"mine": "true"})).json()
    assert closed[0]["status"] == "expired"
    expired = (await owner.get("/api/v1/audit/events", params={"action": "bindings.expire"})).json()["data"]
    assert expired[0]["actor"]["kind"] == "system"


async def test_deleting_a_group_removes_its_bindings(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    jonas, jonas_id = await invite(stack, owner, "jonas@localhost.company", "Jonas Weber")
    group = (await owner.post("/api/v1/directory/groups", json={"name": "Finance", "member_ids": [jonas_id]})).json()
    viewer = (await roles_by_slug(owner))["viewer"]
    await owner.post(
        "/api/v1/access/bindings",
        json={
            "principal_kind": "group",
            "principal_id": group["id"],
            "instance": "prod-agentos",
            "role_id": viewer["id"],
        },
    )
    assert (await jonas.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()["roles"] == ["Viewer"]
    listed = (await owner.get("/api/v1/access/roles")).json()
    assert next(role for role in listed if role["slug"] == "viewer")["groups"] == 1

    assert (await owner.delete(f"/api/v1/directory/groups/{group['id']}")).status_code == 204
    assert (await jonas.get("/api/v1/me/access", params={"instance": "prod-agentos"})).json()["roles"] == []
    assert (await owner.get("/api/v1/access/bindings", params={"principal": group["id"]})).json() == []


async def test_members_bulk_export_and_invitation_groups(stack: Stack) -> None:
    owner = await stack.owner()
    _, omar_id = await invite(stack, owner, "omar@localhost.company", "Omar Haddad")
    _, lena_id = await invite(stack, owner, "lena@localhost.company", "Lena Ito")
    research = (await owner.post("/api/v1/directory/groups", json={"name": "Research"})).json()

    outcomes = (
        await owner.post(
            "/api/v1/members/bulk",
            json={
                "user_ids": [omar_id, lena_id, "usr_nobody"],
                "operation": "add_to_group",
                "group_id": research["id"],
            },
        )
    ).json()
    assert [item["ok"] for item in outcomes] == [True, True, False]
    members = {member["user_id"]: member for member in (await owner.get("/api/v1/members")).json()}
    assert members[omar_id]["groups"] == [{"id": research["id"], "name": "Research"}]

    promoted = (
        await owner.post(
            "/api/v1/members/bulk",
            json={"user_ids": [omar_id], "operation": "change_role", "org_role": "administrator"},
        )
    ).json()
    assert promoted == [{"user_id": omar_id, "ok": True, "error": None}]

    exported = await owner.get("/api/v1/members/export.csv")
    assert exported.headers["content-type"].startswith("text/csv")
    lines = exported.text.strip().splitlines()
    assert lines[0] == "email,name,org_role,groups,joined_at,joined_via,last_active_at"
    assert any(line.startswith("omar@localhost.company,Omar Haddad,administrator,Research") for line in lines)

    invited = await owner.post(
        "/api/v1/invitations", json={"email": "rafael@localhost.company", "group_ids": [research["id"]]}
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["invitation"]["group_ids"] == [research["id"]]
    _, rafael_id = await invite_accept(stack, invited.json()["accept_url"], "Rafael Souza")
    detail = (await owner.get(f"/api/v1/directory/groups/{research['id']}")).json()
    assert rafael_id in {member["user_id"] for member in detail["members"]}


async def invite_accept(stack: Stack, accept_url: str, name: str) -> tuple[httpx.AsyncClient, str]:
    client = stack.client()
    joined = await client.post(
        f"/api/v1/invitations/{accept_url.rsplit('/', 1)[1]}/accept",
        json={"display_name": name, "password": f"{name}'s long password"},
    )
    assert joined.status_code == 200, joined.text
    return client, joined.json()["user_id"]


async def test_approval_routes_can_name_groups(stack: Stack) -> None:
    owner = await stack.owner()
    _, maya_id = await invite(stack, owner, "maya@localhost.company", "Maya Chen")
    group = (await owner.post("/api/v1/directory/groups", json={"name": "Support AI", "member_ids": [maya_id]})).json()

    created = await owner.post(
        "/api/v1/approvals/routes",
        json={"name": "Refunds", "tool_name": "refund_customer", "group_ids": [group["id"]]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["groups"] == [{"id": group["id"], "name": "Support AI"}]
    unknown = await owner.post("/api/v1/approvals/routes", json={"name": "Nope", "group_ids": ["grp_missing"]})
    assert unknown.status_code == 422

    routed = (await owner.get(f"/api/v1/approvals/routes/by-group/{group['id']}")).json()
    assert [route["name"] for route in routed] == ["Refunds"]


async def test_identical_scope_bindings_are_refused(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    _, omar_id = await invite(stack, owner, "omar@localhost.company", "Omar Haddad")
    body = {"user_id": omar_id, "instance": "prod-agentos", "scopes": ["agents:billing-agent:run"]}
    assert (await owner.post("/api/v1/access/bindings", json=body)).status_code == 201
    assert (await owner.post("/api/v1/access/bindings", json=body)).status_code == 409
    other = {**body, "scopes": ["agents:billing-agent:run", "sessions:read"]}
    assert (await owner.post("/api/v1/access/bindings", json=other)).status_code == 201
