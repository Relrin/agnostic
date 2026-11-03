"""Code sources against a fake Gitea and a real repository on disk: connect, scan and bind, a repository edit arriving
through a signed webhook as a draft next to Studio's, a publish written back as a pull request whose merge moves the
binding, publishing held until that merge, the same field edited in both places as a conflict resolved each way,
edits in different fields merging on their own, the sidebar's conflict count, and who may do what."""

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.api.test_instances_gateway import connect
from tests.support.fake_agentos import FakeAgentOS
from tests.support.fake_git_provider import TOKEN, FakeGitea
from tests.support.git_repo import Upstream, git_available
from tests.support.stack import Stack, running_stack

pytestmark = pytest.mark.skipif(not git_available(), reason="git isn't installed")

STAGING = "/api/v1/instances/staging-agentos"
SOURCES = f"{STAGING}/studio/sources"
COMPONENTS = f"{STAGING}/studio/components"

SUPPORT_TRIAGE = """from agno.agent import Agent

# Platform owns this agent; keep the instructions short.
support_triage = Agent(
    id="support-triage",
    name="support-triage",
    description="Triages incoming support tickets.",
    instructions=["Classify the ticket.", "Ask for the order number."],
    markdown=True,
)
"""

BILLING_AGENT = """from agno.agent import Agent

billing_agent = Agent(
    id="billing-agent",
    name="billing-agent",
    description="Handles billing questions.",
    instructions=[
        "Be brief.",
        "Quote the invoice number.",
        "Refunds over $100 need a manager.",
    ],
    markdown=True,
)
"""

TICKET_ROUTER = """from agno.workflow import Router, Step, Workflow

from app.agents import billing_agent, support_triage

ticket_router = Workflow(
    id="ticket-router",
    name="ticket-router",
    description="Triages a ticket and routes it.",
    steps=[
        Step(name="triage", agent=support_triage),
        Router(
            name="route",
            selector='input.contains("refund") ? "billing" : "triage-again"',
            choices=[
                Step(name="billing", agent=billing_agent),
                Step(name="triage-again", agent=support_triage),
            ],
        ),
    ],
)
"""

REGISTRY = '''"""Registry of the instance (read-only to Studio)."""
'''


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SOURCES__ALLOW_FILE_REMOTES", "true")
    monkeypatch.setenv("AGNOSTIC_SOURCES__MIRRORS_DIR", str(tmp_path / "mirrors"))
    monkeypatch.setenv("AGNOSTIC_SOURCES__FETCH_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SOURCES__PULL_REQUEST_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SOURCES__GC_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SOURCES__WATCH_LOCAL", "false")
    monkeypatch.setenv("AGNOSTIC_SOURCES__LOCAL_ROOTS", json.dumps([str(tmp_path / "local")]))
    async with running_stack(sqlite_database) as running:
        yield running


def registry() -> list[dict[str, Any]]:
    return [
        {"name": name, "id": name, "type": "agent", "metadata": {"class_path": "agno.agent.Agent"}}
        for name in ("support-triage", "billing-agent")
    ]


async def eventually[T](probe: Callable[[], Awaitable[T | None]], what: str, seconds: float = 30.0) -> T:
    """Background jobs (fetch, scan, commit) run on the embedded worker; wait until ``probe`` sees their result."""
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        found = await probe()
        if found:
            return found
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.1)


