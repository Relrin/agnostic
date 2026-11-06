"""The tool catalog end to end: org, team and custom entries, who sees and changes them, credentials as env refs,
the manifest a bridge pulls with its sync token, and the badges Studio shows on catalog tools."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from tests.api.test_governance import invite
from tests.api.test_instances_gateway import connect
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

CATALOG = "/api/v1/tool-catalog"
LINEAR: dict[str, Any] = {
    "slug": "linear",
    "level": "org",
    "display_name": "Linear",
    "kind": "mcp",
    "transport": "streamable-http",
    "config": {
        "url": "https://mcp.linear.app/mcp",
        "headers": {"Authorization": {"env": "LINEAR_TOKEN", "format": "Bearer {}"}},
    },
}
SEARCH: dict[str, Any] = {
    "slug": "search",
    "level": "org",
    "display_name": "Web search",
    "kind": "toolkit",
    "toolkit_key": "duck_duck_go",
}


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_SERVICE_ACCOUNTS__POLL_CRON", "")
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_APPROVALS__WATCH_CRON", "")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


async def add(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post(f"{CATALOG}/entries", json=body)


def bridge_status(fake: FakeAgentOS, entries: list[dict[str, Any]]) -> None:
    """The fake runtime answers the bridge's tool catalog status route."""

    async def status(request: Request) -> JSONResponse:
        return JSONResponse({"enabled": True, "local_allowed": False, "interval_seconds": 60, "entries": entries})

    fake.app.add_api_route("/agnostic/v1/tool-catalog/status", status, methods=["GET"])


async def test_org_entries_are_offered_to_everyone_and_managed_by_admins(stack: Stack) -> None:
    owner = await stack.owner()
    await connect(owner, stack.runtime("prod.agentos.test"))
    maya, _ = await invite(stack, owner, "maya@localhost.company", "Maya Chen")

    created = await add(owner, **LINEAR)
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["registry_name"] == "org-linear"
    assert entry["level_label"] == "Organization"
    assert entry["config"]["tool_name_prefix"] == "org_linear_"
    assert entry["config"]["headers"] == {"Authorization": {"env": "LINEAR_TOKEN", "format": "Bearer {}"}}
    assert entry["editable"] is True

    seen = (await maya.get(f"{CATALOG}/entries")).json()
    assert [item["registry_name"] for item in seen] == ["org-linear"]
    assert seen[0]["editable"] is False

    refused = await add(maya, **{**LINEAR, "slug": "linear-2"})
    assert refused.status_code == 422
    assert "org owners and administrators" in refused.json()["detail"]

    changed = await owner.patch(
        f"{CATALOG}/entries/{entry['id']}", json={"version": entry["version"], "display_name": "Linear (prod)"}
    )
    assert changed.status_code == 200, changed.text
    stale = await owner.patch(f"{CATALOG}/entries/{entry['id']}", json={"version": entry["version"], "icon": "x"})
    assert stale.status_code == 409
    renamed = await owner.patch(
        f"{CATALOG}/entries/{entry['id']}", json={"version": changed.json()["version"], "slug": "other"}
    )
    assert renamed.status_code == 422  # name, level and kind stay: the runtime knows the tool by them

    nulls = await owner.patch(
        f"{CATALOG}/entries/{entry['id']}",
        json={"version": changed.json()["version"], "config": None, "instance_ids": None, "description": None},
    )
    assert nulls.status_code == 200, nulls.text  # nulls leave fields as they are
    probed = await maya.post(f"{CATALOG}/entries/{entry['id']}/discover", params={"instance": "prod-agentos"})
    assert probed.status_code == 403  # a member can't make a runtime connect somewhere

    disabled = await owner.post(f"{CATALOG}/entries/{entry['id']}/disable")
    assert disabled.json()["status"] == "disabled"
    assert (await maya.get(f"{CATALOG}/entries")).json() == []


async def test_credentials_are_environment_variable_names_never_values(stack: Stack) -> None:
    owner = await stack.owner()
    literal = await add(owner, **{**LINEAR, "config": {**LINEAR["config"], "headers": {"Authorization": "Bearer x"}}})
    assert literal.status_code == 422
    assert "environment variable" in literal.json()["detail"]

    in_url = await add(owner, **{**LINEAR, "config": {"url": "https://mcp.example.com/mcp?api_key=secret"}})
    assert in_url.status_code == 422

    secret_param = await add(
        owner, slug="gh", level="org", display_name="GitHub", kind="toolkit", toolkit_key="github",
        config={"params": {"access_token": "ghp_value"}},
    )  # fmt: skip
    assert secret_param.status_code == 422
    from_env = await add(
        owner, slug="gh", level="org", display_name="GitHub", kind="toolkit", toolkit_key="github",
        config={"params": {"access_token": {"env": "GITHUB_TOKEN"}}},
    )  # fmt: skip
    assert from_env.status_code == 201, from_env.text

    unknown = await add(owner, **{**SEARCH, "toolkit_key": "os_system"})
    assert unknown.status_code == 422


