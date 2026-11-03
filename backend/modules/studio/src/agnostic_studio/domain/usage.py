"""The reverse index: which components (and which of their versions) use a registry entry."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Use:
    """One component version referring to one registry entry."""

    entry_type: str
    entry_name: str
    component_id: str
    component_kind: str
    component_name: str
    version_tag: str
    """``v3``, ``v4 draft`` or ``code`` for a component defined in code."""


@dataclass(frozen=True, slots=True)
class UsedBy:
    component_id: str
    component_kind: str
    component_name: str
    versions: tuple[str, ...]

    @property
    def versions_text(self) -> str:
        """``v3 · v4 draft`` (empty for code components)."""
        return " · ".join(tag for tag in self.versions if tag != "code")


def index(uses: Iterable[Use]) -> dict[tuple[str, str], list[UsedBy]]:
    grouped: dict[tuple[str, str], dict[str, tuple[str, str, list[str]]]] = {}
    for use in uses:
        components = grouped.setdefault((use.entry_type, use.entry_name), {})
        _, _, tags = components.setdefault(use.component_id, (use.component_kind, use.component_name, []))
        if use.version_tag not in tags:
            tags.append(use.version_tag)
    return {
        key: [
            UsedBy(component_id, kind, name, tuple(sorted(tags, key=_tag_order)))
            for component_id, (kind, name, tags) in sorted(components.items())
        ]
        for key, components in grouped.items()
    }


def _tag_order(tag: str) -> tuple[int, int]:
    digits = "".join(character for character in tag if character.isdigit())
    return (0 if tag == "code" else 1, int(digits) if digits else 0)


@dataclass(frozen=True, slots=True)
class IndexEntry:
    entry_type: str
    name: str
    used_by: list[UsedBy]
    indexed_at: datetime