class World:
    """Staging with a Gitea connection and a source on ``northwind/agent-platform`` · main, scanned and bound."""

    def __init__(self, stack: Stack, owner: httpx.AsyncClient, staging: FakeAgentOS, upstream: Upstream) -> None:
        self.stack = stack
        self.owner = owner
        self.staging = staging
        self.upstream = upstream
        self.gitea = FakeGitea(upstream)
        stack.serve("gitea.test", self.gitea.app)
        self.source_id = ""

    @property
    def source(self) -> str:
        return f"{SOURCES}/{self.source_id}"

    async def changes(self) -> dict[str, Any]:
        response = await self.owner.get(f"{self.source}/changes")
        assert response.status_code == 200, response.text
        return response.json()

    async def incoming_for(self, component_id: str, *, commit: str | None = None) -> dict[str, Any] | None:
        for change in (await self.changes())["incoming"]:
            if change["component_id"] == component_id and (commit is None or change["commit_sha"] == commit):
                return change
        return None

    async def pull(self, *change_ids: str) -> list[dict[str, Any]]:
        response = await self.owner.post(f"{self.source}/pull", json={"change_ids": list(change_ids)})
        assert response.status_code == 200, response.text
        return response.json()

    async def config(self, component_id: str, version: int) -> dict[str, Any]:
        return (await self.owner.get(f"{COMPONENTS}/{component_id}/configs/{version}")).json()

    async def save_draft(self, component_id: str, version: int, change: Callable[[dict[str, Any]], None]) -> None:
        detail = (await self.owner.get(f"{COMPONENTS}/{component_id}")).json()
        config = copy.deepcopy((await self.config(component_id, version))["config"])
        change(config)
        saved = await self.owner.patch(
            f"{COMPONENTS}/{component_id}/configs/{version}",
            json={"config": config, "revision": detail["draft"]["revision"]},
        )
        assert saved.status_code == 200, saved.text

    async def publish(self, component_id: str, version: int) -> httpx.Response:
        return await self.owner.post(f"{COMPONENTS}/{component_id}/configs/{version}/publish", json={})

    async def webhook(self, delivery: tuple[bytes, dict[str, str]]) -> httpx.Response:
        body, headers = delivery
        return await self.stack.client().post("/hooks/gitea", content=body, headers=headers)

    async def component_source(self, component_id: str) -> dict[str, Any]:
        return (await self.owner.get(f"{COMPONENTS}/{component_id}/source")).json()