async def test_team_entries_belong_to_a_group_and_its_owners(stack: Stack) -> None:
    owner = await stack.owner()
    maya, maya_id = await invite(stack, owner, "maya@localhost.company", "Maya Chen")
    jonas, jonas_id = await invite(stack, owner, "jonas@localhost.company", "Jonas Berg")
    lena, _ = await invite(stack, owner, "lena@localhost.company", "Lena Park")
    group = (await owner.post("/api/v1/directory/groups", json={"name": "Data", "member_ids": [jonas_id]})).json()
    made_owner = await owner.put(f"/api/v1/directory/groups/{group['id']}/members/{maya_id}", json={"role": "owner"})
    assert made_owner.status_code == 200, made_owner.text

    prod = await connect(owner, stack.runtime("prod.agentos.test"))
    builder = next(role for role in (await owner.get("/api/v1/access/roles")).json() if role["slug"] == "builder")
    bound = await owner.post(
        "/api/v1/access/bindings",
        json={"principal_kind": "user", "principal_id": maya_id, "instance": "prod-agentos", "role_id": builder["id"]},
    )
    assert bound.status_code == 201, bound.text

    # The org already offers web search; the team adds its own configuration of the same toolkit.
    assert (await add(owner, **SEARCH)).status_code == 201
    team_search = {**SEARCH, "level": "team", "owner_group_id": group["id"], "display_name": "Data search"}
    # A team owner reaches only the instances they build on, never every runtime at once.
    everywhere = await add(maya, **team_search)
    assert everywhere.status_code == 422
    assert "catalog managers" in everywhere.json()["detail"]
    team = await add(maya, **team_search, instance_ids=[prod["id"]])
    assert team.status_code == 201, team.text
    entry = team.json()
    assert entry["registry_name"] == "team-data-search"
    assert entry["level_label"] == "Team · Data"
    assert [item["level_label"] for item in entry["same_as"]] == ["Organization"]

    # A plain member of the group sees it but can't change it; someone outside the group doesn't see it.
    jonas_view = (await jonas.get(f"{CATALOG}/entries", params={"level": "team"})).json()
    assert [item["registry_name"] for item in jonas_view] == ["team-data-search"]
    assert jonas_view[0]["editable"] is False
    assert (await lena.get(f"{CATALOG}/entries", params={"level": "team"})).json() == []
    assert (await lena.get(f"{CATALOG}/entries/{entry['id']}")).status_code == 404
    # Org owners see every team's entries.
    assert len((await owner.get(f"{CATALOG}/entries", params={"level": "team"})).json()) == 1

    by_member = await add(
        jonas, **{**SEARCH, "slug": "s2", "level": "team", "owner_group_id": group["id"], "instance_ids": [prod["id"]]}
    )
    assert by_member.status_code == 422
    other = (await owner.post("/api/v1/directory/groups", json={"name": "Ops"})).json()
    elsewhere = await add(
        maya, **{**SEARCH, "slug": "s3", "level": "team", "owner_group_id": other["id"], "instance_ids": [prod["id"]]}
    )
    assert elsewhere.status_code == 422

    # Tools that run commands on runtimes need the local scope, which only owners and administrators hold.
    shell = await add(
        maya, slug="shell", level="team", owner_group_id=group["id"], display_name="Shell", kind="toolkit",
        toolkit_key="shell", instance_ids=[prod["id"]],
    )  # fmt: skip
    assert shell.status_code == 403
    stdio = await add(
        owner, slug="files", level="org", display_name="Files", kind="mcp", transport="stdio",
        config={"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"]},
    )  # fmt: skip
    assert stdio.status_code == 201, stdio.text
    assert stdio.json()["local"] is True


async def test_custom_entries_are_made_for_one_instance(stack: Stack) -> None:
    owner = await stack.owner()
    await connect(owner, stack.runtime("prod.agentos.test"))
    custom = await add(owner, **{**SEARCH, "level": "custom", "instance_ids": ["prod-agentos"], "display_name": "Mine"})
    assert custom.status_code == 201, custom.text
    name = custom.json()["registry_name"]
    assert name.startswith("custom-")
    assert name.endswith("-search")
    assert custom.json()["level_label"] == "Custom"
    everywhere = await add(owner, **{**SEARCH, "slug": "x", "level": "custom"})
    assert everywhere.status_code == 422


