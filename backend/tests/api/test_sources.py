"""Code sources against a fake Gitea and a real repository on disk: connect, scan and bind, a repository edit arriving
through a signed webhook as a draft next to Studio's, a publish written back as a pull request whose merge moves the
binding, publishing held until that merge, the same field edited in both places as a conflict resolved each way,
edits in different fields merging on their own, the sidebar's conflict count, who may do what, a pull request retried
on the branch it pushed after it failed to open, the status a source returns to after a failed fetch or scan,
read-only and deploy-key connections, connection updates, a local write refused when the file changed on disk, and
the changed-files limit."""

import asyncio
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agnostic_sources.application import sync
from agnostic_sources.application.tasks import SourceJobs
from agnostic_sources.infrastructure import local_folders
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


def configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[Stack]:
    configure(monkeypatch, tmp_path)
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


async def world(stack: Stack, tmp_path: Path, *, access: str = "read_write", fail_scan: bool = False) -> World:
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
        json={
            "name": "Northwind Gitea",
            "provider": "gitea",
            "web_url": "http://gitea.test",
            "token": TOKEN,
            "access": access,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "verified"
    assert created.json()["account"] == "agnostic-bot"
    connection_id = created.json()["id"]
    repos = (await owner.get(f"/api/v1/studio/connections/{connection_id}/repos")).json()
    assert [repo["full_name"] for repo in repos] == ["northwind/agent-platform"]
    here.gitea.refuse_token = fail_scan
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


async def bound(stack: Stack, tmp_path: Path, *, access: str = "read_write") -> World:
    """Scanned, activated, and every file pulled as draft v1 of its component."""
    here = await world(stack, tmp_path, access=access)

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
    assert here.gitea.hooks["1"]["config"]["url"] == f"http://agnostic.test/hooks/gitea?source={here.source_id}"

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


async def test_mappings_that_miss_every_file_say_so_and_a_fixed_mapping_scans_again(
    stack: Stack, tmp_path: Path
) -> None:
    owner = await stack.owner()
    dev = stack.runtime("dev.agentos.test", os_id="fake-dev", name="Fake dev")
    await connect(owner, dev, "http://dev.agentos.test:7777", display_name="dev-agentos", env_tag="development")
    # The package sits one folder below the source's root, so the default `agents/*.py` takes nothing.
    folder = tmp_path / "local" / "share"
    (folder / "agno_app" / "agents").mkdir(parents=True)
    (folder / "agno_app" / "agents" / "support_triage.py").write_text(SUPPORT_TRIAGE, encoding="utf-8")
    sources = "/api/v1/instances/dev-agentos/studio/sources"
    convention = {"registry_module": "agno_app.registry", "agents_module": "agno_app.agents"}
    created = await owner.post(sources, json={"provider": "local", "local_path": str(folder), "convention": convention})
    assert created.status_code == 201, created.text
    source = f"{sources}/{created.json()['id']}"
    assert created.json()["convention"]["agents_module"] == "agno_app.agents"

    async def scanned() -> dict[str, Any] | None:
        report = (await owner.get(f"{source}/scan")).json()
        return report if report["status"] == "ready" else None

    report = (await eventually(scanned, "the scan"))["report"]
    assert report["files"] == []
    assert (report["listed"], report["unmapped"]) == (1, ["agno_app/agents/support_triage.py"])
    refused = await owner.post(f"{source}/activate", json={})
    assert refused.status_code == 409
    assert "matches the path mappings" in refused.json()["detail"]

    card = (await owner.get(source)).json()
    mappings = [{"glob": "agno_app/agents/*.py", "target_kind": "agents", "writable": True}]
    patched = await owner.patch(source, json={"mappings": mappings, "version": card["version"]})
    assert patched.status_code == 200, patched.text

    async def rescanned() -> dict[str, Any] | None:
        again = (await owner.get(f"{source}/scan")).json()
        return again if again["status"] == "ready" and again["report"]["files"] else None

    again = (await eventually(rescanned, "the scan with the fixed mapping"))["report"]
    assert [entry["path"] for entry in again["files"]] == ["agno_app/agents/support_triage.py"]
    assert again["unmapped"] == []
    activated = await owner.post(f"{source}/activate", json={})
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"


async def test_a_bound_file_the_folder_listing_left_out_is_not_removed(
    stack: Stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await stack.owner()
    dev = stack.runtime("dev.agentos.test", os_id="fake-dev", name="Fake dev")
    await connect(owner, dev, "http://dev.agentos.test:7777", display_name="dev-agentos", env_tag="development")
    folder = tmp_path / "local" / "app"
    (folder / "agents").mkdir(parents=True)
    (folder / "agents" / "support_triage.py").write_text(SUPPORT_TRIAGE, encoding="utf-8")
    sources = "/api/v1/instances/dev-agentos/studio/sources"
    created = await owner.post(sources, json={"provider": "local", "local_path": str(folder)})
    assert created.status_code == 201, created.text
    source = f"{sources}/{created.json()['id']}"

    async def scanned() -> dict[str, Any] | None:
        report = (await owner.get(f"{source}/scan")).json()
        return report if report["status"] == "ready" else None

    _ = await eventually(scanned, "the scan")
    assert (await owner.post(f"{source}/activate", json={})).status_code == 200

    async def incoming() -> list[dict[str, Any]] | None:
        return (await owner.get(f"{source}/changes")).json()["incoming"] or None

    [change] = await eventually(incoming, "the folder's agent")
    assert (await owner.post(f"{source}/pull", json={"change_ids": [change["id"]]})).status_code == 200

    # The listing now stops after one file, before it reaches agents/.
    monkeypatch.setattr(local_folders, "MAX_FOLDER_FILES", 1)
    monkeypatch.setattr(sync, "MAX_FOLDER_FILES", 1)
    (folder / "README.md").write_text("# app", encoding="utf-8")
    before = (await owner.get(source)).json()["last_fetched_at"]
    assert (await owner.post(f"{source}/fetch")).status_code == 202

    async def fetched() -> dict[str, Any] | None:
        card = (await owner.get(source)).json()
        return card if card["last_fetched_at"] != before else None

    _ = await eventually(fetched, "the fetch")
    changes = (await owner.get(f"{source}/changes")).json()
    assert [item for item in changes["incoming"] if item["outcome"].get("action") == "removed"] == []


# ---------------------------------------------------------------- failures, retries, limits and connection rules


async def outgoing_for(here: World, component_id: str) -> dict[str, Any]:
    outgoing = (await here.owner.post(f"{here.source}/outgoing/refresh")).json()
    [change] = [item for item in outgoing if item["component_id"] == component_id]
    return change


async def change_status(here: World, change_id: str, status: str) -> dict[str, Any] | None:
    for change in (await here.changes())["outgoing"]:
        if change["id"] == change_id and change["status"] == status:
            return change
    return None


async def source_status(owner: httpx.AsyncClient, source: str, status: str) -> dict[str, Any] | None:
    card = (await owner.get(source)).json()
    return card if card["status"] == status else None


async def fetched(here: World, head: str) -> None:
    """Fetch now and wait until the source has read ``head``."""
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202

    async def done() -> dict[str, Any] | None:
        card = (await here.owner.get(here.source)).json()
        return card if card["head_sha"] == head else None

    _ = await eventually(done, f"the fetch of {head[:7]}")


async def test_a_draft_edited_after_the_fetch_turns_the_change_into_a_conflict_on_the_next_fetch(
    stack: Stack, tmp_path: Path
) -> None:
    here = await bound(stack, tmp_path)
    head = here.upstream.commit(
        {"agents/support_triage.py": SUPPORT_TRIAGE.replace("Triages incoming", "Sorts incoming")}, "Reword"
    )
    await fetched(here, head)
    change = await eventually(lambda: here.incoming_for("support-triage", commit=head), "the repository's edit")
    assert change["outcome"]["action"] == "new_draft"
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Studio's words."))

    [refused] = await here.pull(change["id"])
    assert refused["version"] is None
    assert "fetch again" in refused["error"]

    await fetched(here, head)

    async def conflict() -> dict[str, Any] | None:
        found = await here.incoming_for("support-triage", commit=head)
        return found if found and found["outcome"]["action"] == "conflict" else None

    again = await eventually(conflict, "the change worked out again")
    assert again["id"] != change["id"]
    assert again["outcome"]["conflict_paths"] == ["description"]


async def test_a_version_in_an_open_pull_request_is_not_offered_again(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    change = await outgoing_for(here, "support-triage")
    assert (await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})).status_code == 202
    _ = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(1)), "the pull request")

    outgoing = (await here.owner.post(f"{here.source}/outgoing/refresh")).json()
    assert [item for item in outgoing if item["component_id"] == "support-triage"] == []
    assert len(here.gitea.pulls) == 1


