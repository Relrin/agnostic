"""Studio against fake AgentOS instances: the registry catalog, creating support-triage from blank with registry objects
only, autosave with conflicts, generated code, a draft test run through delegated elevation, a publish blocked by an
eval gate and published with an audited override, rollback, a team with pinned members, and promotion to prod."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.api.test_instances_gateway import connect
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

STAGING = "/api/v1/instances/staging-agentos"
PROD = "/api/v1/instances/prod-agentos"
PARAMETERS = {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    async with running_stack(sqlite_database) as running:
        yield running


def registry(*, refunds: bool = True) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "name": "lookup_order",
            "type": "tool",
            "description": "Look up an order.",
            "metadata": {
                "class_path": "agno.tools.function.Function",
                "module": "app.tools",
                "qualname": "lookup_order",
                "parameters": PARAMETERS,
                "signature": "lookup_order(order_id: str) -> str",
            },
        }
    ]
    if refunds:
        tools.append(
            {
                "name": "refund_customer",
                "type": "tool",
                "description": "Issues a refund through the payments API.",
                "metadata": {
                    "class_path": "agno.tools.function.Function",
                    "module": "app.tools",
                    "qualname": "refund_customer",
                    "parameters": PARAMETERS,
                    "requires_confirmation": True,
                },
            }
        )
    return [
        *tools,
        {
            "name": "mock-precise",
            "type": "model",
            "metadata": {"class_path": "app.models.mock.MockModel", "provider": "Agnostic", "model_id": "mock-precise"},
        },
        {
            "name": "TriageResult",
            "type": "schema",
            "metadata": {
                "class_path": "app.schemas.TriageResult",
                "schema": {"properties": {"category": {"type": "string"}, "urgency": {}, "needs_human": {}}},
            },
        },
        {"name": "agnostic-db", "type": "db", "metadata": {"class_path": "agno.db.postgres.PostgresDb", "db_id": "x"}},
    ]


async def two_instances(stack: Stack, owner: httpx.AsyncClient) -> tuple[FakeAgentOS, FakeAgentOS, dict[str, Any]]:
    staging = stack.runtime("staging.agentos.test", os_id="fake-staging", name="Fake staging")
    prod = stack.runtime("prod.agentos.test")
    staged = await connect(
        owner, staging, "http://staging.agentos.test:7777", display_name="staging-agentos", env_tag="staging"
    )
    await connect(owner, prod)
    staging.registry_items = registry()
    prod.registry_items = registry(refunds=False)
    return staging, prod, staged


async def entry(owner: httpx.AsyncClient, base: str, entry_type: str, name: str) -> dict[str, Any]:
    response = await owner.get(f"{base}/studio/registry/{entry_type}/{name}")
    assert response.status_code == 200, response.text
    return response.json()


def average_8_4(body: dict[str, Any], path: str) -> dict[str, Any]:
    return {"eval_data": {"avg_score": 8.4, "results": [{"score": 8.4}]}}


async def events(owner: httpx.AsyncClient, action: str) -> list[dict[str, Any]]:
    response = await owner.get("/api/v1/audit/events", params={"limit": 200, "action": action})
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_registry_catalog_counts_flags_and_availability(stack: Stack) -> None:
    owner = await stack.owner()
    staging, _, _ = await two_instances(stack, owner)
    staging.bridge = True
    staging.bridge_studio = True
    staging.registry_sources[("tool", "lookup_order")] = {"declared": False}

    catalog = (await owner.get(f"{STAGING}/studio/registry")).json()
    assert catalog["counts"] == {"tool": 2, "model": 1, "schema": 1, "db": 1}
    assert catalog["bridge"] is True
    tools = (await owner.get(f"{STAGING}/studio/registry", params={"type": "tool"})).json()["entries"]
    assert [item["name"] for item in tools] == ["lookup_order", "refund_customer"]

    refund = await entry(owner, STAGING, "tool", "refund_customer")
    assert refund["entry"]["requires_approval"] is True
    assert refund["entry"]["meta"] == "app.tools.refund_customer · @approval"
    assert refund["entry"]["availability"]["title"] == "Available in Studio."
    assert refund["entry"]["config_value"][0]["parameters"] == PARAMETERS
    assert refund["used_by"] == []

    discovered = await entry(owner, STAGING, "tool", "lookup_order")
    assert discovered["entry"]["status"] == "discovered"
    assert discovered["entry"]["studio_available"] is False
    assert discovered["entry"]["availability"]["title"] == "Not available in Studio."

    schema = await entry(owner, STAGING, "schema", "TriageResult")
    assert schema["entry"]["meta"] == "BaseModel · 3 fields"
    assert schema["entry"]["code_label"] == "JSON schema"
    model = await entry(owner, STAGING, "model", "mock-precise")
    assert model["entry"]["config_value"] == {"id": "mock-precise", "provider": "Agnostic"}

    missing = await owner.get(f"{STAGING}/studio/registry/tool/nope")
    assert missing.status_code == 404


async def test_support_triage_from_blank_to_prod(stack: Stack) -> None:  # noqa: PLR0915  (the whole journey)
    owner = await stack.owner()
    owner_id = (await owner.get("/api/v1/me")).json()["id"]
    staging, prod, _ = await two_instances(stack, owner)

    # ------------------------------------------------ create from blank, with the registry's model
    model = (await entry(owner, STAGING, "model", "mock-precise"))["entry"]["config_value"]
    created = await owner.post(
        f"{STAGING}/studio/components",
        json={"kind": "agent", "name": "support-triage", "mode": "blank", "model": model},
    )
    assert created.status_code == 201, created.text
    detail = created.json()
    assert detail["component"]["id"] == "support-triage"
    assert detail["draft"]["version"] == 1
    assert detail["draft"]["config"] == {
        "id": "support-triage",
        "name": "support-triage",
        "markdown": True,
        "model": model,
    }
    assert detail["draft"]["author_name"]
    assert staging.components["support-triage"]["user_id"] == owner_id
    duplicate = await owner.post(f"{STAGING}/studio/components", json={"kind": "agent", "name": "support-triage"})
    assert duplicate.status_code == 409

    # ------------------------------------------------ autosave with registry tools and schema; conflicts
    refund = (await entry(owner, STAGING, "tool", "refund_customer"))["entry"]["config_value"]
    lookup = (await entry(owner, STAGING, "tool", "lookup_order"))["entry"]["config_value"]
    config: dict[str, Any] = {
        **detail["draft"]["config"],
        "instructions": ["Classify by product area and urgency.", "Never promise refunds; use refund_customer."],
        "tools": [*lookup, *refund],
        "output_schema": "TriageResult",
        "search_knowledge": True,
    }
    revision = detail["draft"]["revision"]
    saved = await owner.patch(
        f"{STAGING}/studio/components/support-triage/configs/1", json={"config": config, "revision": revision}
    )
    assert saved.status_code == 200, saved.text
    assert "search_knowledge" not in staging.configs["support-triage"][1]["config"]  # agno's default is left out
    assert staging.config_patches[-1]["body"]["guard"] == {"latest_version": 1}
    stale = await owner.patch(
        f"{STAGING}/studio/components/support-triage/configs/1", json={"config": config, "revision": revision}
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "version_conflict"
    assert stale.json()["saved_by"]
    revision = saved.json()["revision"]
    bad = await owner.patch(
        f"{STAGING}/studio/components/support-triage/configs/1",
        json={"config": {**config, "instructions": 3}, "revision": revision},
    )
    assert bad.status_code == 422
    assert bad.json()["diagnostics"][0]["path"].startswith("instructions")

    # ------------------------------------------------ generated code and validation
    code = await owner.post(
        f"{STAGING}/studio/codegen",
        json={"kind": "agent", "config": config, "base_config": detail["draft"]["config"]},
    )
    assert code.status_code == 200, code.text
    body = code.json()
    assert "support_triage = Agent(" in body["code"]
    assert "        tools.refund_customer," in body["code"]
    assert "    output_schema=schemas.TriageResult," in body["code"]
    assert body["ruff"]["status"] == "ruff · 0 errors"
    assert body["filename"] == "agents/support_triage.py"
    instructions = body["spans"]["instructions[1]"]["line"]
    assert body["marks"][str(instructions)] in {"added", "modified"}
    assert [note["entry"] for note in body["notes"]] == ["refund_customer"]

    valid = (await owner.post(f"{STAGING}/studio/validate", json={"kind": "agent", "config": config})).json()
    assert valid["ok"] is True
    registry_layer = next(layer for layer in valid["layers"] if layer["id"] == "registry")
    assert [item["message"] for item in registry_layer["diagnostics"]] == [
        "Tool `refund_customer` is registered · needs approval."
    ]
    assert next(layer for layer in valid["layers"] if layer["id"] == "bridge")["status"] == "skipped"
    unknown = {**config, "tools": [{"name": "wire_money", "parameters": {}}]}
    invalid = (await owner.post(f"{STAGING}/studio/validate", json={"kind": "agent", "config": unknown})).json()
    assert invalid["ok"] is False
    assert "isn't registered on staging-agentos" in invalid["layers"][1]["diagnostics"][0]["message"]

    # ------------------------------------------------ test the draft (AgentOS runs drafts for owners/admins only)
    staging.components["support-triage"]["user_id"] = "someone-else"
    async with owner.stream(
        "POST",
        f"{STAGING}/studio/components/support-triage/test-runs",
        json={"message": "My card was charged twice", "version": 1},
    ) as response:
        assert response.status_code == 200
        streamed = b"".join([chunk async for chunk in response.aiter_bytes()])
    assert b"RunCompleted" in streamed
    run = staging.run_requests[-1]
    assert (run["form"]["version"], run["sub"]) == ("1", owner_id)
    elevated = await events(owner, "gateway.elevated")
    assert elevated[0]["scope_checked"] == "components:write"

    # ------------------------------------------------ eval gate 8.40 < 8.5 blocks; override with a reason
    staging.bridge = True
    staging.eval_responder = average_8_4
    dataset = await owner.post(
        f"{STAGING}/eval-datasets",
        json={
            "name": "billing-tickets",
            "eval_type": "accuracy",
            "cases": [{"input": "refund?", "expected_output": "x"}],
        },
    )
    assert dataset.status_code == 201, dataset.text
    gate = await owner.put(
        f"{STAGING}/eval-gates",
        json={
            "component_kind": "agent",
            "component_id": "support-triage",
            "dataset_id": dataset.json()["id"],
            "min_average": 8.5,
            "enabled": True,
        },
    )
    assert gate.status_code == 200, gate.text
    batch = await owner.post(
        f"{STAGING}/eval-batches",
        json={
            "dataset_id": dataset.json()["id"],
            "component_kind": "agent",
            "component_id": "support-triage",
            "version": 1,
        },
    )
    assert batch.status_code == 202, batch.text
    for _ in range(200):
        state = (await owner.get(f"{STAGING}/eval-batches/{batch.json()['id']}")).json()["batch"]["status"]
        if state in {"completed", "failed"}:
            break
        await asyncio.sleep(0.05)

    check = (await owner.get(f"{STAGING}/studio/components/support-triage/publish-check", params={"version": 1})).json()
    assert check["blocked_by_gates"] is True
    assert check["gates"][0]["consequence"] == "v1 draft (8.40) would be blocked from publishing."
    assert (check["can_publish"], check["can_override"]) == (True, True)
    assert check["outcome"] == "v1 becomes current on staging-agentos; the API serves it from the next request."

    blocked = await owner.post(f"{STAGING}/studio/components/support-triage/configs/1/publish", json={})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "gate_blocked"
    published = await owner.post(
        f"{STAGING}/studio/components/support-triage/configs/1/publish",
        json={"notes": "First triage agent", "override_reason": "Judge disagrees on two billing cases; fixed in v2"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["overridden"] is True
    assert published.json()["version"]["eval_status"] == "overridden"
    assert staging.components["support-triage"]["current_version"] == 1

    override = await events(owner, "evals.gate.override")
    assert override[0]["summary"].endswith("past its eval gate: Judge disagrees on two billing cases; fixed in v2")
    publish_event = (await events(owner, "studio.publish"))[0]
    detail_event = (await owner.get(f"/api/v1/audit/events/{publish_event['id']}")).json()
    assert {"op": "add", "text": "tools: 2 items"} in detail_event["diff"]["lines"]
    assert detail_event["diff"]["note"].startswith("Gate override:")

    # ------------------------------------------------ versions: new draft from current, diff, rollback rules
    draft = await owner.post(f"{STAGING}/studio/components/support-triage/configs", json={})
    assert draft.status_code == 201, draft.text
    assert (draft.json()["version"], draft.json()["based_on_version"]) == (2, 1)
    edited = {**config, "instructions": [*config["instructions"], "Answer in the customer's language."]}
    saved_v2 = await owner.patch(
        f"{STAGING}/studio/components/support-triage/configs/2",
        json={"config": edited, "revision": draft.json()["revision"]},
    )
    assert saved_v2.status_code == 200, saved_v2.text
    diff = (await owner.get(f"{STAGING}/studio/components/support-triage/diff", params={"from": 1, "to": 2})).json()
    assert diff["counts"] == {"added": 1, "changed": 0, "removed": 0}
    assert diff["summary"] == "one new instruction"
    assert diff["lines_added"] == 1
    not_published = await owner.post(f"{STAGING}/studio/components/support-triage/configs/2/set-current", json={})
    assert not_published.status_code == 409

    used = await entry(owner, STAGING, "tool", "refund_customer")
    assert used["used_by"] == [
        {
            "component_id": "support-triage",
            "component_kind": "agent",
            "component_name": "support-triage",
            "versions": ["v1", "v2 draft"],
            "versions_text": "v1 · v2 draft",
        }
    ]
    rows = (await owner.get(f"{STAGING}/studio/components", params={"kind": "agent"})).json()
    assert [(row["component"]["id"], row["draft_version"]) for row in rows] == [("support-triage", 2)]

    # ------------------------------------------------ promote to prod: blocked by the registry, then applied
    dry = await owner.post(f"{STAGING}/studio/components/support-triage/promotions", json={"target": "prod-agentos"})
    assert dry.status_code == 201, dry.text
    assert dry.json()["status"] == "blocked"
    assert dry.json()["report"]["missing"] == [{"type": "tool", "name": "refund_customer", "paths": ["tools[1]"]}]
    assert dry.json()["report"]["summary"] == "Blocked: tool `refund_customer` isn't registered on the target."
    refused = await owner.post(f"{STAGING}/studio/promotions/{dry.json()['id']}/apply", json={})
    assert refused.status_code == 409

    prod.registry_items = registry()
    again = await owner.post(f"{STAGING}/studio/components/support-triage/promotions", json={"target": "prod-agentos"})
    assert again.json()["status"] == "dry_run"
    assert again.json()["report"]["summary"] == "All 4 registry references exist on the target."
    applied = await owner.post(f"{STAGING}/studio/promotions/{again.json()['id']}/apply", json={"publish": False})
    assert applied.status_code == 200, applied.text
    assert (applied.json()["status"], applied.json()["to_version"]) == ("applied", 1)
    assert prod.configs["support-triage"][1]["config"]["tools"][1]["name"] == "refund_customer"
    assert prod.configs["support-triage"][1]["stage"] == "draft"
    on_prod = (await owner.get(f"{PROD}/studio/components/support-triage")).json()
    assert on_prod["draft"]["promoted_from"]["instance"] == "staging-agentos"
    promote_event = (await events(owner, "studio.promote"))[0]
    assert promote_event["summary"].endswith("from staging-agentos v1 to prod-agentos v1 (as a draft)")


async def test_team_members_are_pinned_and_archive_lists_dependents(stack: Stack) -> None:
    owner = await stack.owner()
    staging, _, _ = await two_instances(stack, owner)
    model = {"id": "mock-precise", "provider": "Agnostic"}
    for name in ("kb-researcher", "summarizer"):
        created = await owner.post(
            f"{STAGING}/studio/components", json={"kind": "agent", "name": name, "mode": "blank", "model": model}
        )
        assert created.status_code == 201, created.text
        published = await owner.post(f"{STAGING}/studio/components/{name}/configs/1/publish", json={})
        assert published.status_code == 200, published.text

    team = await owner.post(
        f"{STAGING}/studio/components",
        json={
            "kind": "team",
            "name": "research-team",
            "mode": "import",
            "config": {
                "mode": "tasks",
                "max_iterations": 6,
                "model": model,
                "members": [
                    {"type": "agent", "agent_id": "kb-researcher"},
                    {"type": "agent", "agent_id": "summarizer"},
                ],
            },
        },
    )
    assert team.status_code == 201, team.text
    links = staging.configs["research-team"][1]["links"]
    assert [(link["child_component_id"], link["child_version"], link["link_key"]) for link in links] == [
        ("kb-researcher", 1, "member_0"),
        ("summarizer", 1, "member_1"),
    ]
    code = (
        await owner.post(f"{STAGING}/studio/codegen", json={"kind": "team", "config": team.json()["draft"]["config"]})
    ).json()
    assert "    mode=TeamMode.tasks," in code["code"]
    assert "from app.agents import kb_researcher, summarizer" in code["code"]

    templates = (await owner.get("/api/v1/studio/templates", params={"kind": "team"})).json()
    assert {item["id"] for item in templates} == {"blank-team", "coordinate-team"}
    schema = (await owner.get("/api/v1/studio/schema/team")).json()
    assert [section["id"] for section in schema["x-agnostic-sections"]][:2] == ["team", "members"]

    archived = await owner.delete(f"{STAGING}/studio/components/kb-researcher")
    assert archived.status_code == 409
    assert archived.json()["dependents"] == ["research-team"]


async def test_code_defined_agent_is_viewable_and_duplicable(stack: Stack) -> None:
    owner = await stack.owner()
    staging, _, _ = await two_instances(stack, owner)
    model = {"id": "mock-precise", "provider": "Agnostic"}
    config = {
        "id": "billing-agent",
        "name": "billing-agent",
        "description": "Handles billing questions.",
        "model": model,
        "instructions": "Resolve billing questions.",
        "markdown": True,
    }
    staging.agent_items = [
        {"id": "billing-agent", "name": "billing-agent", "description": "Handles billing questions."}
    ]

    # Without the bridge: listed and viewable, but its config can't be read.
    bare = await owner.get(f"{STAGING}/studio/code-components/agent/billing-agent")
    assert bare.status_code == 200, bare.text
    assert bare.json()["component"]["source"] == "code"
    assert bare.json()["config"] is None
    assert "agnostic-bridge" in bare.json()["unavailable"]
    refused = await owner.post(
        f"{STAGING}/studio/components",
        json={
            "kind": "agent",
            "name": "billing-copy",
            "mode": "duplicate",
            "source_id": "billing-agent",
            "source_origin": "code",
        },
    )
    assert refused.status_code == 422

    staging.bridge = True
    staging.bridge_studio = True
    staging.code_components = [
        {
            "id": "billing-agent",
            "kind": "agent",
            "name": "billing-agent",
            "config": config,
            "module": "app.agents.billing_agent",
            "file": "/srv/app/agents/billing_agent.py",
            "line": 8,
        }
    ]
    await owner.post(f"{STAGING}/studio/registry/refresh")
    viewed = await owner.get(f"{STAGING}/studio/code-components/agent/billing-agent")
    assert viewed.status_code == 200, viewed.text
    body = viewed.json()
    assert body["config"] == config
    assert body["unavailable"] is None
    assert body["source"] == {
        "module": "app.agents.billing_agent",
        "file": "/srv/app/agents/billing_agent.py",
        "line": 8,
    }
    assert body["component"]["description"] == "Handles billing questions."
    missing = await owner.get(f"{STAGING}/studio/code-components/team/billing-agent")
    assert missing.status_code == 404

    copied = await owner.post(
        f"{STAGING}/studio/components",
        json={
            "kind": "agent",
            "name": "billing-copy",
            "mode": "duplicate",
            "source_id": "billing-agent",
            "source_origin": "code",
        },
    )
    assert copied.status_code == 201, copied.text
    draft = copied.json()["draft"]
    assert copied.json()["component"]["source"] == "studio"
    assert draft["version"] == 1
    assert draft["config"]["id"] == "billing-copy"
    assert draft["config"]["name"] == "billing-copy"
    assert draft["config"]["instructions"] == "Resolve billing questions."
    assert draft["config"]["model"] == model
    assert draft["change_summary"] == "Duplicated from billing-agent (defined in code)"
    assert "billing-agent" not in staging.components
