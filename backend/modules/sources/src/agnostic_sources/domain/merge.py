"""Three-way merge of config documents, field by field, with the last synced version as the base.

``ours`` is Studio's draft and ``theirs`` the repository's file. A field changed on one side only takes that change; a
field changed the same way on both is fine; a field changed differently on both is a conflict at its path
(``instructions[2]``, ``steps[1].selector``). Lists whose items carry a name or id (workflow steps, router choices,
team members) are aligned by it; other lists merge by position, diff3-style, so an instruction added on one side and
another edited on the other both survive.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Final, cast


class _Missing:
    """A field that isn't there (configs leave defaults out)."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:  # noqa: PYI034
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Final = _Missing()
IDENTITY_KEYS: Final = ("step_id", "name", "id", "component_id", "agent_id", "team_id", "workflow_id")

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


@dataclass(frozen=True, slots=True)
class FieldConflict:
    path: str
    base: Any
    ours: Any
    theirs: Any


@dataclass(slots=True)
class MergeResult:
    merged: dict[str, Any]
    auto_merged: list[str] = field(default_factory=list[str])
    """Paths Studio changed and the repository didn't: carried into the merged document."""
    conflicts: list[FieldConflict] = field(default_factory=list[FieldConflict])

    @property
    def clean(self) -> bool:
        return not self.conflicts


def format_path(parts: Sequence[str | int]) -> str:
    out = ""
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else part)
    return out


