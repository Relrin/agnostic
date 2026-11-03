"""Line-level differences between two generated files: gutter marks and a unified diff."""

from __future__ import annotations

import difflib
from typing import Literal

Mark = Literal["added", "modified"]


def line_marks(base: str, current: str) -> dict[int, Mark]:
    """1-based line numbers of ``current`` that are new or changed compared with ``base``."""
    marks: dict[int, Mark] = {}
    matcher = difflib.SequenceMatcher(a=base.splitlines(), b=current.splitlines(), autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            marks.update(dict.fromkeys(range(j1 + 1, j2 + 1), "added"))
        elif tag == "replace":
            changed = min(i2 - i1, j2 - j1)
            marks.update(dict.fromkeys(range(j1 + 1, j1 + changed + 1), "modified"))
            marks.update(dict.fromkeys(range(j1 + changed + 1, j2 + 1), "added"))
    return marks


def unified(base: str, current: str, *, from_label: str, to_label: str) -> str:
    return "".join(
        difflib.unified_diff(
            base.splitlines(keepends=True), current.splitlines(keepends=True), fromfile=from_label, tofile=to_label
        )
    )


def counts(base: str, current: str) -> tuple[int, int]:
    """(added, removed) lines."""
    added = removed = 0
    for line in difflib.ndiff(base.splitlines(), current.splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed
