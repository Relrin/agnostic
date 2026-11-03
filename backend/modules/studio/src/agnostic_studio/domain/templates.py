"""Starting points for "New agent" and "New team". They reference no registry entry except the chosen model."""

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
)


def template(template_id: str) -> Template | None:
    return next((item for item in TEMPLATES if item.id == template_id), None)


def start_config(
    base: Mapping[str, Any], *, component_id: str, name: str, model: Mapping[str, Any] | None
) -> dict[str, Any]:
    config: dict[str, Any] = {"id": component_id, "name": name, **base}
    if model is not None:
        config["model"] = dict(model)
    return config
