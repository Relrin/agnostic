"""Code → config: every golden config survives config → code → config, human-styled code reads as the expected
config, and anything that can't be stored is located and marked code-owned rather than dropped."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agnostic_codegen import Lookup, RegistryConvention, components_in, parse_source, render
from agnostic_spec.v3_1 import ComponentConfig, Kind, parse

GOLDEN = Path(__file__).parents[1] / "golden" / "agno-3.1"
KINDS: dict[str, Kind] = {"agents": "agent", "teams": "team", "workflows": "workflow", "prototype": "workflow"}


def golden(folder: str, name: str) -> ComponentConfig:
    return parse(KINDS[folder], json.loads((GOLDEN / folder / f"{name}.json").read_text(encoding="utf-8")))


def every_golden() -> list[ComponentConfig]:
    return [
        parse(KINDS[path.parent.name], json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(GOLDEN.glob("*/*.json"))
    ]


@pytest.mark.parametrize("path", sorted(GOLDEN.glob("*/*.json")), ids=lambda path: f"{path.parent.name}/{path.stem}")
def test_every_golden_config_round_trips_through_code(path: Path) -> None:
    kind = KINDS[path.parent.name]
    raw = json.loads(path.read_text(encoding="utf-8"))
    config = parse(kind, raw)
    code = asyncio.run(render(config)).code
    parsed = parse_source(code, kind=kind, resolver=Lookup().learn([config]))
    assert parsed.diagnostics == []
    assert parsed.code_owned == []
    assert parsed.config == raw


HUMAN_AGENT = '''"""Support triage, hand-tuned."""

import app.registry as registry
from agno.agent import Agent
from app.registry import models as m
from app.registry.tools import refund_customer

GREETING = "Triage the ticket: answer from the help center when you can, otherwise hand off. "

# Keep the instructions short: the model is small.
support_triage = Agent(
    id="support-triage",
    name="support-triage",
    description="Classifies incoming tickets and answers simple ones.",
    model=m.agnostic_mock,  # the default preset
    instructions=(
        GREETING
        + "Refunds go through refund_customer, which a human approves."
    ),
    tools=[registry.tools.lookup_order, registry.tools.search_knowledge, refund_customer],
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
)
'''


def test_human_styled_agent_reads_as_its_config() -> None:
    expected = golden("agents", "support-triage")
    parsed = parse_source(HUMAN_AGENT, kind="agent", resolver=Lookup().learn([expected]))
    assert parsed.diagnostics == []
    assert parsed.config == expected.dump()
    assert parsed.spans["tools[2]"].line == 20
    assert parsed.spans["model"].line == 15


HUMAN_TEAM = """from agno.team import Team
from agno.team.mode import TeamMode
from app.agents.kb_researcher import kb_researcher
from app.agents.summarizer import summarizer
from app.agents.web_researcher import web_researcher
from app.registry import models

research_team = Team(
    id="research-team",
    name="research-team",
    mode=TeamMode.coordinate,
    # Order matters: the leader asks them in this order.
    members=[kb_researcher, web_researcher, summarizer],
    description="Researches a question across the knowledge base and the web, then writes a brief.",
    model=models.agnostic_mock,
    instructions="Ask kb-researcher first, web-researcher for anything missing, and summarizer for the final brief.",
    num_history_runs=3,
    store_events=True,
)
"""


def test_human_styled_team_with_module_per_agent_imports() -> None:
    expected = golden("teams", "research-team")
    parsed = parse_source(HUMAN_TEAM, kind="team", resolver=Lookup().learn(every_golden()))
    assert parsed.diagnostics == []
    assert parsed.config == expected.dump()


def test_the_prototype_ticket_router_reads_as_its_config() -> None:
    from tests.unit.test_prototype_ticket_router import PROTOTYPE  # noqa: PLC0415

    expected = golden("prototype", "ticket-router")
    parsed = parse_source(PROTOTYPE, kind="workflow", resolver=Lookup().learn([expected]))
    assert parsed.diagnostics == []
    assert parsed.config == expected.dump()
    # The router's choices defined above it point at their definitions; the router itself at its own lines.
    assert (parsed.spans["steps[1].choices[1]"].line, parsed.spans["steps[1].choices[1]"].end_line) == (12, 16)
    assert (parsed.spans["steps[1]"].line, parsed.spans["steps[1]"].end_line) == (32, 36)


UNSUPPORTED = """from agno.agent import Agent
from agno.models.anthropic import Claude
from app.registry import tools
from app.hooks import check_input

