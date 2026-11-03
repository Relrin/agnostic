"""Field-level differences between two config documents.

Lists are compared item by item: instructions by text, tools by name, members by component, so reordering or
inserting one item reads as one change instead of a cascade.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

type Op = Literal["added", "removed", "changed"]


@dataclass(frozen=True, slots=True)
class FieldChange:
    path: str
    op: Op
    before: Any = None
    after: Any = None

    @property
    def field(self) -> str:
        """The top-level field: ``instructions`` for ``instructions[2]``."""
        return self.path.split("[", 1)[0].split(".", 1)[0]


@dataclass(frozen=True, slots=True)
class DiffCounts:
    added: int
    changed: int
    removed: int

    @property
    def total(self) -> int:
        return self.added + self.changed + self.removed


def diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[FieldChange]:
    changes: list[FieldChange] = []
    for key in _keys(before, after):
        changes.extend(_compare(key, before.get(key, _MISSING), after.get(key, _MISSING)))
    return changes


def counts(changes: Sequence[FieldChange]) -> DiffCounts:
    return DiffCounts(
        added=sum(1 for change in changes if change.op == "added"),
        changed=sum(1 for change in changes if change.op == "changed"),
        removed=sum(1 for change in changes if change.op == "removed"),
    )


def previous_values(changes: Sequence[FieldChange]) -> dict[str, Any]:
    """Field path → its value in the base version, for "Changed from X in vN" hints."""
    return {change.path: change.before for change in changes if change.op == "changed"}


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


_MISSING: Any = _Missing()


def _keys(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    keys = list(after)
    keys.extend(key for key in before if key not in after)
    return keys


def _compare(path: str, before: Any, after: Any) -> list[FieldChange]:  # noqa: ANN401, PLR0911
    if before is _MISSING and after is _MISSING:
        return []
    if before is _MISSING:
        return [FieldChange(path, "added", after=after)]
    if after is _MISSING:
        return [FieldChange(path, "removed", before=before)]
    if before == after:
        return []
    if isinstance(before, list) and isinstance(after, list):
        return _lists(path, before, after)  # pyright: ignore[reportUnknownArgumentType]
    if isinstance(before, dict) and isinstance(after, dict) and not _is_ref(before) and not _is_ref(after):  # pyright: ignore[reportUnknownArgumentType]
        changes: list[FieldChange] = []
        for key in _keys(before, after):  # pyright: ignore[reportUnknownArgumentType]
            changes.extend(_compare(f"{path}.{key}", before.get(key, _MISSING), after.get(key, _MISSING)))  # pyright: ignore[reportUnknownMemberType]
        return changes
    return [FieldChange(path, "changed", before=before, after=after)]


def _lists(path: str, before: list[Any], after: list[Any]) -> list[FieldChange]:
    keys_before = [identity(item) for item in before]
    keys_after = [identity(item) for item in after]
    changes: list[FieldChange] = []
    matcher = difflib.SequenceMatcher(a=keys_before, b=keys_after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            changes.extend(
                FieldChange(f"{path}[{j1 + offset}]", "changed", before[i1 + offset], after[j1 + offset])
                for offset in range(i2 - i1)
                if before[i1 + offset] != after[j1 + offset]
            )
        elif tag == "insert":
            changes.extend(FieldChange(f"{path}[{j}]", "added", after=after[j]) for j in range(j1, j2))
        elif tag == "delete":
            changes.extend(FieldChange(f"{path}[{i}]", "removed", before=before[i]) for i in range(i1, i2))
        else:
            paired = min(i2 - i1, j2 - j1)
            changes.extend(
                FieldChange(f"{path}[{j1 + k}]", "changed", before[i1 + k], after[j1 + k]) for k in range(paired)
            )
            changes.extend(FieldChange(f"{path}[{j}]", "added", after=after[j]) for j in range(j1 + paired, j2))
            changes.extend(FieldChange(f"{path}[{i}]", "removed", before=before[i]) for i in range(i1 + paired, i2))
    return changes


def identity(item: Any) -> str:  # noqa: ANN401
    """What makes a list item the same item: a tool's name, a member's component, otherwise its whole value."""
    if isinstance(item, dict):
        for key in ("name", "agent_id", "team_id", "id"):
            value = item.get(key)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(value, str):
                return f"{key}:{value}"
    return json.dumps(item, sort_keys=True, default=str)


def _is_ref(value: Mapping[str, Any]) -> bool:
    """Registry references change as a whole (a model is swapped, not edited)."""
    return ("id" in value and "provider" in value) or set(value) <= {"name", "registry_id"}