async def world(stack: Stack, tmp_path: Path) -> World:
    owner = await stack.owner()
    staging = stack.runtime("staging.agentos.test", os_id="fake-staging", name="Fake staging")
    await connect(owner, staging, "http://staging.agentos.test:7777", display_name="staging-agentos", env_tag="staging")
    staging.registry_items = registry()
    upstream = Upstream(tmp_path / "repo")
    _ = upstream.commit(
        {
            "agents/support_triage.py": SUPPORT_TRIAGE,
            "agents/billing_agent.py": BILLING_AGENT,
            "workflows/ticket_router.py": TICKET_ROUTER,
            "registry.py": REGISTRY,
            "tests/test_smoke.py": "def test_nothing() -> None:\n    pass\n",
        },
        "Agents, teams and workflows",
        author=("Lena Ito", "lena@northwind.test"),
    )
    here = World(stack, owner, staging, upstream)
    created = await owner.post(
        "/api/v1/studio/connections",
        json={"name": "Northwind Gitea", "provider": "gitea", "web_url": "http://gitea.test", "token": TOKEN},
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "verified"
    assert created.json()["account"] == "agnostic-bot"
    connection_id = created.json()["id"]
    repos = (await owner.get(f"/api/v1/studio/connections/{connection_id}/repos")).json()
    assert [repo["full_name"] for repo in repos] == ["northwind/agent-platform"]
    source = await owner.post(
        SOURCES,
        json={
            "provider": "gitea",
            "connection_id": connection_id,
            "repo": "northwind/agent-platform",
            "branch": "main",
            "clone_url": upstream.url,
        },
    )
    assert source.status_code == 201, source.text
    here.source_id = source.json()["id"]
    return here


async def bound(stack: Stack, tmp_path: Path) -> World:
    """Scanned, activated, and every file pulled as draft v1 of its component."""
    here = await world(stack, tmp_path)

    async def scanned() -> dict[str, Any] | None:
        report = (await here.owner.get(f"{here.source}/scan")).json()
        return report if report["status"] == "ready" else None

    report = (await eventually(scanned, "the initial scan"))["report"]
    files = {entry["path"]: entry for entry in report["files"]}
    assert set(files) == {
        "agents/support_triage.py",
        "agents/billing_agent.py",
        "workflows/ticket_router.py",
        "registry.py",
    }
    assert files["registry.py"]["mapping"] == "registry"
    assert files["agents/support_triage.py"]["components"][0] | {"diagnostics": []} == {
        "variable": "support_triage",
        "kind": "agent",
        "id": "support-triage",
        "parse": "ok",
        "diagnostics": [],
        "code_owned": [],
        "match": "new",
        "proposed": "create",
    }
    activated = await here.owner.post(f"{here.source}/activate", json={})
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
    assert activated.json()["webhook"] is True
    assert here.gitea.hooks["1"]["config"]["url"] == "http://agnostic.test/hooks/gitea"

    async def three() -> list[dict[str, Any]] | None:
        incoming = (await here.changes())["incoming"]
        return incoming if len(incoming) == 3 else None

    incoming = await eventually(three, "the files as incoming changes")
    sentences = {change["component_id"]: change["outcome_sentence"] for change in incoming}
    assert sentences["ticket-router"] == "Creates ticket-router as a new workflow (draft v1)"
    pulled = await here.pull(*(change["id"] for change in incoming))
    assert {result["component_id"]: (result["version"], result["error"]) for result in pulled} == {
        "support-triage": (1, None),
        "billing-agent": (1, None),
        "ticket-router": (1, None),
    }
    assert (await here.changes())["incoming"] == []
    return here


async def test_a_repository_edit_arrives_through_the_webhook_as_a_draft_next_to_studios(
    stack: Stack, tmp_path: Path
) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("ticket-router", 1, lambda config: config.update(description="Routes tickets."))
    before = here.upstream.head()
    after = here.upstream.commit(
        {
            "workflows/ticket_router.py": TICKET_ROUTER.replace(
                'input.contains("refund") ?', 'input.contains("refund") || input.contains("outage") ?'
            )
        },
        "Route outage tickets to on-call",
    )
    rejected = await here.webhook(here.gitea.delivery("push", {"ref": "refs/heads/main"}, secret="wrong"))
    assert rejected.status_code == 401
    delivery = here.gitea.push(before, after)
    accepted = await here.webhook(delivery)
    assert accepted.status_code == 202, accepted.text
    again = await here.webhook(delivery)
    assert again.status_code == 202

    change = await eventually(lambda: here.incoming_for("ticket-router", commit=after), "the pushed change")
    assert change["outcome_sentence"] == "Becomes draft v2 of ticket-router, next to your draft v1"
    assert change["outcome"]["auto_merged"] == ["description"]
    assert (change["author_name"], change["message"]) == ("Sam Rivera", "Route outage tickets to on-call")
    assert (change["additions"], change["deletions"]) == (1, 1)
    deliveries = (await here.owner.get(f"{here.source}/deliveries")).json()
    assert len(deliveries) == 1

    [result] = await here.pull(change["id"])
    assert (result["version"], result["error"]) == (2, None)
    draft = await here.config("ticket-router", 2)
    assert draft["stage"] == "draft"
    assert draft["config"]["description"] == "Routes tickets."
    assert "outage" in draft["config"]["steps"][1]["selector"]
    document = (await here.owner.get(f"{COMPONENTS}/ticket-router/configs/2/code")).json()
    assert document["code_backed"] is True
    assert 'description="Routes tickets."' in document["code"]
    bar = await here.component_source("ticket-router")
    assert (bar["bound"], bar["path"], bar["marks_version"]) == (True, "workflows/ticket_router.py", 2)
    assert set(bar["incoming_marks"].values()) == {"incoming"}
    assert bar["incoming"] == []


async def test_a_publish_opens_a_pull_request_whose_merge_moves_the_binding(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    published = await here.publish("support-triage", 1)
    assert published.status_code == 200, published.text
    drafted = await here.owner.post(f"{COMPONENTS}/support-triage/configs", json={})
    assert drafted.status_code == 201, drafted.text
    await here.save_draft(
        "support-triage", 2, lambda config: config["instructions"].append("Offer a refund for late orders.")
    )
    check = (await here.owner.get(f"{COMPONENTS}/support-triage/publish-check", params={"version": 2})).json()
    assert check["hold"]["write_back"] == "Opens a pull request studio/support-triage-v2 into main"
    assert (await here.publish("support-triage", 2)).status_code == 200

    pull = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(1)), "the pull request")
    assert pull.head == "studio/support-triage-v2"
    assert pull.title == "support-triage: one new instruction"
    written = here.upstream.read("agents/support_triage.py", "studio/support-triage-v2")
    assert "# Platform owns this agent; keep the instructions short." in written
    assert "Offer a refund for late orders." in written
    tracked = (await here.changes())["pull_requests"]
    assert (tracked[0]["number"], tracked[0]["status"]) == (1, "open")
    assert tracked[0]["review_requirement"] == "1 review from Platform required"

    merge = here.gitea.merge(1)
    assert (await here.webhook(here.gitea.pull_merged(1))).status_code == 202

    async def synced() -> dict[str, Any] | None:
        bar = await here.component_source("support-triage")
        return bar if bar["synced_version"] == 2 and bar["synced_sha"] == merge else None

    bar = await eventually(synced, "the binding to move to the merge")
    assert bar["incoming"] == []
    assert bar["uncommitted"] is None
    assert (await here.changes())["pull_requests"][0]["status"] == "merged"


