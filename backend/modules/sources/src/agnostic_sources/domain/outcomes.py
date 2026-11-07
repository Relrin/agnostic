"""What an incoming change will do, said as a sentence for the person reading it.

The outcome is stored as data (``Outcome.as_dict``); the sentence is written when it is shown, because it depends on
who reads it ("next to your draft v8" or "next to Maya Chen's draft v8").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from agnostic_sources.domain.paths import compile_glob

type Action = Literal[
    "new_draft", "new_component", "noop", "conflict", "unparseable", "removed", "read_only", "unbound"
]


@dataclass(frozen=True, slots=True)
class Outcome:
    action: Action
    component_id: str | None = None
    kind: str | None = None
    version: int | None = None
    """The draft version the change becomes."""
    beside_version: int | None = None
    """Studio's open draft the new one sits next to (and merged with)."""
    beside_author_id: str | None = None
    beside_author_name: str | None = None
    matches_version: int | None = None
    auto_merged: list[str] = field(default_factory=list[str])
    conflict_paths: list[str] = field(default_factory=list[str])
    problems: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def of(cls, data: Mapping[str, Any]) -> Outcome:
        known = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        return cls(**known)


def sentence(outcome: Outcome, viewer_id: str | None = None) -> str:  # noqa: PLR0911
    name = outcome.component_id or "the component"
    beside = _beside(outcome, viewer_id)
    match outcome.action:
        case "new_draft":
            text = f"Becomes draft v{outcome.version} of {name}"
            return f"{text}, next to {beside}" if beside else text
        case "new_component":
            return f"Creates {name} as a new {outcome.kind or 'component'} (draft v1)"
        case "noop":
            return (
                f"Already matches v{outcome.matches_version} of {name}"
                if outcome.matches_version
                else (f"Already matches {name}")
            )
        case "conflict":
            where = (
                f"on {outcome.conflict_paths[0]}"
                if len(outcome.conflict_paths) == 1
                else f"on {len(outcome.conflict_paths)} fields"
            )
            return f"Conflicts with {beside or f'the draft of {name}'} {where}"
        case "unparseable":
            return f"Can't become a draft: {_count(outcome.problems, 'problem')} in the code"
        case "removed":
            return (
                f"The file was removed; pulling stops syncing it ({name} stays in Studio), committing writes it again"
            )
        case "read_only":
            return "Registry file: read-only, Studio reads the registry from the instance"
        case "unbound":
            return "Not mapped to an agent, team or workflow"


def _beside(outcome: Outcome, viewer_id: str | None) -> str | None:
    if outcome.beside_version is None:
        return None
    if viewer_id is not None and outcome.beside_author_id == viewer_id:
        return f"your draft v{outcome.beside_version}"
    if outcome.beside_author_name:
        return f"{outcome.beside_author_name}'s draft v{outcome.beside_version}"
    return f"draft v{outcome.beside_version}"


def _count(number: int, noun: str) -> str:
    return f"{'one' if number == 1 else number} {noun}{'' if number == 1 else 's'}"


def review_sentence(required: int, teams: Sequence[str]) -> str:
    """``1 review from Platform required``; ``No review required``."""
    if required <= 0:
        return "No review required"
    who = f" from {' or '.join(teams)}" if teams else ""
    return f"{required} review{'' if required == 1 else 's'}{who} required"


def team_label(handle: str) -> str:
    """``@northwind/platform`` → ``Platform``; ``platform-team`` → ``Platform team``."""
    name = handle.rsplit("/", 1)[-1].lstrip("@").replace("-", " ").replace("_", " ").strip()
    return name[:1].upper() + name[1:] if name else handle


def codeowners(text: str, path: str) -> list[str]:
    """The owners of ``path`` in a CODEOWNERS file (the last matching rule wins)."""
    owners: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *names = line.split()
        if _codeowners_match(pattern, path):
            owners = names
    return owners


def _codeowners_match(pattern: str, path: str) -> bool:
    anchored = pattern.startswith("/")
    pattern = pattern.lstrip("/")
    if pattern.endswith("/"):
        pattern += "**"
    elif "*" not in pattern and "." not in pattern.rsplit("/", 1)[-1]:
        pattern += "/**"
    candidates = [pattern] if anchored or "/" in pattern.rstrip("/*") else [pattern, f"**/{pattern}"]
    return any(compile_glob(candidate).fullmatch(path) for candidate in candidates)
