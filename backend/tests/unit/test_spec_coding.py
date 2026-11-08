"""Coding agents in the spec: the marker's settings and schema, the form section, rules, the Studio template, the
gateway's routes for the bridge, and a lossless round trip through the typed config and generated code."""

import ast
from typing import Any

import pytest

from agnostic_codegen import generate
from agnostic_gateway.domain.policies import DEFAULT_POLICIES, PolicyTable
from agnostic_spec.v3_1 import AgentConfig, CodingAgentSettings, check, json_schema, layout, parse
from agnostic_studio.domain.templates import template

MARKER = {"harness": "pi", "thinking": "low", "sandbox": {"provider": "docker", "cpus": 1.5, "memory_mb": 4096}}
CODER: dict[str, Any] = {
    "id": "pi-coder",
    "name": "Pi coder",
    "model": {"id": "mock-coder", "provider": "Agnostic", "name": "MockModel"},
    "instructions": ["Write files to outputs/."],
    "metadata": {"agnostic": {"coding_agent": MARKER}, "team": "platform"},
}
TABLE = PolicyTable(DEFAULT_POLICIES)


def test_settings_fill_in_the_bridge_defaults() -> None:
    settings = CodingAgentSettings.model_validate({"harness": "opencode"})
    assert settings.model_dump() == {
        "harness": "opencode",
        "outputs_root": "outputs",
        "thinking": None,
        "sandbox": {
            "provider": "docker",
            "image": "agnostic-coding:0.1.0",
            "template": None,
            "cpus": 2.0,
            "memory_mb": 2048,
            "workspace_mb": 512,
            "pids_limit": 256,
            "network": "isolated",
            "turn_timeout_s": 900,
            "idle_pause_s": 300,
            "ttl_s": 3600,
        },
    }


def test_agent_schema_carries_the_coding_section_and_settings() -> None:
    sections = layout("agent")
    assert {"id": "coding_agent", "label": "Coding agent", "fields": []} in sections
    assert [section["id"] for section in sections][-2:] == ["coding_agent", "advanced"]

    schema = json_schema("agent")["x-agnostic-coding-agent"]
    harness = schema["properties"]["harness"]
    assert (harness["enum"], harness["x-agnostic"]["widget"]) == (["pi", "opencode"], "select")
    assert schema["required"] == ["harness"]
    sandbox = schema["$defs"]["SandboxSettings"]["properties"]
    assert sandbox["provider"]["enum"] == ["docker", "e2b"]
    assert (sandbox["provider"]["default"], sandbox["provider"]["x-agnostic"]["section"]) == ("docker", "sandbox")
    assert (sandbox["cpus"]["default"], sandbox["cpus"]["x-agnostic"]["widget"]) == (2.0, "number")
    assert "x-agnostic-coding-agent" not in json_schema("team")


def test_a_malformed_marker_is_an_error_at_its_path() -> None:
    marker = {"harness": "claude", "sandbox": {"cpus": 0, "gpus": 1}}
    config = parse("agent", {**CODER, "metadata": {"agnostic": {"coding_agent": marker}}})
    found = {(item.path, item.severity, item.code) for item in check(config)}
    assert found == {
        ("metadata.agnostic.coding_agent.harness", "error", "coding_agent_invalid"),
        ("metadata.agnostic.coding_agent.sandbox.cpus", "error", "coding_agent_invalid"),
        ("metadata.agnostic.coding_agent.sandbox.gpus", "error", "coding_agent_invalid"),
    }
    not_an_object = parse("agent", {**CODER, "metadata": {"agnostic": {"coding_agent": "pi"}}})
    assert [(item.path, item.code) for item in check(not_an_object)] == [
        ("metadata.agnostic.coding_agent", "coding_agent_invalid")
    ]


def test_fields_a_coding_agent_ignores_are_warnings() -> None:
    config = parse(
        "agent",
        {
            **CODER,
            "learning": True,
            "enable_agentic_memory": True,
            "output_schema": "TriageResult",
            "input_schema": {"type": "object"},
            "enable_session_summaries": True,
            "reasoning_model": "agnostic:mock-precise",
            "add_memories_to_context": False,
        },
    )
    ignored = sorted(item.path for item in check(config) if item.code == "coding_agent_ignores")
    assert ignored == [
        "enable_agentic_memory",
        "enable_session_summaries",
        "input_schema",
        "learning",
        "output_schema",
        "reasoning_model",
    ]
    assert all(item.severity == "warning" for item in check(config) if item.code == "coding_agent_ignores")
    assert check(parse("agent", CODER)) == []
    plain = parse("agent", {**CODER, "metadata": None, "learning": True})
    assert not [item for item in check(plain) if item.code.startswith("coding_agent")]


def test_the_marker_survives_the_typed_config_and_generated_code() -> None:
    config = AgentConfig.parse(CODER)
    assert config.dump() == CODER
    generated = generate(config)
    tree = ast.parse(generated.code)
    call = next(
        node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Agent"
    )
    metadata = next(keyword.value for keyword in call.keywords if keyword.arg == "metadata")
    assert ast.literal_eval(metadata) == CODER["metadata"]
    assert "model=models.mock_coder," in generated.code


def test_the_coding_agent_template() -> None:
    chosen = template("coding-agent")
    assert chosen is not None
    assert (chosen.kind, chosen.label) == ("agent", "Coding agent")
    assert chosen.description == "Pi in a Docker sandbox; files written to outputs/ become artefacts."
    config = dict(chosen.config)
    assert config["model"]["id"] == "mock-coder"
    assert config["metadata"] == {"agnostic": {"coding_agent": {"harness": "pi"}}}
    assert config["instructions"]
    assert check(parse("agent", {"id": "c", "name": "c", **config})) == []


@pytest.mark.parametrize(
    ("method", "path", "scopes", "ttl", "audit", "bucket"),
    [
        ("GET", "/agnostic/v1/coding-agents", ("agents:read",), 30, "decision", "read"),
        ("POST", "/agnostic/v1/coding-agents/refresh", ("config:write",), 0, "full", "write"),
        ("GET", "/agnostic/v1/reasoning/agents/coder", ("agents:read",), 30, "decision", "read"),
    ],
)
def test_gateway_maps_the_coding_agent_routes(
    method: str, path: str, scopes: tuple[str, ...], ttl: int, audit: str, bucket: str
) -> None:
    policy, params = TABLE.match(method, path)
    assert (policy.source, policy.required(params)) == ("default", scopes)
    assert (policy.cache_ttl_s, policy.audit_level, policy.rate_bucket) == (ttl, audit, bucket)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/agnostic/v1/coding/models/chat/completions"),
        ("POST", "/agnostic/v1/coding/files"),
        ("GET", "/agnostic/v1/coding/sessions/ses_1"),
    ],
)
def test_sandbox_callback_routes_fail_closed(method: str, path: str) -> None:
    policy, _ = TABLE.match(method, path)
    assert (policy.source, policy.scopes) == ("fallback", ("agent_os:admin",))
