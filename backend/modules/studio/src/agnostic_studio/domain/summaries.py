"""Sentences Studio writes about versions: what changed, and what publishing will do."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agnostic_studio.domain.diff import FieldChange

WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
ITEM_NOUNS = {"instructions": "instruction", "tools": "tool", "members": "member"}
MAX_TEXT = 40


def number(count: int) -> str:
    return WORDS[count] if 0 <= count < len(WORDS) else str(count)


def display(value: Any) -> str:  # noqa: ANN401, PLR0911
    """A short human form of a config value: a model's id, a tool's name, ``on``/``off``."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "none"
    if isinstance(value, dict):
        for key in ("id", "name", "agent_id", "team_id", "registry_id"):
            item = value.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(item, str):
                return item
        return "{…}"
    if isinstance(value, list):
        return f"{len(value)} items"  # pyright: ignore[reportUnknownArgumentType]
    if isinstance(value, str):
        text = value if len(value) <= MAX_TEXT else f"{value[: MAX_TEXT - 1]}…"
        return f"“{text}”" if " " in text else text
    return str(value)


def change_summary(changes: Sequence[FieldChange]) -> str:
    """``temperature 0.7 → 0.2, one new instruction`` (deterministic, in field order)."""
    if not changes:
        return "No changes"
    phrases: list[str] = []
    seen: set[str] = set()
    for change in changes:
        field = change.field
        if field in seen:
            continue
        if field in ITEM_NOUNS and change.path != field:
            seen.add(field)
            phrases.extend(_items(field, [item for item in changes if item.field == field]))
            continue
        if change.path != field:
            seen.add(field)
            phrases.append(f"{field} changed")
            continue
        phrases.append(_scalar(change))
    return ", ".join(phrases)


def _items(field: str, changes: Sequence[FieldChange]) -> list[str]:
    noun = ITEM_NOUNS[field]
    phrases: list[str] = []
    added = [change for change in changes if change.op == "added"]
    removed = [change for change in changes if change.op == "removed"]
    changed = [change for change in changes if change.op == "changed"]
    if added:
        if field != "instructions" and len(added) == 1:
            phrases.append(f"{noun} {display(added[0].after)} added")
        else:
            phrases.append(f"{number(len(added))} new {_plural(noun, len(added))}")
    if removed:
        if field != "instructions" and len(removed) == 1:
            phrases.append(f"{noun} {display(removed[0].before)} removed")
        else:
            phrases.append(f"{number(len(removed))} {_plural(noun, len(removed))} removed")
    if changed:
        verb = "reworded" if field == "instructions" else "changed"
        phrases.append(f"{number(len(changed))} {_plural(noun, len(changed))} {verb}")
    return phrases


def _scalar(change: FieldChange) -> str:
    if change.op == "added":
        return f"{change.path} {display(change.after)}" if isinstance(change.after, bool) else f"{change.path} set"
    if change.op == "removed":
        return f"{change.path} removed"
    return f"{change.path} {display(change.before)} → {display(change.after)}"


def _plural(noun: str, count: int) -> str:
    return noun if count == 1 else f"{noun}s"


def publish_outcome(version: int, instance: str, previous: int | None) -> str:
    replaces = f", replacing v{previous}" if previous is not None else ""
    return f"v{version} becomes current on {instance}{replaces}; the API serves it from the next request."


def rollback_outcome(version: int, instance: str, previous: int | None) -> str:
    was = f" instead of v{previous}" if previous is not None else ""
    return f"v{version} becomes current on {instance}{was}; the API serves it from the next request."


def audit_lines(changes: Sequence[FieldChange]) -> list[dict[str, str]]:
    """The audit diff shape the audit log renders (``op`` add/remove/change with a text line)."""
    ops = {"added": "add", "removed": "remove", "changed": "change"}
    lines: list[dict[str, str]] = []
    for change in changes:
        if change.op == "changed":
            text = f"{change.path}: {display(change.before)} → {display(change.after)}"
        elif change.op == "added":
            text = f"{change.path}: {display(change.after)}"
        else:
            text = f"{change.path}: {display(change.before)}"
        lines.append({"op": ops[change.op], "text": text})
    return lines
