"""The ticket router as the Studio design draws it: the code Studio generates for its config is the design's code,
modulo formatting (both sides through ``ruff format`` with collapsed trailing commas and sorted imports)."""

import asyncio
import json
import subprocess
from pathlib import Path

from ruff.__main__ import find_ruff_bin

from agnostic_codegen import render
from agnostic_spec.v3_1 import parse

GOLDEN = Path(__file__).parents[1] / "golden" / "agno-3.1" / "prototype" / "ticket-router.json"

PROTOTYPE = """from agno.workflow import Workflow, Step, Parallel, Router, Condition, Loop
from app.agents import support_triage, billing_agent, kb_researcher, qa_reviewer
from app.teams import escalation_team
from app.functions import check_status, send_reply

ROUTE_BY_CATEGORY = (
    'input.contains("refund") || input.contains("invoice") ? "Billing"'
    ' : previous_step_content.contains("BUG") ? "Investigate"'
    ' : "Draft & review"'
)

investigate = Parallel(
    Step(name="Search KB", agent=kb_researcher),
    Step(name="Check status page", executor=check_status),
    name="Investigate",
)

draft_and_review = Loop(
    name="Draft & review",
    steps=[
        Step(name="Draft reply", agent=support_triage),
        Step(name="Review tone", agent=qa_reviewer),
    ],
    end_condition='last_step_content.contains("APPROVED")',
    max_iterations=3,
)

ticket_router = Workflow(
    id="ticket-router",
    steps=[
        Step(name="Classify ticket", agent=support_triage),
        Router(
            name="Route by category",
            selector=ROUTE_BY_CATEGORY,
            choices=[Step(name="Billing", agent=billing_agent), investigate, draft_and_review],
        ),
        Condition(
            name="Needs a human?",
            evaluator='previous_step_content.contains("ESCALATE")',
            steps=[Step(name="Escalate", team=escalation_team)],
            else_steps=[Step(name="Send reply", executor=send_reply)],
        ),
    ],
)
"""


def normalized(code: str) -> str:
    """Sorted imports, then ruff's layout with trailing commas no longer forcing one item per line."""
    ruff = find_ruff_bin()
    sorted_imports = subprocess.run(
        [ruff, "check", "--isolated", "--select=I", "--fix", "--exit-zero", "--quiet", "--stdin-filename=x.py", "-"],
        input=code.encode(),
        capture_output=True,
        check=True,
    ).stdout.decode()
    return subprocess.run(
        [
            ruff,
            "format",
            "--isolated",
            "--line-length=120",
            "--config=format.skip-magic-trailing-comma = true",
            "--stdin-filename=x.py",
            "-",
        ],
        input=sorted_imports.encode(),
        capture_output=True,
        check=True,
    ).stdout.decode()


def test_generated_code_is_the_prototype_modulo_formatting() -> None:
    config = parse("workflow", json.loads(GOLDEN.read_text(encoding="utf-8")))
    generated = asyncio.run(render(config)).code
    assert normalized(generated) == normalized(PROTOTYPE)


def test_the_selected_router_highlights_its_lines() -> None:
    config = parse("workflow", json.loads(GOLDEN.read_text(encoding="utf-8")))
    rendered = asyncio.run(render(config))
    router = rendered.spans["steps[1]"]
    lines = rendered.code.splitlines()[router.line - 1 : router.end_line]
    assert lines[0].strip() == "Router("
    assert lines[-1].strip() == "),"
    assert rendered.spans["steps[1].choices[1]"].line < router.line  # hoisted above the workflow