async def test_publishing_waits_for_the_pull_request_when_the_policy_says_so(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    source = (await here.owner.get(here.source)).json()
    policy = {**source["policy"], "block_publish_until_merged": True}
    patched = await here.owner.patch(here.source, json={"policy": policy, "version": source["version"]})
    assert patched.status_code == 200, patched.text
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))

    check = (await here.owner.get(f"{COMPONENTS}/support-triage/publish-check", params={"version": 1})).json()
    assert check["hold"]["held"] is True
    assert check["can_publish"] is False
    held = await here.publish("support-triage", 1)
    assert held.status_code == 409
    assert held.json()["code"] == "publish_held"

    outgoing = (await here.owner.post(f"{here.source}/outgoing/refresh")).json()
    [change] = [item for item in outgoing if item["component_id"] == "support-triage"]
    assert change["summary"] == "description “Triages incoming support tickets.” → “Sorts tickets.”"
    preview = (await here.owner.get(f"{here.source}/commit-preview", params={"change_ids": change["id"]})).json()
    assert preview["sentence"] == "Branch studio/support-triage-v1 · PR into main · 1 review from Platform required"
    committed = await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})
    assert committed.status_code == 202, committed.text
    _ = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(1)), "the pull request")

    check = (await here.owner.get(f"{COMPONENTS}/support-triage/publish-check", params={"version": 1})).json()
    assert check["hold"]["reason"] == "Waiting for PR #1 to merge · 1 review from Platform required"
    _ = here.gitea.merge(1)
    assert (await here.webhook(here.gitea.pull_merged(1))).status_code == 202

    async def released() -> dict[str, Any] | None:
        found = (await here.owner.get(f"{COMPONENTS}/support-triage/publish-check", params={"version": 1})).json()
        return found if not found["hold"]["held"] else None

    _ = await eventually(released, "the hold to clear")
    assert (await here.publish("support-triage", 1)).status_code == 200


@pytest.mark.parametrize(
    ("resolution", "value", "expected"),
    [
        ("keep_studio", None, "Refunds over $150 need a manager."),
        ("keep_repo", None, "Refunds over $200 need a manager."),
        ("merged", "Refunds over $175 need a manager.", "Refunds over $175 need a manager."),
    ],
)
async def test_the_same_field_edited_in_both_places_is_a_conflict(
    stack: Stack, tmp_path: Path, resolution: str, value: str | None, expected: str
) -> None:
    here = await bound(stack, tmp_path)

    def studio_edit(config: dict[str, Any]) -> None:
        config["instructions"][2] = "Refunds over $150 need a manager."

    await here.save_draft("billing-agent", 1, studio_edit)
    repo_edit = BILLING_AGENT.replace("$100", "$200").replace("Handles billing questions.", "Billing and refunds.")
    head = here.upstream.commit({"agents/billing_agent.py": repo_edit}, "Raise the refund limit")
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202

    change = await eventually(lambda: here.incoming_for("billing-agent", commit=head), "the conflicting change")
    assert change["outcome_sentence"] == "Conflicts with your draft v1 on instructions[2]"
    [conflict] = (await here.changes())["conflicts"]
    assert conflict["field_path"] == "instructions[2]"
    assert (conflict["repo"]["value"], conflict["repo"]["author"]) == (
        "Refunds over $200 need a manager.",
        "Sam Rivera",
    )
    assert (conflict["studio"]["value"], conflict["studio"]["reference"]) == (
        "Refunds over $150 need a manager.",
        "draft v1",
    )
    assert (await here.owner.get(f"{SOURCES}/conflicts/count")).json()["count"] == 1
    [refused] = await here.pull(change["id"])
    assert refused["error"] == "Resolve the conflict on instructions[2] first."

    resolved = await here.owner.post(
        f"{here.source}/conflicts/{conflict['id']}/resolve", json={"resolution": resolution, "value": value}
    )
    assert resolved.status_code == 200, resolved.text
    assert (await here.owner.get(f"{SOURCES}/conflicts/count")).json()["count"] == 0
    [result] = await here.pull(change["id"])
    assert (result["version"], result["error"]) == (2, None)
    draft = (await here.config("billing-agent", 2))["config"]
    assert draft["instructions"][2] == expected
    assert draft["description"] == "Billing and refunds."
    events = (await here.owner.get("/api/v1/audit/events", params={"action": "sources.conflict.resolve"})).json()
    assert len(events["data"]) == 1