async def test_two_pulls_of_one_change_make_one_draft(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    head = here.upstream.commit(
        {"agents/support_triage.py": SUPPORT_TRIAGE.replace("Triages incoming", "Sorts incoming")}, "Reword"
    )
    await fetched(here, head)
    change = await eventually(lambda: here.incoming_for("support-triage", commit=head), "the repository's edit")
    first, second = await asyncio.gather(here.pull(change["id"]), here.pull(change["id"]))
    versions = sorted(result["version"] or 0 for result in (*first, *second))
    assert versions == [0, 2], "one pull makes draft v2, the other is told it's taken"
    detail = (await here.owner.get(f"{COMPONENTS}/support-triage")).json()
    assert detail["draft"]["version"] == 2


async def test_a_renamed_file_moves_its_binding(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    head = here.upstream.commit(
        {"agents/support_triage.py": None, "agents/triage.py": SUPPORT_TRIAGE}, "Shorter file name"
    )
    await fetched(here, head)

    async def moved() -> dict[str, Any] | None:
        bar = await here.component_source("support-triage")
        return bar if bar["path"] == "agents/triage.py" else None

    _ = await eventually(moved, "the binding to follow the file")
    assert await here.incoming_for("support-triage") is None, "nothing to pull: the file only moved"
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    change = await outgoing_for(here, "support-triage")
    assert (change["path"], change["outcome"]["action"]) == ("agents/triage.py", "edit")


async def test_a_renamed_and_edited_file_moves_its_binding_once_pulled(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    head = here.upstream.commit(
        {
            "agents/support_triage.py": None,
            "agents/triage.py": SUPPORT_TRIAGE.replace("Triages incoming", "Sorts incoming"),
        },
        "Rename and reword",
    )
    await fetched(here, head)
    change = await eventually(lambda: here.incoming_for("support-triage", commit=head), "the edit at the new path")
    assert change["path"] == "agents/triage.py"
    assert [item["path"] for item in (await here.changes())["incoming"]] == ["agents/triage.py"]
    [result] = await here.pull(change["id"])
    assert (result["version"], result["error"]) == (2, None)
    await here.save_draft("support-triage", 2, lambda config: config.update(description="Sorts every ticket."))
    outgoing = (await here.owner.post(f"{here.source}/outgoing/refresh")).json()
    assert [item["path"] for item in outgoing if item["component_id"] == "support-triage"] == ["agents/triage.py"]


async def test_a_removed_file_can_be_written_again_or_stop_syncing(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    head = here.upstream.commit({"agents/billing_agent.py": None}, "Billing moves to another repo")
    await fetched(here, head)
    removed = await eventually(lambda: here.incoming_for("billing-agent"), "the removal")
    assert removed["outcome"]["action"] == "removed"

    # Studio's side still goes out: committing writes the file again.
    await here.save_draft("billing-agent", 1, lambda config: config.update(description="Bills."))
    change = await outgoing_for(here, "billing-agent")
    assert change["outcome"]["action"] != "blocked"

    # Or the removal is accepted: the file stops being synced, the component stays.
    [result] = await here.pull(removed["id"])
    assert (result["version"], result["error"]) == (None, None)
    assert (await here.component_source("billing-agent"))["bound"] is False
    assert (await here.owner.get(f"{COMPONENTS}/billing-agent")).status_code == 200
    assert await here.incoming_for("billing-agent") is None
    outgoing = (await here.owner.post(f"{here.source}/outgoing/refresh")).json()
    assert [item for item in outgoing if item["component_id"] == "billing-agent"] == []


async def test_activating_after_a_newer_fetch_keeps_the_repositorys_edit_incoming(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    upstream = Upstream(tmp_path / "second", branch="release")
    _ = upstream.commit({"agents/support_triage.py": SUPPORT_TRIAGE}, "The same agent on the release branch")
    connection_id = (await here.owner.get(here.source)).json()["connection_id"]
    created = await here.owner.post(
        SOURCES,
        json={
            "provider": "gitea",
            "connection_id": connection_id,
            "repo": "northwind/agent-platform",
            "branch": "release",
            "clone_url": upstream.url,
        },
    )
    assert created.status_code == 201, created.text
    second = f"{SOURCES}/{created.json()['id']}"

    async def scanned() -> dict[str, Any] | None:
        report = (await here.owner.get(f"{second}/scan")).json()
        return report if report["status"] == "ready" else None

    report = (await eventually(scanned, "the scan"))["report"]
    [entry] = [item for item in report["files"] if item["path"] == "agents/support_triage.py"]
    assert entry["components"][0]["match"] == "same"

    head = upstream.commit(
        {"agents/support_triage.py": SUPPORT_TRIAGE.replace("Triages incoming", "Sorts incoming")}, "Reword"
    )
    assert (await here.owner.post(f"{second}/fetch")).status_code == 202

    async def read() -> dict[str, Any] | None:
        card = (await here.owner.get(second)).json()
        return card if card["head_sha"] == head else None

    _ = await eventually(read, "the fetch before activating")
    assert (await here.owner.post(f"{second}/activate", json={})).status_code == 200

    async def incoming() -> list[dict[str, Any]] | None:
        return (await here.owner.get(f"{second}/changes")).json()["incoming"] or None

    [change] = await eventually(incoming, "the edit made after the scan")
    assert (change["component_id"], change["commit_sha"]) == ("support-triage", head)


async def test_a_published_version_that_never_reached_the_file_is_merged_not_overwritten(
    stack: Stack, tmp_path: Path
) -> None:
    here = await bound(stack, tmp_path)
    patched = await here.owner.patch(here.source, json={"policy": {"publish_mode": "no_write_back"}})
    assert patched.status_code == 200, patched.text
    assert (await here.publish("support-triage", 1)).status_code == 200
    assert (await here.owner.post(f"{COMPONENTS}/support-triage/configs", json={})).status_code == 201
    await here.save_draft("support-triage", 2, lambda config: config.update(description="Sorts tickets."))
    assert (await here.publish("support-triage", 2)).status_code == 200

    head = here.upstream.commit(
        {"agents/support_triage.py": SUPPORT_TRIAGE.replace('"Ask for the order number."', '"Ask for the order id."')},
        "Wording",
    )
    await fetched(here, head)
    change = await eventually(lambda: here.incoming_for("support-triage", commit=head), "the repository's edit")
    assert change["outcome"]["auto_merged"] == ["description"]
    [result] = await here.pull(change["id"])
    assert (result["version"], result["error"]) == (3, None)
    config = (await here.config("support-triage", 3))["config"]
    assert config["description"] == "Sorts tickets.", "v2's change survives"
    assert "Ask for the order id." in config["instructions"]


async def test_a_closed_pull_request_gives_back_only_its_own_changes(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    first = await outgoing_for(here, "support-triage")
    assert (await here.owner.post(f"{here.source}/commit", json={"change_ids": [first["id"]]})).status_code == 202
    _ = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(1)), "the first pull request")
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts every ticket."))
    second = await outgoing_for(here, "support-triage")
    assert (await here.owner.post(f"{here.source}/commit", json={"change_ids": [second["id"]]})).status_code == 202
    _ = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(2)), "the second pull request")

    here.gitea.close(1)
    assert (await here.webhook(here.gitea.pull_merged(1))).status_code == 202
    _ = await eventually(lambda: change_status(here, first["id"], "pending"), "the closed one to give back")
    pending = [change["id"] for change in (await here.changes())["outgoing"] if change["status"] == "pending"]
    assert pending == [first["id"]], "the change in the open pull request stays committed"


async def test_a_pull_request_that_failed_to_open_is_retried_on_the_branch_it_pushed(
    stack: Stack, tmp_path: Path
) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    change = await outgoing_for(here, "support-triage")
    here.gitea.fail_pulls = 1
    first = await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})
    assert first.status_code == 202, first.text
    failed = await eventually(lambda: change_status(here, change["id"], "pending"), "the failed commit to give back")
    assert failed["outcome"]["commit_error"], "the reason is kept for the people who asked for the commit"
    assert "studio/support-triage-v1" in here.upstream.branches(), "the push went through before the PR failed"
    assert here.gitea.pulls == {}

    preview = (await here.owner.get(f"{here.source}/commit-preview", params={"change_ids": change["id"]})).json()
    assert preview["branch"] == "studio/support-triage-v1", "the branch left behind is used again, not -2, -3, ..."
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts every ticket."))
    again = await outgoing_for(here, "support-triage")
    assert again["id"] != change["id"]
    retried = await here.owner.post(f"{here.source}/commit", json={"change_ids": [again["id"]]})
    assert retried.status_code == 202, retried.text
    pull = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(1)), "the pull request")
    assert pull.head == "studio/support-triage-v1"
    assert [(item["branch"], item["status"]) for item in (await here.changes())["pull_requests"]] == [
        ("studio/support-triage-v1", "open")
    ]
    assert sorted(here.upstream.branches()) == ["main", "studio/support-triage-v1"]
    assert 'description="Sorts every ticket."' in here.upstream.read(
        "agents/support_triage.py", "studio/support-triage-v1"
    )