async def test_the_bridge_pulls_its_instance_manifest_with_its_sync_token(stack: Stack) -> None:
    owner = await stack.owner()
    prod = await connect(owner, stack.runtime("prod.agentos.test"))
    staging = await connect(
        owner,
        stack.runtime("staging.agentos.test", os_id="fake-staging", name="Fake staging"),
        "http://staging.agentos.test:7777",
        display_name="staging-agentos",
        env_tag="staging",
    )
    assert (await add(owner, **LINEAR)).status_code == 201
    only_staging = await add(owner, **{**SEARCH, "instance_ids": [staging["id"]]})
    assert only_staging.status_code == 201

    issued = await owner.post(f"{CATALOG}/instances/{prod['id']}/sync-token")
    assert issued.status_code == 201, issued.text
    body = issued.json()
    assert body["env"]["AGNOSTIC_INSTANCE_ID"] == prod["id"]
    assert body["env"]["AGNOSTIC_TOOL_CATALOG_TOKEN"] == body["token"]

    bridge = stack.client()
    bridge.headers["Authorization"] = f"Bearer {body['token']}"
    bridge.headers["X-Agnostic-Bridge-Version"] = "0.2.0"
    pulled = await bridge.get(f"{CATALOG}/sync/{prod['id']}/manifest")
    assert pulled.status_code == 200, pulled.text
    manifest = pulled.json()
    assert manifest["instance_id"] == prod["id"]
    assert [item["name"] for item in manifest["entries"]] == ["org-linear"]  # the staging-only entry isn't here
    item = manifest["entries"][0]
    assert item["headers"]["Authorization"] == {"env": "LINEAR_TOKEN", "format": "Bearer {}"}
    assert item["revision"]

    again = await bridge.get(f"{CATALOG}/sync/{prod['id']}/manifest", headers={"If-None-Match": pulled.headers["etag"]})
    assert again.status_code == 304

    # The token is for this instance only, and for nothing else.
    assert (await bridge.get(f"{CATALOG}/sync/{staging['id']}/manifest")).status_code == 403
    assert (await bridge.get(f"{CATALOG}/entries")).status_code == 403

    status = (await owner.get(f"{CATALOG}/instances/{prod['id']}/status")).json()
    assert status["entries"] == 1
    assert status["bridge_version"] == "0.2.0"
    assert status["reachable"] is False

    # A new token replaces the old one.
    renewed = (await owner.post(f"{CATALOG}/instances/{prod['id']}/sync-token")).json()
    assert renewed["token"] != body["token"]
    assert (await bridge.get(f"{CATALOG}/sync/{prod['id']}/manifest")).status_code == 401


async def test_studio_marks_catalog_tools_and_lists_the_ones_not_loaded_yet(stack: Stack) -> None:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    assert (await add(owner, **LINEAR)).status_code == 201
    assert (await add(owner, **SEARCH)).status_code == 201
    fake.registry_items = [
        {
            "type": "tool",
            "name": "org-linear",
            "metadata": {"is_toolkit": True, "class_path": "agno.tools.mcp.MCPTools", "functions": []},
        }
    ]
    bridge_status(fake, [{"name": "org-linear", "state": "connected", "functions": ["org_linear_search"]}])

    registry = (await owner.get("/api/v1/instances/prod-agentos/studio/registry", params={"type": "tool"})).json()
    by_name = {entry["name"]: entry for entry in registry["entries"]}
    linear = by_name["org-linear"]
    assert linear["catalog"]["level_label"] == "Organization"
    assert linear["catalog"]["state"] == "connected"
    assert linear["studio_available"] is True
    search = by_name["org-search"]
    assert search["catalog"]["state"] == "not_on_instance"
    assert search["catalog"]["kind"] == "toolkit"
    assert search["studio_available"] is False


async def test_toolkits_lists_every_agno_toolkit(stack: Stack) -> None:
    owner = await stack.owner()
    body = (await owner.get(f"{CATALOG}/toolkits")).json()
    assert body["from_instance"] is False
    keys = {item["key"]: item for item in body["toolkits"]}
    assert len(keys) > 100
    assert keys["shell"]["local"] is True
    assert next(param for param in keys["github"]["params"] if param["name"] == "access_token")["secret"] is True