async def test_edits_in_different_fields_merge_on_their_own(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("billing-agent", 1, lambda config: config.update(description="Billing, briefly."))
    edited = BILLING_AGENT.replace(
        '        "Refunds over $100 need a manager.",\n',
        '        "Refunds over $100 need a manager.",\n        "Never promise a date.",\n',
    )
    head = here.upstream.commit({"agents/billing_agent.py": edited}, "One more rule")
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202
    change = await eventually(lambda: here.incoming_for("billing-agent", commit=head), "the change")
    assert change["outcome"]["action"] == "new_draft"
    assert change["outcome"]["auto_merged"] == ["description"]
    assert (await here.changes())["conflicts"] == []
    [result] = await here.pull(change["id"])
    draft = (await here.config("billing-agent", result["version"]))["config"]
    assert draft["description"] == "Billing, briefly."
    assert draft["instructions"][-1] == "Never promise a date."


async def test_who_may_do_what(stack: Stack, tmp_path: Path) -> None:
    here = await world(stack, tmp_path)
    anonymous = stack.client()
    assert (await anonymous.get(SOURCES)).status_code == 401
    assert (await anonymous.post("/hooks/gitea", content=b"{}")).status_code == 401
    local = await here.owner.post(SOURCES, json={"provider": "local", "local_path": str(tmp_path)})
    assert local.status_code == 422
    assert "Local folders" in local.text
    listed = (await here.owner.get(SOURCES)).json()
    assert [(item["provider_label"], item["repo"], item["auth"]) for item in listed] == [
        ("Gitea", "northwind/agent-platform", "Token · read & write")
    ]


async def test_a_local_folder_syncs_with_a_development_instance(stack: Stack, tmp_path: Path) -> None:
    owner = await stack.owner()
    dev = stack.runtime("dev.agentos.test", os_id="fake-dev", name="Fake dev")
    await connect(owner, dev, "http://dev.agentos.test:7777", display_name="dev-agentos", env_tag="development")
    folder = tmp_path / "local" / "app"
    (folder / "agents").mkdir(parents=True)
    (folder / "agents" / "support_triage.py").write_text(SUPPORT_TRIAGE, encoding="utf-8")
    sources = "/api/v1/instances/dev-agentos/studio/sources"
    components = "/api/v1/instances/dev-agentos/studio/components"
    outside = await owner.post(sources, json={"provider": "local", "local_path": str(tmp_path)})
    assert outside.status_code == 422
    created = await owner.post(sources, json={"provider": "local", "local_path": str(folder)})
    assert created.status_code == 201, created.text
    source = f"{sources}/{created.json()['id']}"
    assert created.json()["auth"] == "Local folder · writes go straight to disk"

    async def scanned() -> dict[str, Any] | None:
        report = (await owner.get(f"{source}/scan")).json()
        return report if report["status"] == "ready" else None

    _ = await eventually(scanned, "the scan")
    assert (await owner.post(f"{source}/activate", json={})).status_code == 200

    async def incoming() -> list[dict[str, Any]] | None:
        return (await owner.get(f"{source}/changes")).json()["incoming"] or None

    [change] = await eventually(incoming, "the folder's agent")
    pulled = (await owner.post(f"{source}/pull", json={"change_ids": [change["id"]]})).json()
    assert pulled[0]["version"] == 1
    assert (await owner.post(f"{components}/support-triage/configs/1/publish", json={})).status_code == 200
    assert (await owner.post(f"{components}/support-triage/configs", json={})).status_code == 201
    detail = (await owner.get(f"{components}/support-triage")).json()
    config = copy.deepcopy((await owner.get(f"{components}/support-triage/configs/2")).json()["config"])
    config["instructions"].append("Thank the customer.")
    saved = await owner.patch(
        f"{components}/support-triage/configs/2", json={"config": config, "revision": detail["draft"]["revision"]}
    )
    assert saved.status_code == 200, saved.text
    check = (await owner.get(f"{components}/support-triage/publish-check", params={"version": 2})).json()
    assert check["hold"]["write_back"] == "Writes agents/support_triage.py in the folder; the runtime reloads it"
    assert (await owner.post(f"{components}/support-triage/configs/2/publish", json={})).status_code == 200

    async def written() -> str | None:
        text = (folder / "agents" / "support_triage.py").read_text(encoding="utf-8")
        return text if "Thank the customer." in text else None

    text = await eventually(written, "the publish written to disk")
    assert "# Platform owns this agent; keep the instructions short." in text

    async def synced() -> dict[str, Any] | None:
        bar = (await owner.get(f"{components}/support-triage/source")).json()
        return bar if bar["synced_version"] == 2 else None

    _ = await eventually(synced, "the binding to follow the folder")