async def test_a_retry_moves_to_a_new_branch_once_someone_else_pushed_to_the_old_one(
    stack: Stack, tmp_path: Path
) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    change = await outgoing_for(here, "support-triage")
    here.gitea.fail_pulls = 1
    first = await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})
    assert first.status_code == 202, first.text
    _ = await eventually(lambda: change_status(here, change["id"], "pending"), "the failed commit to give back")
    here.upstream.move("studio/support-triage-v1", here.upstream.head())

    rejected = await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})
    assert rejected.status_code == 202, rejected.text
    _ = await eventually(lambda: change_status(here, change["id"], "pending"), "the rejected push to give back")
    assert here.upstream.head("studio/support-triage-v1") == here.upstream.head(), "the other push is kept"

    preview = (await here.owner.get(f"{here.source}/commit-preview", params={"change_ids": change["id"]})).json()
    assert preview["branch"] == "studio/support-triage-v1-2", "the branch someone else pushed to is left alone"
    retried = await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})
    assert retried.status_code == 202, retried.text
    pull = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(1)), "the pull request")
    assert pull.head == "studio/support-triage-v1-2"


async def test_a_commit_preview_says_when_the_remote_branches_cant_be_listed(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    change = await outgoing_for(here, "support-triage")
    here.gitea.refuse_token = True
    preview = await here.owner.get(f"{here.source}/commit-preview", params={"change_ids": change["id"]})
    assert preview.status_code == 502
    assert "Couldn't list the branches of northwind/agent-platform" in preview.json()["detail"]


async def test_a_config_edit_of_a_code_backed_draft_writes_the_new_value(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path)
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    document = (await here.owner.get(f"{COMPONENTS}/support-triage/configs/1/code")).json()
    assert document["stale"] is True, "the draft's code still says the old description"
    change = await outgoing_for(here, "support-triage")
    assert (change["additions"], change["deletions"]) == (1, 1)
    committed = await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})
    assert committed.status_code == 202, committed.text
    _ = await eventually(lambda: asyncio.sleep(0, here.gitea.pulls.get(1)), "the pull request")
    written = here.upstream.read("agents/support_triage.py", "studio/support-triage-v1")
    assert 'description="Sorts tickets."' in written
    assert "# Platform owns this agent; keep the instructions short." in written


