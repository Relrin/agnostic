"""Form edits applied to existing code: only the changed arguments move, comments and formatting stay, and the
result must read back as the edited config."""

import copy
import json
from pathlib import Path
from typing import Any

from agnostic_codegen import Lookup, parse_source, transform
from agnostic_spec.v3_1 import parse
from tests.unit.test_prototype_ticket_router import PROTOTYPE

GOLDEN = Path(__file__).parents[1] / "golden" / "agno-3.1"
TRIAGE = parse("agent", json.loads((GOLDEN / "agents" / "support-triage.json").read_text(encoding="utf-8")))
PROTOTYPE_CONFIG = parse(
    "workflow", json.loads((GOLDEN / "prototype" / "ticket-router.json").read_text(encoding="utf-8"))
)

HUMAN = '''"""Support triage, hand-tuned."""

import app.registry as registry
from agno.agent import Agent
from app.registry import models as m

# Keep the instructions short: the model is small.
support_triage = Agent(
    id="support-triage",
    name="support-triage",
    description="Classifies incoming tickets and answers simple ones.",
    model=m.agnostic_mock,  # the default preset
    instructions="Triage the ticket: answer from the help center when you can, otherwise hand off. "
    "Refunds go through refund_customer, which a human approves.",
    tools=[
        registry.tools.lookup_order,  # order status
        registry.tools.search_knowledge,
        registry.tools.refund_customer,  # needs approval
    ],
    add_search_knowledge_instructions=True,
    num_history_runs=3,
    markdown=True,
    store_events=True,
    pre_hooks=[check_input],
)
'''


def lookup() -> Lookup:
    found = Lookup().learn([TRIAGE, PROTOTYPE_CONFIG])
    found.add("schema", "TriageResult", "TriageResult")
    found.add("agent", "web-researcher", "web-researcher")
    return found


def edited(code: str, kind: str) -> dict[str, Any]:
    parsed = parse_source(code, kind=kind, resolver=lookup())  # pyright: ignore[reportArgumentType]
    assert parsed.config is not None
    return copy.deepcopy(parsed.config)


def test_agent_edits_keep_comments_and_layout() -> None:
    after = edited(HUMAN, "agent")
    tools = after["tools"]
    after["tools"] = [tools[2], tools[0]]
    after["markdown"] = False
    after["description"] = "Classifies tickets."
    after["output_schema"] = "TriageResult"
    result = transform(HUMAN, after, kind="agent", resolver=lookup())
    assert result.equivalent, result.diagnostics
    assert result.changed == ["description", "markdown", "output_schema", "tools"]
    code = result.code
    assert code.startswith('"""Support triage, hand-tuned."""\n\nimport app.registry as registry\n')
    assert "# Keep the instructions short: the model is small." in code
    assert "    model=m.agnostic_mock,  # the default preset\n" in code
    assert '    "Refunds go through refund_customer, which a human approves.",\n' in code
    assert (
        "    tools=[\n"
        "        registry.tools.refund_customer,  # needs approval\n"
        "        registry.tools.lookup_order,  # order status\n"
        "    ],\n"
    ) in code
    assert "markdown" not in code
    assert "    output_schema=registry.schemas.TriageResult,\n    store_events=True,\n" in code
    assert "pre_hooks=[check_input]" in code  # code-owned, untouched


def test_code_owned_fields_refuse_edits() -> None:
    after = edited(HUMAN, "agent")
    after["pre_hooks"] = []
    result = transform(HUMAN, after, kind="agent", resolver=lookup())
    assert not result.equivalent
    assert result.code == HUMAN
    assert result.diagnostics[-1].code == "transform_refused"


def test_new_imports_are_added_and_unused_ones_removed() -> None:
    code = (
        "from agno.agent import Agent\n"
        "from app.registry import tools\n\n"
        "support_triage = Agent(\n"
        '    id="support-triage",\n'
        "    tools=[tools.lookup_order],\n"
        ")\n"
    )
    after = edited(code, "agent")
    after.pop("tools")
    after["model"] = TRIAGE.dump()["model"]
    result = transform(code, after, kind="agent", resolver=lookup())
    assert result.equivalent, result.diagnostics
    assert "from app.registry import models\n" in result.code
    assert "import tools" not in result.code
    assert "    model=models.agnostic_mock,\n" in result.code


def test_workflow_edits_reach_helper_variables() -> None:
    after = edited(PROTOTYPE, "workflow")
    investigate = after["steps"][1]["choices"][1]
    investigate["steps"][0]["name"] = "Search the KB"
    investigate["steps"].append({"type": "Step", "name": "Search the web", "agent_id": "web-researcher"})
    after["steps"][1]["choices"][2]["max_iterations"] = 5
    after["steps"][1]["selector"] = after["steps"][1]["selector"].replace('"BUG"', '"ERROR"')
    after["steps"][2]["else_steps"][0]["max_retries"] = 1
    result = transform(PROTOTYPE, after, kind="workflow", resolver=lookup())
    assert result.equivalent, result.diagnostics
    code = result.code
    assert (
        "ROUTE_BY_CATEGORY = (\n"
        '    \'input.contains("refund") || input.contains("invoice") ? "Billing"\'\n'
        '    \' : previous_step_content.contains("ERROR") ? "Investigate"\'\n'
        "    ' : \"Draft & review\"'\n"
        ")\n"
    ) in code
    assert (
        "investigate = Parallel(\n"
        '    Step(name="Search the KB", agent=kb_researcher),\n'
        '    Step(name="Check status page", executor=check_status),\n'
        '    Step(name="Search the web", agent=web_researcher),\n'
        '    name="Investigate",\n'
        ")\n"
    ) in code
    assert "    max_iterations=5,\n" in code
    assert 'else_steps=[Step(name="Send reply", executor=send_reply, max_retries=1)],' in code
    assert 'choices=[Step(name="Billing", agent=billing_agent), investigate, draft_and_review],' in code


def test_workflow_structure_changes() -> None:
    after = edited(PROTOTYPE, "workflow")
    condition = after.pop("steps")[2]
    after["steps"] = [condition, *edited(PROTOTYPE, "workflow")["steps"][:2]]
    after["steps"][0]["type"] = "Condition"
    result = transform(PROTOTYPE, after, kind="workflow", resolver=lookup())
    assert result.equivalent, result.diagnostics
    assert result.code.index('name="Needs a human?"') < result.code.index('name="Classify ticket"')

    removed = edited(PROTOTYPE, "workflow")
    removed["steps"][1]["choices"].pop(0)
    removed["steps"][1]["selector"] = '"Investigate"'
    result = transform(PROTOTYPE, removed, kind="workflow", resolver=lookup())
    assert result.equivalent, result.diagnostics
    assert "choices=[investigate, draft_and_review]," in result.code

    swapped = edited(PROTOTYPE, "workflow")
    swapped["steps"][0] = {"type": "Steps", "name": "Prepare", "steps": [swapped["steps"][0]]}
    result = transform(PROTOTYPE, swapped, kind="workflow", resolver=lookup())
    assert result.equivalent, result.diagnostics
    assert "Steps(" in result.code
    assert "from agno.workflow import Steps, Workflow, Step, Parallel, Router, Condition, Loop\n" in result.code


def test_nothing_to_do() -> None:
    result = transform(PROTOTYPE, edited(PROTOTYPE, "workflow"), kind="workflow", resolver=lookup())
    assert result.equivalent
    assert result.code == PROTOTYPE
    assert result.changed == []
