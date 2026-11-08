"""Starting points for "New agent", "New team" and "New workflow".

They reference no registry entry except the chosen model; workflow templates leave their steps' executors to pick.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agnostic_studio.domain.model import EditableKind


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    kind: EditableKind
    label: str
    description: str
    config: Mapping[str, Any] = field(default_factory=dict[str, Any])


TEMPLATES: tuple[Template, ...] = (
    Template("blank-agent", "agent", "Blank agent", "An agent with a model and nothing else.", {"markdown": True}),
    Template(
        "support-agent",
        "agent",
        "Support agent",
        "Triages customer requests: history and summaries on, Markdown answers.",
        {
            "instructions": [
                "Classify the request by product area and urgency.",
                "Answer from what you know; say when a teammate needs to step in.",
            ],
            "add_history_to_context": True,
            "num_history_runs": 5,
            "enable_session_summaries": True,
            "markdown": True,
        },
    ),
    Template(
        "researcher",
        "agent",
        "Researcher",
        "Answers questions with sources; searches knowledge when one is attached.",
        {
            "instructions": ["Cite a source for every claim.", "Say so when the sources disagree."],
            "markdown": True,
        },
    ),
    Template(
        "coding-agent",
        "agent",
        "Coding agent",
        "Pi in a Docker sandbox; files written to outputs/ become artefacts.",
        {
            "instructions": [
                "Work in the current directory; it is a fresh sandbox for this session.",
                "Write every file the user should get into outputs/.",
                "End with a short summary of what you changed.",
            ],
            "model": {"id": "mock-coder", "name": "MockModel", "provider": "Agnostic"},
            "metadata": {"agnostic": {"coding_agent": {"harness": "pi"}}},
        },
    ),
    Template("blank-team", "team", "Blank team", "A team in coordinate mode, without members.", {"mode": "coordinate"}),
    Template(
        "coordinate-team",
        "team",
        "Coordinating team",
        "A leader splits the request, members answer their parts, the leader merges them.",
        {
            "mode": "coordinate",
            "instructions": [
                "Split the question into parts members can answer.",
                "Cite a source for every claim in the final answer.",
            ],
            "markdown": True,
        },
    ),
    Template("blank-workflow", "workflow", "Blank workflow", "A workflow without steps: add them on the canvas.", {}),
    Template(
        "triage-and-route",
        "workflow",
        "Triage and route",
        "Classify the input, then route it with a CEL selector to one of two steps.",
        {
            "steps": [
                {"type": "Step", "name": "Classify"},
                {
                    "type": "Router",
                    "name": "Route",
                    "selector": 'previous_step_content.contains("BILLING") ? "Billing" : "Answer"',
                    "choices": [{"type": "Step", "name": "Billing"}, {"type": "Step", "name": "Answer"}],
                },
            ]
        },
    ),
)


def template(template_id: str) -> Template | None:
    return next((item for item in TEMPLATES if item.id == template_id), None)


def start_config(
    base: Mapping[str, Any],
    *,
    component_id: str,
    name: str,
    model: Mapping[str, Any] | None,
    kind: EditableKind = "agent",
) -> dict[str, Any]:
    """A template's config with the new id and name, and the chosen model (a workflow has none of its own)."""
    config: dict[str, Any] = {"id": component_id, "name": name, **base}
    if model is not None and kind != "workflow":
        config["model"] = dict(model)
    return config
