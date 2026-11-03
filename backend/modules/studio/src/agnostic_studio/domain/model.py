"""Components, versions and the sidecar metadata Studio keeps next to AgentOS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

type Kind = Literal["agent", "team", "workflow"]
type EditableKind = Literal["agent", "team"]
type Stage = Literal["draft", "published"]
type Source = Literal["studio", "code"]

FAMILY: dict[Kind, str] = {"agent": "agents", "team": "teams", "workflow": "workflows"}


class StudioRuleError(Exception):
    """A request Studio refuses on its own terms (shown to the person as is)."""


@dataclass(frozen=True, slots=True)
class Version:
    component_id: str
    version: int
    stage: Stage
    label: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime | None
    config: dict[str, Any] | None
    links: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def tag(self, current: int | None) -> str:
        """``v3``, ``v3 · current`` or ``v4 draft``."""
        if self.stage == "draft":
            return f"v{self.version} draft"
        return f"v{self.version} · current" if self.version == current else f"v{self.version}"


@dataclass(frozen=True, slots=True)
class Component:
    id: str
    kind: Kind
    name: str
    description: str | None
    current_version: int | None
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None
    source: Source
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class ComponentMeta:
    instance_id: str
    component_id: str
    kind: Kind
    owner_group_id: str | None = None
    labels: tuple[str, ...] = ()
    last_known_current_version: int | None = None


@dataclass(frozen=True, slots=True)
class VersionMeta:
    instance_id: str
    component_id: str
    version: int
    author_id: str | None = None
    author_name: str | None = None
    updated_by: str | None = None
    updated_by_name: str | None = None
    updated_at: datetime | None = None
    notes: str | None = None
    change_summary: str | None = None
    based_on_version: int | None = None
    eval_status: str | None = None
    published_by: str | None = None
    published_by_name: str | None = None
    published_at: datetime | None = None
    promoted_from: dict[str, Any] | None = None


def latest(versions: list[Version]) -> Version | None:
    return max(versions, key=lambda item: item.version, default=None)


def open_draft(versions: list[Version]) -> Version | None:
    """The draft builders edit: the newest one."""
    return max((item for item in versions if item.stage == "draft"), key=lambda item: item.version, default=None)