async def test_a_fetch_after_a_failure_restores_the_status_the_source_had(stack: Stack, tmp_path: Path) -> None:
    here = await world(stack, tmp_path)
    _ = await eventually(lambda: source_status(here.owner, here.source, "ready"), "the initial scan")

    here.gitea.refuse_token = True
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202
    failed = await eventually(lambda: source_status(here.owner, here.source, "failed"), "the fetch to fail")
    assert "refused the connection's credentials" in failed["status_detail"]
    here.gitea.refuse_token = False
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202
    ready = await eventually(lambda: source_status(here.owner, here.source, "ready"), "the source to recover")
    assert ready["status_detail"] is None, "a source that was never activated goes back to its scan, not to syncing"

    assert (await here.owner.post(f"{here.source}/activate", json={})).status_code == 200
    here.gitea.refuse_token = True
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202
    _ = await eventually(lambda: source_status(here.owner, here.source, "failed"), "the fetch to fail again")
    here.gitea.refuse_token = False
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202
    _ = await eventually(lambda: source_status(here.owner, here.source, "active"), "the source to sync again")


async def test_a_source_activated_with_nothing_bound_still_syncs_after_a_failure(stack: Stack, tmp_path: Path) -> None:
    here = await world(stack, tmp_path)
    report = (await eventually(lambda: source_status(here.owner, f"{here.source}/scan", "ready"), "the scan"))["report"]
    skipped = [
        {"path": entry["path"], "component_id": component["id"], "bind": False}
        for entry in report["files"]
        for component in entry["components"]
        if component["id"]
    ]
    activated = await here.owner.post(f"{here.source}/activate", json={"bindings": skipped})
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"

    here.gitea.refuse_token = True
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202
    _ = await eventually(lambda: source_status(here.owner, here.source, "failed"), "the fetch to fail")
    here.gitea.refuse_token = False
    assert (await here.owner.post(f"{here.source}/fetch")).status_code == 202
    _ = await eventually(lambda: source_status(here.owner, here.source, "active"), "the source to sync again")