support_triage = Agent(
    id="support-triage",
    model=Claude(id="claude-opus-5-5", temperature=0.2),
    instructions=[f"Today is {TODAY}", "Be brief."],
    tools=[tools.lookup_order, tools.unknown_tool],
    pre_hooks=[check_input],
    markdown=True,
)
"""


def test_unsupported_constructs_are_located_and_code_owned() -> None:
    lookup = Lookup().learn([golden("agents", "support-triage")])
    parsed = parse_source(UNSUPPORTED, kind="agent", resolver=lookup)
    assert parsed.code_owned == ["model", "instructions", "tools", "pre_hooks"]
    by_path = {diagnostic.path: diagnostic for diagnostic in parsed.diagnostics}
    assert by_path["model"].line == 8
    assert "`Claude(…)` is code; register it as a model preset" in by_path["model"].message
    assert by_path["instructions"].code == "f_string"
    assert "isn't in this instance's registry" in by_path["tools"].message
    assert by_path["pre_hooks"].code == "code_only"
    assert "registered tool" in by_path["pre_hooks"].message
    # The rest stays editable.
    assert parsed.config == {"id": "support-triage", "markdown": True}


WORKFLOW_PROBLEMS = """from agno.workflow import Router, Step, Workflow
from app.agents import support_triage
from app.functions import pick_route

w = Workflow(
    id="w",
    steps=[
        support_triage,
        Router(name="Route", selector=lambda step_input: "a", choices=[Step(name="a", agent=support_triage)]),
    ],
)
"""


def test_workflow_problems_are_reported_where_they_are() -> None:
    parsed = parse_source(WORKFLOW_PROBLEMS, kind="workflow")
    codes = {diagnostic.code for diagnostic in parsed.diagnostics}
    assert "bare_executor" in codes
    assert parsed.code_owned == ["steps"]
    bare = next(diagnostic for diagnostic in parsed.diagnostics if diagnostic.code == "bare_executor")
    assert bare.line == 8
    assert "Wrap `support_triage` in Step(name=…" in bare.message


def test_lambda_selectors_are_code_owned() -> None:
    code = WORKFLOW_PROBLEMS.replace("        support_triage,\n", "")
    parsed = parse_source(code, kind="workflow", resolver=Lookup().learn([]))
    assert parsed.code_owned == ["steps[0].selector"]
    assert "component_unknown" in {diagnostic.code for diagnostic in parsed.diagnostics}
    assert parsed.config is not None
    assert parsed.config["steps"][0]["selector"] is None


@pytest.mark.parametrize(
    ("code", "code_name"),
    [
        ("x = (", "syntax"),
        ("print('no component here')\n", "component_missing"),
    ],
)
def test_files_without_a_component(code: str, code_name: str) -> None:
    parsed = parse_source(code)
    assert parsed.config is None
    assert [diagnostic.code for diagnostic in parsed.diagnostics] == [code_name]


def test_picks_the_component_by_id() -> None:
    code = (
        'from agno.agent import Agent\n\na = Agent(id="first", markdown=True)\nb = Agent(id="second", name="Second")\n'
    )
    parsed = parse_source(code, component_id="second")
    assert parsed.variable == "b"
    assert parsed.config == {"id": "second", "name": "Second"}
    ambiguous = parse_source(code)
    assert ambiguous.variable == "a"
    assert "component_ambiguous" in {diagnostic.code for diagnostic in ambiguous.diagnostics}


def test_custom_convention() -> None:
    convention = RegistryConvention(registry_module="platform.registry", agents_module="platform.agents")
    code = (
        "from agno.agent import Agent\n"
        "from platform.registry import models\n\n"
        'agent = Agent(id="a", model=models.mock_precise)\n'
    )
    lookup = Lookup(convention)
    lookup.add("model", "mock-precise", {"id": "mock-precise", "provider": "Agnostic", "name": "MockModel"})
    parsed = parse_source(code, convention=convention, resolver=lookup)
    model: Any = parsed.config["model"] if parsed.config else None
    assert model == {"id": "mock-precise", "provider": "Agnostic", "name": "MockModel"}


def test_components_in_lists_every_component_a_file_defines() -> None:
    code = (
        "from agno.agent import Agent\n"
        "from agno.team import Team\n\n"
        'first = Agent(id="first", name="First")\n'
        'second = Agent(name="Second")\n'
        'crew = Team(id="crew", members=[first, second])\n'
    )
    found = components_in(code)
    assert [(item.variable, item.kind, item.component_id) for item in found] == [
        ("first", "agent", "first"),
        ("second", "agent", None),
        ("crew", "team", "crew"),
    ]
    assert components_in("def broken(:\n") == []


def test_registry_convention_survives_json() -> None:
    convention = RegistryConvention(registry_module="platform.registry", namespaces={"tool": "toolbox"})
    restored = RegistryConvention.from_dict(json.loads(json.dumps(convention.as_dict())))
    assert restored == RegistryConvention(
        registry_module="platform.registry", namespaces={**RegistryConvention().namespaces, "tool": "toolbox"}
    )
    assert RegistryConvention.from_dict(None) == RegistryConvention()
    assert RegistryConvention.from_dict({"registry_module": "not a module", "keep_schema_names": "yes"}) == (
        RegistryConvention()
    )
