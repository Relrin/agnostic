"""Explanations next to a page's deterministic text, and drafts a person can insert.

Each kind names the facts it needs as tool calls (made as the asking person, exactly like a question's), what the
page may send along as ``material`` (a draft that isn't saved yet, a preview), and what the model writes back. The
page keeps showing its deterministic text; the generated one is labelled and never applied on its own.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from agnostic_assistant.domain.settings import Feature

type Output = Literal["text", "json", "expression"]

MAX_MATERIAL_CHARS = 20_000


class ExplainerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Gather:
    """A tool call made before the model runs.

    ``Gather("compare_trace", {"trace_id": "trace_id"})`` passes the subject's ``trace_id`` as the tool's ``trace_id``.
    """

    tool: str
    arguments: Mapping[str, str]
    unless_material: bool = False
    """Skip it when the page sent material instead (an unsaved draft)."""


@dataclass(frozen=True, slots=True)
class Explainer:
    kind: str
    feature: Feature
    task: str
    subject: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    gathers: tuple[Gather, ...] = ()
    material: bool = False
    output: Output = "text"
    label: str = "Explanation"

    def check(self, subject: Mapping[str, Any], material: object) -> None:
        missing = [key for key in self.subject if subject.get(key) in (None, "")]
        if missing:
            raise ExplainerError(f"{self.kind} needs {', '.join(missing)}.")
        unknown = set(subject) - set(self.subject) - set(self.optional)
        if unknown:
            raise ExplainerError(f"{self.kind} doesn't take {', '.join(sorted(unknown))}.")
        for key, value in subject.items():
            if not isinstance(value, str | int) or isinstance(value, bool):
                raise ExplainerError(f"{key} is a string or a number.")
        if material is not None:
            if not self.material:
                raise ExplainerError(f"{self.kind} reads its data itself; don't send material.")
            if len(json.dumps(material, default=str)) > MAX_MATERIAL_CHARS:
                raise ExplainerError(f"Material is limited to {MAX_MATERIAL_CHARS:,} characters.")

    def calls(self, subject: Mapping[str, Any], *, has_material: bool) -> list[tuple[str, dict[str, Any]]]:
        return [
            (gather.tool, {arg: subject[key] for arg, key in gather.arguments.items() if key in subject})
            for gather in self.gathers
            if not (gather.unless_material and has_material)
        ]


@dataclass(frozen=True, slots=True)
class Registry:
    kinds: Mapping[str, Explainer] = field(default_factory=dict[str, Explainer])

    def get(self, kind: str) -> Explainer:
        explainer = self.kinds.get(kind)
        if explainer is None:
            raise ExplainerError(f"Unknown explanation {kind!r}; use one of {', '.join(sorted(self.kinds))}.")
        return explainer


def subject_key(kind: str, subject: Mapping[str, Any], material: object) -> str:
    """Identifies "the same explanation" so a page reopening reuses the last one instead of paying again."""
    canonical = json.dumps([kind, dict(subject), material], sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:40]


_DIFF = Gather(
    "diff_versions", {"component_id": "component_id", "from_version": "from_version", "to_version": "to_version"}
)
_VERSIONS = ("component_id", "from_version", "to_version")

EXPLAINERS = Registry(
    {
        explainer.kind: explainer
        for explainer in (
            Explainer(
                "trace.diagnosis",
                "summaries",
                "Rewrite the comparison's diagnosis for a person in one or two sentences. Keep every fact from it "
                "(span names, durations, versions, errors) and add none that the data doesn't show. Lead with what "
                "changed and what it caused.",
                subject=("trace_id",),
                gathers=(Gather("compare_trace", {"trace_id": "trace_id"}),),
                label="Diagnosis",
            ),
            Explainer(
                "eval.insight",
                "summaries",
                "In two sentences, say what changed between the two evaluations: which cases the newer version "
                "fixes and which it breaks (by case number), and the pattern behind them.",
                subject=("evaluation_id", "compare_to_id"),
                gathers=(
                    Gather("list_eval_results", {"evaluation_id": "evaluation_id", "compare_to_id": "compare_to_id"}),
                ),
                label="Insight",
            ),
            Explainer(
                "memory.optimization",
                "summaries",
                "In two or three sentences, explain what this memory optimization preview would do for this user: "
                "what gets merged, what is kept, what detail could be lost, and the tokens saved. Don't recommend "
                "applying it; the person decides.",
                subject=("user_id",),
                material=True,
                label="What this would change",
            ),
            Explainer(
                "studio.version_summary",
                "summaries",
                "Summarize the change between the two versions in one sentence for a version list, then at most "
                "three short bullet points on how the behavior changes.",
                subject=_VERSIONS,
                gathers=(_DIFF,),
                label="Change summary",
            ),
            Explainer(
                "studio.commit_message",
                "suggestions",
                "Write a git commit message for these changes: an imperative subject line under 72 characters, a "
                "blank line, then a short body listing what changed. Output only the message.",
                subject=("source_id",),
                material=True,
                label="Commit message",
            ),
            Explainer(
                "studio.release_notes",
                "suggestions",
                "Write release notes for publishing this version: two to four bullet points on what changes for "
                "people using it. Output only the notes.",
                subject=("component_id", "version"),
                material=True,
                label="Release notes",
            ),
            Explainer(
                "studio.config_explanation",
                "summaries",
                "Explain what this configuration does in plain words: what the component is for, the model and "
                "its settings, the instructions in short, its tools or members or steps, and anything unusual. "
                "Use a short paragraph and a few bullet points.",
                subject=("component_id",),
                optional=("version",),
                gathers=(
                    Gather(
                        "get_component_config",
                        {"component_id": "component_id", "version": "version"},
                        unless_material=True,
                    ),
                ),
                material=True,
                label="About this configuration",
            ),
            Explainer(
                "audit.diff",
                "summaries",
                "Summarize this audit event's change in plain words in two or three sentences: what was changed, "
                "the before and after that matter, and who is affected.",
                subject=("event_id",),
                gathers=(Gather("search_audit", {"event_id": "event_id"}),),
                label="Summary",
            ),
            Explainer(
                "studio.cel",
                "suggestions",
                "Write one CEL expression that does what the description says. Use only the variables and "
                "functions in the material. Output only the expression: no code fences, no explanation.",
                subject=("description",),
                material=True,
                output="expression",
                label="CEL suggestion",
            ),
            Explainer(
                "access.question",
                "assistant",
                "Turn the question into a permission check. Reply with only a JSON object with the keys person "
                "(an id from the material's people, or null), resource, verb, component (or null) and instance (a "
                "slug from the material's instances, or null). Use only values from the material.",
                subject=("question",),
                material=True,
                output="json",
                label="Permission check",
            ),
        )
    }
)