async def test_a_source_whose_scan_failed_scans_again_on_its_next_fetch(stack: Stack, tmp_path: Path) -> None:
    here = await world(stack, tmp_path, fail_scan=True)
    failed = await eventually(lambda: source_status(here.owner, here.source, "failed"), "the scan to fail")
    assert "refused the connection's credentials" in failed["status_detail"]
    here.gitea.refuse_token = False
    async with stack.container() as request:
        _ = await (await request.get(SourceJobs)).fetch(here.source_id, "push")
    scan = await eventually(lambda: source_status(here.owner, f"{here.source}/scan", "ready"), "the scan to run")
    assert scan["report"]["scanned_at"], "the source is ready only with a scan to review"
    assert {entry["path"] for entry in scan["report"]["files"]} >= {"agents/support_triage.py"}


async def test_a_read_only_connection_never_writes_back(stack: Stack, tmp_path: Path) -> None:
    here = await bound(stack, tmp_path, access="read_only")
    assert (await here.owner.get(here.source)).json()["auth"] == "Token · pull only"
    await here.save_draft("support-triage", 1, lambda config: config.update(description="Sorts tickets."))
    change = await outgoing_for(here, "support-triage")
    preview = await here.owner.get(f"{here.source}/commit-preview", params={"change_ids": change["id"]})
    assert preview.status_code == 422
    assert "read-only" in preview.json()["detail"]
    commit = await here.owner.post(f"{here.source}/commit", json={"change_ids": [change["id"]]})
    assert commit.status_code == 422

    check = (await here.owner.get(f"{COMPONENTS}/support-triage/publish-check", params={"version": 1})).json()
    assert check["hold"]["write_back"] is None
    assert (await here.publish("support-triage", 1)).status_code == 200
    await asyncio.sleep(1.0)
    assert here.gitea.pulls == {}
    assert here.upstream.branches() == ["main"]


