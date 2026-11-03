"""Typed component configs and generated code: lossless round trips over the golden ``to_dict()`` fixtures, field
metadata, references, rules, the generator's output with exact spans after ruff, and line marks."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agnostic_codegen import RegistryConvention, generate, line_marks, render, snake
from agnostic_spec import field_meta
from agnostic_spec.v3_1 import (
    AgentConfig,
    TeamConfig,
    check,
    iter_refs,
    json_schema,
    layout,
    parse,
    shape_errors,
)

GOLDEN = Path(__file__).parents[1] / "golden" / "agno-3.1"
REFUND = {"name": "refund_customer", "parameters": {"type": "object"}, "requires_confirmation": True}
TRIAGE: dict[str, Any] = {
    "id": "support-triage",
    "name": "Support Triage",
    "model": {"id": "mock-precise", "provider": "Agnostic", "name": "MockModel"},
    "instructions": ["Classify by product area and urgency.", "Never promise refunds; use refund_customer."],
    "tools": [{"name": "lookup_order", "parameters": {"type": "object"}}, REFUND],
    "knowledge": {"name": "help_center"},
    "output_schema": "TriageResult",
    "enable_agentic_memory": True,
    "add_history_to_context": True,
    "num_history_runs": 5,
    "markdown": True,
}


def golden_configs() -> list[Path]:
    return sorted(GOLDEN.glob("*/*.json"))


@pytest.mark.parametrize("path", golden_configs(), ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_golden_configs_round_trip_losslessly(path: Path) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    kind = "team" if path.parent.name == "teams" else "agent"
    assert parse(kind, raw).dump() == raw


@pytest.mark.parametrize("path", golden_configs(), ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_generated_code_matches_the_golden_files(path: Path) -> None:
    expected = path.with_suffix(".py")
    if not expected.exists():
        pytest.skip("no golden code for this config")
    kind = "team" if path.parent.name == "teams" else "agent"
    rendered = asyncio.run(render(parse(kind, json.loads(path.read_text(encoding="utf-8")))))
    assert rendered.code == expected.read_text(encoding="utf-8")


def test_unknown_keys_survive_and_defaults_are_left_out() -> None:
    config = AgentConfig.parse({**TRIAGE, "search_knowledge": True, "telemetry": True, "from_agno_3_2": {"x": 1}})
    dumped = config.dump()
    assert dumped["from_agno_3_2"] == {"x": 1}
    assert "search_knowledge" not in dumped
    assert "telemetry" not in dumped
    assert AgentConfig.parse({**TRIAGE, "search_knowledge": False}).dump()["search_knowledge"] is False
    assert TeamConfig.parse({"max_iterations": 10, "determine_input_for_members": True}).dump() == {}


def test_shape_errors_name_the_field() -> None:
    problems = shape_errors("agent", {**TRIAGE, "num_history_runs": "five"})
    assert [(item.path, item.severity) for item in problems] == [("num_history_runs", "error")]
    assert shape_errors("team", {"members": [{"type": "robot"}]})[0].path.startswith("members[0]")


def test_field_metadata_drives_the_form() -> None:
    meta = field_meta(AgentConfig, "output_schema")
    assert meta is not None
    assert (meta.section, meta.widget) == ("output", "schema")
    sections = layout("agent")
    assert [section["id"] for section in sections][:4] == ["identity", "model", "instructions", "tools"]
    assert sections[3]["fields"][:2] == ["tools", "tool_call_limit"]
    schema = json_schema("team")
    assert schema["properties"]["mode"]["x-agnostic"]["widget"] == "mode"
    assert schema["x-agnostic-agno"] == "3.1"


def test_references_and_rules() -> None:
    config = AgentConfig.parse(TRIAGE)
    assert [(ref.path, ref.type, ref.name) for ref in iter_refs(config)] == [
        ("model", "model", "mock-precise"),
        ("tools[0]", "tool", "lookup_order"),
        ("tools[1]", "tool", "refund_customer"),
        ("knowledge", "knowledge", "help_center"),
        ("output_schema", "schema", "TriageResult"),
    ]
    team = TeamConfig.parse(
        {
            "mode": "route",
            "max_iterations": 4,
            "respond_directly": True,
            "members": [{"type": "agent", "agent_id": "a"}, {"type": "agent", "agent_id": "a"}],
        }
    )
    assert {item.code for item in check(team)} == {
        "model_missing",
        "member_duplicate",
        "max_iterations_unused",
        "legacy_flags_ignored",
    }
    assert TeamConfig.parse({"delegate_to_all_members": True}).effective_mode() == "broadcast"
    unrebuildable = AgentConfig.parse({**TRIAGE, "tools": [{"name": "x"}]})
    assert "tool_without_parameters" in {item.code for item in check(unrebuildable)}


def test_generated_code_uses_the_registry_convention() -> None:
    generated = generate(AgentConfig.parse(TRIAGE))
    assert generated.variable == "support_triage"
    assert "from app.registry import knowledge, models, schemas, tools" in generated.code
    assert "    model=models.mock_precise," in generated.code
    assert generated.code.index("output_schema") < generated.code.index("markdown")
    assert [(note.path, note.kind) for note in generated.notes] == [("tools[1]", "approval")]

    convention = RegistryConvention(registry_module="platform.reg", agents_module="platform.agents")
    team = generate(TeamConfig.parse({"id": "research-team", "members": [{"agent_id": "kb-researcher"}]}), convention)
    assert "from platform.agents import kb_researcher" in team.code
    assert snake("claude-opus-5.5") == "claude_opus_5_5"
    assert snake("class") == "class_"


def test_toolkit_functions_share_one_element() -> None:
    config = AgentConfig.parse(
        {
            "tools": [
                {"name": "web_search", "toolkit": "websearch", "parameters": {}},
                {"name": "search_news", "toolkit": "websearch", "parameters": {}},
            ]
        }
    )
    generated = generate(config)
    assert generated.code.count("tools.websearch") == 1
    assert generated.element_paths["tools"] == [["tools[0]", "tools[1]"]]


def test_spans_are_exact_after_formatting() -> None:
    rendered = asyncio.run(render(AgentConfig.parse(TRIAGE)))
    lines = rendered.code.splitlines()
    for path in ("model", "instructions[1]", "tools[1]", "output_schema"):
        span = rendered.spans[path]
        text = lines[span.line - 1][span.col_start : span.col_end]
        assert text, path
    assert lines[rendered.spans["tools[1]"].line - 1].strip() == "tools.refund_customer,"
    assert rendered.ruff.status == "ruff · 0 errors"


def test_line_marks() -> None:
    base = "a\nb\nc\n"
    assert line_marks(base, "a\nB\nc\nd\n") == {2: "modified", 4: "added"}
    assert line_marks(base, base) == {}
