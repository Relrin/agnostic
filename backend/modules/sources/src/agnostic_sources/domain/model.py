"""Connections, sources and what moves between a repository and Studio."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

type Provider = Literal["github", "gitlab", "gitea", "forgejo", "local"]
type AuthKind = Literal["github_app", "token", "deploy_key", "local"]
type Access = Literal["read_write", "read_only"]
type TargetKind = Literal["agents", "teams", "workflows", "registry", "ignored"]
type PullMode = Literal["on_demand", "on_push_as_drafts"]
type PublishMode = Literal["open_pr", "commit_direct", "no_write_back"]
type SourceStatus = Literal["setup", "scanning", "ready", "active", "failed", "over_quota"]
type Direction = Literal["incoming", "outgoing"]
type ChangeStatus = Literal["pending", "pulled", "committing", "committed", "noop", "superseded", "failed"]
type ConflictStatus = Literal["open", "resolved", "superseded"]
type Resolution = Literal["keep_studio", "keep_repo", "merged"]
type PullRequestStatus = Literal["open", "merged", "closed"]
type ComponentKind = Literal["agent", "team", "workflow"]

KIND_OF_TARGET: dict[str, ComponentKind] = {"agents": "agent", "teams": "team", "workflows": "workflow"}
PROVIDER_LABEL: dict[str, str] = {
    "github": "GitHub",
    "gitlab": "GitLab",
    "gitea": "Gitea",
    "forgejo": "Forgejo",
    "local": "Local folder",
}


class SourceRuleError(Exception):
    """A request the sources module refuses on its own terms (shown to the person as is)."""


@dataclass(frozen=True, slots=True)
class Connection:
    """How Agnostic reaches a git host (org-wide); its secrets live sealed next to it, never in this object."""

    id: str
    name: str
    provider: Provider
    auth_kind: AuthKind
    access: Access = "read_write"
    api_url: str | None = None
    web_url: str | None = None
    app_slug: str | None = None
    installation_id: str | None = None
    account: str | None = None
    status: str = "unverified"
    last_error: str | None = None
    last_checked_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    version: int = 1


@dataclass(frozen=True, slots=True)
class PathMapping:
    glob: str
    target_kind: TargetKind
    writable: bool = True

    @property
    def effective_writable(self) -> bool:
        return self.writable and self.target_kind not in {"registry", "ignored"}


@dataclass(frozen=True, slots=True)
class SyncPolicy:
    pull_mode: PullMode = "on_demand"
    publish_mode: PublishMode = "open_pr"
    branch_template: str = "studio/{component}-v{version}"
    commit_template: str = "{component}: {summary}"
    block_publish_until_merged: bool = False


@dataclass(frozen=True, slots=True)
class Source:
    """A repository branch (or a local folder) synced with one instance."""

    id: str
    instance_id: str
    provider: Provider
    repo: str
    branch: str
    connection_id: str | None = None
    clone_url: str | None = None
    local_path: str | None = None
    convention: dict[str, Any] | None = None
    mappings: tuple[PathMapping, ...] = ()
    policy: SyncPolicy = field(default_factory=SyncPolicy)
    status: SourceStatus = "setup"
    status_detail: str | None = None
    head_sha: str | None = None
    last_fetched_at: datetime | None = None
    scan_report: dict[str, Any] | None = None
    webhook_id: str | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    version: int = 1

    @property
    def is_local(self) -> bool:
        return self.provider == "local"

    @property
    def label(self) -> str:
        return self.local_path or self.repo


@dataclass(frozen=True, slots=True)
class FileBinding:
    """A repository file ↔ a Studio component, with where they last agreed."""

    id: str
    source_id: str
    path: str
    component_kind: ComponentKind
    component_id: str
    last_synced_sha: str | None = None
    last_synced_version: int | None = None
    content_hash: str | None = None
    synced_code: str | None = None
    """The file as of the last sync: the base of every three-way merge."""
    synced_config: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    author_name: str
    author_email: str
    committed_at: datetime
    message: str


@dataclass(frozen=True, slots=True)
class Change:
    """One file moving one way: incoming (repo → a Studio draft) or outgoing (a Studio version → the repo)."""

    id: str
    source_id: str
    direction: Direction
    path: str
    component_kind: ComponentKind | None = None
    component_id: str | None = None
    binding_id: str | None = None
    base_sha: str | None = None
    commit_sha: str | None = None
    blob: str | None = None
    """The file's blob id (or content hash) the change was read from."""
    author_name: str | None = None
    author_email: str | None = None
    committed_at: datetime | None = None
    message: str | None = None
    additions: int = 0
    deletions: int = 0
    before_code: str | None = None
    after_code: str | None = None
    config: dict[str, Any] | None = None
    """Incoming: what the repository's file reads as. Outgoing: the config of the version written out."""
    base_config: dict[str, Any] | None = None
    """The last version both sides agreed on: the base of the three-way merge."""
    outcome: dict[str, Any] = field(default_factory=dict[str, Any])
    diagnostics: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    incoming_marks: dict[str, str] = field(default_factory=dict[str, str])
    draft_version: int | None = None
    """Incoming: Studio's open draft the change merges with. Outgoing: the version that is written out."""
    summary: str | None = None
    included: bool = True
    status: ChangeStatus = "pending"
    result_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Side:
    """One side of a conflict: the value and who wrote it."""

    value: Any
    author: str | None
    reference: str | None
    """A commit sha (repository side) or ``draft v6`` (Studio side)."""
    present: bool = True
    """``False`` when this side removed the field."""


@dataclass(frozen=True, slots=True)
class Conflict:
    id: str
    source_id: str
    change_id: str
    path: str
    component_id: str
    field_path: str
    base_value: Any
    repo_side: Side
    studio_side: Side
    status: ConflictStatus = "open"
    resolution: Resolution | None = None
    resolved_value: Any = None
    resolved_by: str | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime | None = None

    def chosen(self) -> Any:  # noqa: ANN401
        match self.resolution:
            case "keep_studio":
                return self.studio_side.value
            case "keep_repo":
                return self.repo_side.value
            case _:
                return self.resolved_value


@dataclass(frozen=True, slots=True)
class PullRequest:
    id: str
    source_id: str
    number: int
    url: str
    branch: str
    base_branch: str
    head_sha: str
    status: PullRequestStatus = "open"
    merge_sha: str | None = None
    components: tuple[dict[str, Any], ...] = ()
    """``{component_id, version, path, blob}`` for every file the pull request writes."""
    review_requirement: str | None = None
    title: str | None = None
    opened_by: str | None = None
    opened_by_name: str | None = None
    created_at: datetime | None = None
    merged_at: datetime | None = None
    last_checked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Delivery:
    id: str
    source_id: str
    provider: Provider
    delivery_id: str
    event: str
    received_at: datetime
    processed_at: datetime | None = None
    error: str | None = None