async def test_a_connection_update_changes_only_what_it_sends(stack: Stack, tmp_path: Path) -> None:
    here = await world(stack, tmp_path)
    [connection] = (await here.owner.get("/api/v1/studio/connections")).json()
    url = f"/api/v1/studio/connections/{connection['id']}"

    renamed = await here.owner.patch(url, json={"name": "Northwind Gitea (prod)"})
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["web_url"], renamed.json()["status"]) == (
        "Northwind Gitea (prod)",
        "http://gitea.test",
        "verified",
    )
    rotated = (await here.owner.patch(url, json={"token": "a-revoked-token"})).json()
    assert (rotated["status"], rotated["name"]) == ("failed", "Northwind Gitea (prod)")
    restored = (await here.owner.patch(url, json={"token": TOKEN, "access": "read_only"})).json()
    assert (restored["status"], restored["access"], restored["web_url"]) == (
        "verified",
        "read_only",
        "http://gitea.test",
    )

    switched = await here.owner.patch(url, json={"auth_kind": "deploy_key"})
    assert switched.status_code == 422
    assert "can't switch to a deploy key" in switched.json()["detail"]
    same = await here.owner.patch(url, json={"auth_kind": "token", "provider": "gitea"})
    assert same.status_code == 200, same.text
    moved = await here.owner.patch(url, json={"provider": "gitlab"})
    assert moved.status_code == 422
    cleared = await here.owner.patch(url, json={"web_url": None})
    assert cleared.status_code == 422
    assert "server's URL" in cleared.json()["detail"]

    kept = await here.owner.patch(url, json={"name": None, "access": "read_write"})
    assert kept.status_code == 200, kept.text
    assert (kept.json()["name"], kept.json()["access"]) == ("Northwind Gitea (prod)", "read_write")

    stale = await here.owner.patch(url, json={"name": "Old", "version": 1})
    assert stale.status_code == 409


