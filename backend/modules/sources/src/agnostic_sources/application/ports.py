"""Ports of the sources module: the store, git mirrors, git host APIs and local folders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from agnostic_kernel.errors import AppError
from agnostic_sources.domain.model import (
    Change,
    ChangeStatus,
    CommitInfo,
    Conflict,
    Connection,
    Delivery,
    Direction,
    FileBinding,
    PullRequest,
    Source,
)


@dataclass(frozen=True, slots=True)
class SourceLimits:
    """The settings the use cases follow (built from ``AGNOSTIC_SOURCES__*``)."""

    max_changed_files: int = 500
    max_file_bytes: int = 256_000
    allow_file_remotes: bool = False
    mirror_quota_mb: int = 512
    total_quota_mb: int = 10_240
    delivery_retention_days: int = 30
    committer_name: str = "Agnostic Studio"
    committer_email: str = "studio@agnostic.invalid"
    github_app_slug: str | None = None
    github_web_url: str = "https://github.com"
    watch_local: bool = True
    watch_debounce_ms: int = 800


class GitError(AppError):
    status = 502
    code = "git_error"
    title = "Git couldn't finish"


class ProviderError(AppError):
    status = 502
    code = "provider_error"
    title = "The git host answered with an error"


@dataclass(frozen=True, slots=True)
class Secrets:
    """A connection's or source's secrets, opened only to build a call."""

    token: str | None = None
    private_key: str | None = None
    """A GitHub App key or a deploy key (PEM / OpenSSH)."""
    app_id: str | None = None
    webhook_secret: str | None = None


class SourceStore(Protocol):
    async def connections(self) -> list[Connection]: ...
    async def connection(self, connection_id: str) -> Connection | None: ...
    async def save_connection(
        self, connection: Connection, secrets: Secrets | None, *, expected_version: int | None = None
    ) -> Connection: ...
    async def connection_secrets(self, connection_id: str) -> Secrets: ...
    async def delete_connection(self, connection_id: str) -> None: ...

    async def sources(self, instance_id: str | None = None) -> list[Source]: ...
    async def source(self, source_id: str) -> Source | None: ...
    async def save_source(self, source: Source, *, expected_version: int | None = None) -> Source: ...
    async def source_secret(self, source_id: str) -> str | None:
        """The webhook secret of the source (``None`` before a webhook is registered)."""
        ...

    async def set_source_secret(self, source_id: str, secret: str | None) -> None: ...
    async def delete_source(self, source_id: str) -> None: ...

    async def bindings(self, source_id: str) -> list[FileBinding]: ...
    async def bindings_for_component(self, instance_id: str, component_id: str) -> list[tuple[Source, FileBinding]]: ...
    async def save_binding(self, binding: FileBinding) -> None: ...
    async def delete_binding(self, binding_id: str) -> None: ...

    async def changes(
        self, source_id: str, direction: Direction | None = None, statuses: Sequence[ChangeStatus] | None = None
    ) -> list[Change]: ...
    async def change(self, change_id: str) -> Change | None: ...
    async def save_change(self, change: Change) -> None: ...

    async def conflicts(self, source_id: str, *, open_only: bool = True) -> list[Conflict]: ...
    async def conflicts_for_change(self, change_id: str) -> list[Conflict]: ...
    async def conflict(self, conflict_id: str) -> Conflict | None: ...
    async def save_conflict(self, conflict: Conflict) -> None: ...
    async def open_conflict_count(self, instance_id: str) -> int: ...

    async def pull_requests(self, source_id: str | None = None, *, open_only: bool = False) -> list[PullRequest]: ...
    async def pull_request(self, pull_request_id: str) -> PullRequest | None: ...
    async def save_pull_request(self, pull_request: PullRequest) -> None: ...

    async def record_delivery(self, delivery: Delivery) -> bool:
        """``False`` when the delivery was seen already (redelivered)."""
        ...

    async def finish_delivery(self, delivery_id: str, error: str | None) -> None: ...
    async def deliveries(self, source_id: str, limit: int = 50) -> list[Delivery]: ...
    async def prune_deliveries(self, older_than_days: int) -> int: ...

    async def commit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Remote:
    url: str
    header: str | None = None
    """``Authorization`` header value for https remotes."""
    ssh_key: str | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    head: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PathChange:
    status: Literal["added", "modified", "deleted"]
    path: str
    additions: int = 0
    deletions: int = 0


class GitRepo(Protocol):
    """Bare mirrors of source repositories (never a work tree, never a hook)."""

    async def fetch(self, source_id: str, remote: Remote, branch: str) -> FetchResult: ...
    async def files(self, source_id: str, rev: str) -> dict[str, str]:
        """Path → blob id of every file at ``rev`` (trees only: contents aren't fetched)."""
        ...

    async def changed(self, source_id: str, old: str | None, new: str) -> list[PathChange]:
        """Files that differ between two commits (every file when ``old`` is unknown)."""
        ...

    async def read(self, source_id: str, remote: Remote, rev: str, path: str) -> bytes | None: ...
    async def last_commit(self, source_id: str, rev: str, path: str) -> CommitInfo | None: ...
    async def contains(self, source_id: str, ancestor: str, rev: str) -> bool: ...
    async def branches(self, source_id: str, remote: Remote) -> list[str]: ...
    async def default_branch(self, remote: Remote) -> str | None:
        """The branch the remote's ``HEAD`` points at (``None`` when it doesn't say)."""
        ...

    async def commit(
        self,
        source_id: str,
        base: str,
        files: Mapping[str, bytes],
        message: str,
        author: tuple[str, str],
        committer: tuple[str, str],
    ) -> str: ...
    async def push(self, source_id: str, remote: Remote, sha: str, branch: str, *, lease: str | None = None) -> None:
        """Push ``sha`` to ``branch``; with ``lease``, replace the branch only while it still points there."""
        ...

    async def size(self, source_id: str) -> int: ...
    async def gc(self, source_id: str) -> None: ...
    async def remove(self, source_id: str) -> None: ...
    async def mirrors(self) -> list[str]: ...
    async def version(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class RepoSummary:
    full_name: str
    default_branch: str
    private: bool = True
    clone_url: str | None = None


@dataclass(frozen=True, slots=True)
class OpenedPullRequest:
    number: int
    url: str


@dataclass(frozen=True, slots=True)
class PullRequestState:
    status: Literal["open", "merged", "closed"]
    merge_sha: str | None = None
    head_sha: str | None = None


class ProviderClient(Protocol):
    async def verify(self) -> str:
        """Who the connection acts as (``northwind`` installation, ``agnostic-bot``); raises when it can't."""
        ...

    async def repos(self, query: str | None = None) -> list[RepoSummary]: ...
    async def repo(self, repo: str) -> RepoSummary: ...
    async def branches(self, repo: str) -> list[str]: ...
    async def remote(self, repo: str, clone_url: str | None) -> Remote: ...
    async def review_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:
        """``(required approvals, reviewer teams)`` from branch protection; ``None`` when it can't be read."""
        ...

    async def open_pull_request(
        self, repo: str, *, head: str, base: str, title: str, body: str
    ) -> OpenedPullRequest: ...
    async def pull_request(self, repo: str, number: int) -> PullRequestState: ...
    async def register_webhook(self, repo: str, url: str, secret: str) -> str | None: ...
    async def delete_webhook(self, repo: str, hook_id: str) -> None: ...


class ProviderClients(Protocol):
    def client(self, connection: Connection, secrets: Secrets) -> ProviderClient: ...


class Folders(Protocol):
    """Local folders mounted into Agnostic and the instance (development setups): files read and written in place."""

    def files(self, root: str) -> dict[str, str]:
        """Path → content hash of every file under ``root`` (POSIX paths)."""
        ...

    def digest(self, root: str, path: str) -> str | None:
        """The hash :meth:`files` lists for the file (``None`` when it is gone)."""
        ...

    def read(self, root: str, path: str) -> bytes | None:
        """The file's content (``None`` when it is gone or too large to read)."""
        ...

    def write(self, root: str, path: str, data: bytes) -> None: ...
    def check_root(self, root: str) -> str:
        """The resolved root, or :class:`SourceRuleError` when it is outside the allowed roots."""
        ...

    def allowed_roots(self) -> list[str]: ...


class WebhookUrls(Protocol):
    def url(self, provider: str) -> str | None:
        """The public URL git hosts post to (``None`` without a public URL: no webhook is registered)."""
        ...


type Json = dict[str, Any]