def parse_path(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for name, index in _TOKEN.findall(path):
        parts.append(int(index) if index else name)
    if format_path(parts) != path:
        msg = f"{path!r} isn't a field path"
        raise ValueError(msg)
    return parts


def get_at(document: Any, path: str) -> Any:  # noqa: ANN401
    current: Any = document
    for part in parse_path(path):
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(cast("list[Any]", current)):
                return MISSING
            current = cast("list[Any]", current)[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return MISSING
            current = cast("dict[str, Any]", current)[part]
    return current


def set_at(document: dict[str, Any], path: str, value: Any) -> dict[str, Any]:  # noqa: ANN401
    """A copy of ``document`` with ``value`` at ``path`` (``MISSING`` removes it)."""
    parts = parse_path(path)
    root: dict[str, Any] = json.loads(json.dumps(document))
    current: Any = root
    for position, part in enumerate(parts):
        last = position == len(parts) - 1
        if isinstance(part, int):
            items = cast("list[Any]", current)
            if last:
                if value is MISSING:
                    del items[part]
                elif part == len(items):
                    items.append(value)
                else:
                    items[part] = value
                return root
            current = items[part]
            continue
        mapping = cast("dict[str, Any]", current)
        if last:
            if value is MISSING:
                mapping.pop(part, None)
            else:
                mapping[part] = value
            return root
        nxt = parts[position + 1]
        if part not in mapping:
            mapping[part] = [] if isinstance(nxt, int) else {}
        current = mapping[part]
    return root


def apply_resolutions(document: dict[str, Any], resolutions: Mapping[str, Any]) -> dict[str, Any]:
    """Set every resolved conflict's value; paths that index lists are applied from the highest index down."""

    def order(path: str) -> list[tuple[int, str | int]]:
        return [(1, part) if isinstance(part, int) else (0, part) for part in parse_path(path)]

    for path, value in sorted(resolutions.items(), key=lambda item: order(item[0]), reverse=True):
        document = set_at(document, path, value)
    return document


def three_way(base: Mapping[str, Any] | None, ours: Mapping[str, Any], theirs: Mapping[str, Any]) -> MergeResult:
    result = MergeResult(merged={})
    merged = _merge(dict(base or {}), dict(ours), dict(theirs), [], result)
    result.merged = cast("dict[str, Any]", merged) if isinstance(merged, dict) else {}
    return result


def changed_paths(before: Any, after: Any, parts: list[str | int] | None = None) -> list[str]:  # noqa: ANN401
    """The leaf paths that differ between two documents (lists of different length count as one change)."""
    parts = parts or []
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        found: list[str] = []
        b, a = cast("dict[str, Any]", before), cast("dict[str, Any]", after)
        for key in _keys(b, a):
            found.extend(changed_paths(b.get(key, MISSING), a.get(key, MISSING), [*parts, key]))
        return found
    if isinstance(before, list) and isinstance(after, list):
        b_list, a_list = cast("list[Any]", before), cast("list[Any]", after)
        if len(b_list) == len(a_list):
            found = []
            for index, (left, right) in enumerate(zip(b_list, a_list, strict=True)):
                found.extend(changed_paths(left, right, [*parts, index]))
            return found
    return [format_path(parts)]


# ---------------------------------------------------------------- internals


def _keys(*documents: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    for document in documents:
        keys.extend(key for key in document if key not in keys)
    return keys


def _merge(base: Any, ours: Any, theirs: Any, parts: list[str | int], result: MergeResult) -> Any:  # noqa: ANN401
    if ours == theirs:
        return ours
    if ours == base:
        return theirs
    if theirs == base:
        if ours is not MISSING or base is not MISSING:
            result.auto_merged.append(format_path(parts))
        return ours
    if isinstance(ours, dict) and isinstance(theirs, dict):
        base_dict = cast("dict[str, Any]", base) if isinstance(base, dict) else {}
        merged: dict[str, Any] = {}
        o, t = cast("dict[str, Any]", ours), cast("dict[str, Any]", theirs)
        for key in _keys(t, o):
            value = _merge(base_dict.get(key, MISSING), o.get(key, MISSING), t.get(key, MISSING), [*parts, key], result)
            if value is not MISSING:
                merged[key] = value
        return cast("Any", merged)
    if isinstance(ours, list) and isinstance(theirs, list):
        base_list = cast("list[Any]", base) if isinstance(base, list) else []
        return _merge_list(base_list, cast("list[Any]", ours), cast("list[Any]", theirs), parts, result)
    result.conflicts.append(FieldConflict(format_path(parts), base, ours, theirs))
    return cast("Any", ours)


def _identity(*lists: list[Any]) -> str | None:
    """The key every item of every list has, unique within each list (``name`` for steps)."""
    items = [item for values in lists for item in values]
    if not items or not all(isinstance(item, dict) for item in items):
        return None
    for key in IDENTITY_KEYS:
        if all(isinstance(cast("dict[str, Any]", item).get(key), str) for item in items) and all(
            len({cast("dict[str, Any]", item)[key] for item in values}) == len(values) for values in lists
        ):
            return key
    return None


def _merge_list(
    base: list[Any], ours: list[Any], theirs: list[Any], parts: list[str | int], result: MergeResult
) -> Any:  # noqa: ANN401
    key = _identity(base, ours, theirs)
    if key is not None:
        return _merge_keyed(key, base, ours, theirs, parts, result)
    return _merge_positional(base, ours, theirs, parts, result)


def _merge_keyed(
    key: str, base: list[Any], ours: list[Any], theirs: list[Any], parts: list[str | int], result: MergeResult
) -> Any:  # noqa: ANN401
    def index(values: list[Any]) -> dict[str, Any]:
        return {cast("dict[str, Any]", item)[key]: item for item in values}

    b, o, t = index(base), index(ours), index(theirs)

    def moved(side: list[str]) -> bool:
        return [name for name in side if name in b] != [name for name in b if name in side]

    ours_moved, theirs_moved = moved(list(o)), moved(list(t))
    if ours_moved and theirs_moved and [name for name in o if name in t] != [name for name in t if name in o]:
        result.conflicts.append(FieldConflict(format_path(parts), base, ours, theirs))
        return ours
    first, second = (list(o), list(t)) if ours_moved else (list(t), list(o))
    order = first + [name for name in second if name not in first]
    merged: list[Any] = []
    for name in order:
        value = _merge(b.get(name, MISSING), o.get(name, MISSING), t.get(name, MISSING), [*parts, len(merged)], result)
        if value is not MISSING:
            merged.append(value)
    return merged


@dataclass(frozen=True, slots=True)
class _Hunk:
    start: int
    end: int
    items: list[Any]
    side: str


def _hunks(base: list[Any], side: list[Any], name: str) -> list[_Hunk]:
    matcher = SequenceMatcher(a=[_text(item) for item in base], b=[_text(item) for item in side], autojunk=False)
    return [_Hunk(i1, i2, side[j1:j2], name) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]


def _merge_positional(  # noqa: C901
    base: list[Any], ours: list[Any], theirs: list[Any], parts: list[str | int], result: MergeResult
) -> Any:  # noqa: ANN401
    hunks = sorted([*_hunks(base, ours, "ours"), *_hunks(base, theirs, "theirs")], key=lambda h: (h.start, h.end))
    groups: list[list[_Hunk]] = []
    for hunk in hunks:
        if groups and _overlaps(groups[-1], hunk):
            groups[-1].append(hunk)
        else:
            groups.append([hunk])
    merged: list[Any] = []
    conflicts: list[FieldConflict] = []
    auto: list[str] = []
    position = 0
    for group in groups:
        start = min(h.start for h in group)
        end = max(h.end for h in group)
        merged.extend(base[position:start])
        position = end
        sides = {h.side for h in group}
        ours_items = _apply(base, start, end, [h for h in group if h.side == "ours"])
        theirs_items = _apply(base, start, end, [h for h in group if h.side == "theirs"])
        if sides == {"theirs"} or ours_items == theirs_items:
            merged.extend(theirs_items)
            continue
        if sides == {"ours"}:
            auto.append(format_path([*parts, len(merged)]))
            merged.extend(ours_items)
            continue
        if end - start == len(ours_items) == len(theirs_items):
            for offset in range(end - start):
                left, right, original = ours_items[offset], theirs_items[offset], base[start + offset]
                if left == right:
                    merged.append(left)
                    continue
                path = [*parts, len(merged)]
                if right == original:
                    auto.append(format_path(path))
                    merged.append(left)
                elif left == original:
                    merged.append(right)
                else:
                    conflicts.append(FieldConflict(format_path(path), original, left, right))
                    merged.append(left)
            continue
        result.conflicts.append(FieldConflict(format_path(parts), base, ours, theirs))
        return ours
    merged.extend(base[position:])
    result.conflicts.extend(conflicts)
    result.auto_merged.extend(auto)
    return merged


def _overlaps(group: list[_Hunk], hunk: _Hunk) -> bool:
    for other in group:
        if max(other.start, hunk.start) < min(other.end, hunk.end):
            return True
        if other.start == hunk.start:
            return True
        if other.start == other.end and hunk.start < other.start < hunk.end:
            return True
        if hunk.start == hunk.end and other.start < hunk.start < other.end:
            return True
    return False


def _apply(base: list[Any], start: int, end: int, hunks: list[_Hunk]) -> list[Any]:
    out: list[Any] = []
    position = start
    for hunk in sorted(hunks, key=lambda h: (h.start, h.end)):
        out.extend(base[position : hunk.start])
        out.extend(hunk.items)
        position = hunk.end
    out.extend(base[position:end])
    return out


def _text(value: Any) -> str:  # noqa: ANN401
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