async def test_a_deploy_key_connection_commits_but_never_opens_pull_requests(stack: Stack, tmp_path: Path) -> None:
    here = await world(stack, tmp_path)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()
    ).decode()
    keyless = await here.owner.post(
        "/api/v1/studio/connections",
        json={"name": "Deploy key", "provider": "gitea", "auth_kind": "deploy_key", "web_url": "http://gitea.test"},
    )
    assert keyless.status_code == 422
    created = await here.owner.post(
        "/api/v1/studio/connections",
        json={
            "name": "Deploy key",
            "provider": "gitea",
            "auth_kind": "deploy_key",
            "web_url": "http://gitea.test",
            "private_key": pem,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "failed", "the key is tried over SSH, and nothing answers at gitea.test"
    assert "over SSH" in created.json()["last_error"]
    connection_id = created.json()["id"]
    bad_address = await here.owner.patch(
        f"/api/v1/studio/connections/{connection_id}", json={"api_url": "https://gitea.test:2222"}
    )
    assert bad_address.status_code == 422
    assert "SSH address" in bad_address.json()["detail"]
    address = await here.owner.patch(
        f"/api/v1/studio/connections/{connection_id}", json={"api_url": "ssh://git@gitea.test:2222"}
    )
    assert address.status_code == 200, address.text
    assert address.json()["api_url"] == "ssh://git@gitea.test:2222"
    assert "gitea.test:2222" in address.json()["last_error"]
    assert (await here.owner.get(f"/api/v1/studio/connections/{connection_id}/repos")).json() == []

    body = {"provider": "gitea", "connection_id": connection_id, "repo": "northwind/agents", "branch": "main"}
    refused = await here.owner.post(SOURCES, json=body)
    assert refused.status_code == 422
    assert "can't open pull requests" in refused.json()["detail"]
    direct = await here.owner.post(SOURCES, json={**body, "policy": {"publish_mode": "commit_direct"}})
    assert direct.status_code == 201, direct.text
    card = direct.json()
    back = await here.owner.patch(
        f"{SOURCES}/{card['id']}", json={"policy": {"publish_mode": "open_pr"}, "version": card["version"]}
    )
    assert back.status_code == 422


async def test_a_local_write_back_refuses_a_file_changed_on_disk(stack: Stack, tmp_path: Path) -> None:
    owner = await stack.owner()
    dev = stack.runtime("dev.agentos.test", os_id="fake-dev", name="Fake dev")
    await connect(owner, dev, "http://dev.agentos.test:7777", display_name="dev-agentos", env_tag="development")
    folder = tmp_path / "local" / "app"
    (folder / "agents").mkdir(parents=True)
    file = folder / "agents" / "support_triage.py"
    file.write_text(SUPPORT_TRIAGE, encoding="utf-8")
    sources = "/api/v1/instances/dev-agentos/studio/sources"
    components = "/api/v1/instances/dev-agentos/studio/components"
    created = await owner.post(sources, json={"provider": "local", "local_path": str(folder)})
    assert created.status_code == 201, created.text
    source = f"{sources}/{created.json()['id']}"
    _ = await eventually(lambda: source_status(owner, source, "ready"), "the scan")
    assert (await owner.post(f"{source}/activate", json={})).status_code == 200

    async def incoming() -> list[dict[str, Any]] | None:
        return (await owner.get(f"{source}/changes")).json()["incoming"] or None

    [change] = await eventually(incoming, "the folder's agent")
    assert (await owner.post(f"{source}/pull", json={"change_ids": [change["id"]]})).json()[0]["version"] == 1
    detail = (await owner.get(f"{components}/support-triage")).json()
    config = copy.deepcopy((await owner.get(f"{components}/support-triage/configs/1")).json()["config"])
    config["description"] = "Sorts tickets."
    saved = await owner.patch(
        f"{components}/support-triage/configs/1", json={"config": config, "revision": detail["draft"]["revision"]}
    )
    assert saved.status_code == 200, saved.text
    [outgoing] = (await owner.post(f"{source}/outgoing/refresh")).json()

    edited = SUPPORT_TRIAGE.replace("Ask for the order number.", "Ask for the order number and the email.")
    file.write_text(edited, encoding="utf-8")
    committed = await owner.post(f"{source}/commit", json={"change_ids": [outgoing["id"]]})
    assert committed.status_code == 202, committed.text

    async def given_back() -> dict[str, Any] | None:
        for item in (await owner.get(f"{source}/changes")).json()["outgoing"]:
            if item["id"] == outgoing["id"] and item["status"] == "pending":
                return item
        return None

    _ = await eventually(given_back, "the write to be refused")
    assert file.read_text(encoding="utf-8") == edited, "the edit on disk is kept"


@pytest.fixture
async def narrow_stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_SOURCES__MAX_CHANGED_FILES", "2")
    configure(monkeypatch, tmp_path)
    async with running_stack(sqlite_database) as running:
        yield running


async def test_a_fetch_with_more_changed_files_than_the_limit_says_so(narrow_stack: Stack, tmp_path: Path) -> None:
    here = await world(narrow_stack, tmp_path)
    _ = await eventually(lambda: source_status(here.owner, here.source, "ready"), "the initial scan")
    assert (await here.owner.post(f"{here.source}/activate", json={})).status_code == 200

    async def warned() -> dict[str, Any] | None:
        card = (await here.owner.get(here.source)).json()
        return card if card["status_detail"] and "files changed" in card["status_detail"] else None

    card = await eventually(warned, "the warning")
    assert card["status_detail"].startswith("3 files changed in this fetch; Studio read the first 2.")
    assert len((await here.changes())["incoming"]) == 2
