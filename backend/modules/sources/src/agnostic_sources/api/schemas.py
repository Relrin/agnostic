"""Request and response bodies of the sources API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_sources.application.connections import ConnectionDraft
from agnostic_sources.application.outgoing import CommitPreview
from agnostic_sources.application.ports import RepoSummary, Secrets
from agnostic_sources.application.sources import BindingDecision, SourceDraft, SourcePatch
from agnostic_sources.application.sync import PullResult
from agnostic_sources.application.views import ChangesView, ComponentSource, SourceCard
from agnostic_sources.domain.merge import MISSING
from agnostic_sources.domain.model import (
    PROVIDER_LABEL,
    Change,
    Conflict,
    Connection,
    Delivery,
    PathMapping,
    PullRequest,
    Side,
    Source,
    SyncPolicy,
)
from agnostic_sources.domain.outcomes import Outcome, sentence

type ProviderIn = Literal["github", "gitlab", "gitea", "forgejo", "local"]
type TargetIn = Literal["agents", "teams", "workflows", "registry", "ignored"]


# ---------------------------------------------------------------- connections


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    provider: Literal["github", "gitlab", "gitea", "forgejo"]
    auth_kind: Literal["github_app", "token", "deploy_key"] = "token"
    access: Literal["read_write", "read_only"] = "read_write"
    api_url: str | None = Field(default=None, max_length=500)
    web_url: str | None = Field(default=None, max_length=500, description="The server (Gitea, Forgejo, self-managed).")
    app_slug: str | None = Field(default=None, max_length=200)
    installation_id: str | None = Field(default=None, max_length=40)
    app_id: str | None = Field(default=None, max_length=40)
    private_key: str | None = Field(default=None, max_length=20_000, description="GitHub App key or deploy key.")
    token: str | None = Field(default=None, max_length=2000)
    webhook_secret: str | None = Field(default=None, max_length=500)
    version: int | None = Field(default=None, description="Expected version (optimistic concurrency).")

    def draft(self) -> ConnectionDraft:
        return ConnectionDraft(
            name=self.name,
            provider=self.provider,
            auth_kind=self.auth_kind,
            access=self.access,
            api_url=self.api_url,
            web_url=self.web_url,
            app_slug=self.app_slug,
            installation_id=self.installation_id,
            secrets=Secrets(
                token=self.token,
                private_key=self.private_key,
                app_id=self.app_id,
                webhook_secret=self.webhook_secret,
            ),
        )


class ConnectionOut(BaseModel):
    id: str
    name: str
    provider: str
    provider_label: str
    auth_kind: str
    access: str
    api_url: str | None
    web_url: str | None
    app_slug: str | None
    installation_id: str | None
    account: str | None
    status: str
    last_error: str | None
    last_checked_at: datetime | None
    version: int

    @classmethod
    def of(cls, connection: Connection) -> ConnectionOut:
        return cls(
            id=connection.id,
            name=connection.name,
            provider=connection.provider,
            provider_label=PROVIDER_LABEL.get(connection.provider, connection.provider),
            auth_kind=connection.auth_kind,
            access=connection.access,
            api_url=connection.api_url,
            web_url=connection.web_url,
            app_slug=connection.app_slug,
            installation_id=connection.installation_id,
            account=connection.account,
            status=connection.status,
            last_error=connection.last_error,
            last_checked_at=connection.last_checked_at,
            version=connection.version,
        )


class InstallUrlOut(BaseModel):
    url: str


class RepoOut(BaseModel):
    full_name: str
    default_branch: str
    private: bool

    @classmethod
    def of(cls, repo: RepoSummary) -> RepoOut:
        return cls(full_name=repo.full_name, default_branch=repo.default_branch, private=repo.private)


# ---------------------------------------------------------------- sources


class PathMappingIO(BaseModel):
    glob: str = Field(min_length=1, max_length=500)
    target_kind: TargetIn
    writable: bool = True

    def mapping(self) -> PathMapping:
        return PathMapping(self.glob, self.target_kind, self.writable)


class SyncPolicyIO(BaseModel):
    pull_mode: Literal["on_demand", "on_push_as_drafts"] = "on_demand"
    publish_mode: Literal["open_pr", "commit_direct", "no_write_back"] = "open_pr"
    branch_template: str = Field(default="studio/{component}-v{version}", max_length=200)
    commit_template: str = Field(default="{component}: {summary}", max_length=300)
    block_publish_until_merged: bool = False

    def policy(self) -> SyncPolicy:
        return SyncPolicy(
            pull_mode=self.pull_mode,
            publish_mode=self.publish_mode,
            branch_template=self.branch_template,
            commit_template=self.commit_template,
            block_publish_until_merged=self.block_publish_until_merged,
        )

    @classmethod
    def of(cls, policy: SyncPolicy) -> SyncPolicyIO:
        return cls(
            pull_mode=policy.pull_mode,
            publish_mode=policy.publish_mode,
            branch_template=policy.branch_template,
            commit_template=policy.commit_template,
            block_publish_until_merged=policy.block_publish_until_merged,
        )


class ConventionIO(BaseModel):
    """How the repository reaches registry objects (``from app.registry import tools``)."""

    registry_module: str = Field(default="app.registry", max_length=200)
    namespaces: dict[str, str] = Field(default_factory=dict[str, str])
    agents_module: str = Field(default="app.agents", max_length=200)
    teams_module: str = Field(default="app.teams", max_length=200)
    workflows_module: str = Field(default="app.workflows", max_length=200)
    functions_module: str = Field(default="app.functions", max_length=200)


class SourceIn(BaseModel):
    provider: ProviderIn
    connection_id: str | None = None
    repo: str | None = Field(default=None, max_length=300, description="owner/name")
    branch: str = Field(default="main", max_length=200)
    clone_url: str | None = Field(default=None, max_length=500)
    local_path: str | None = Field(default=None, max_length=500, description="For local folders.")
    mappings: list[PathMappingIO] | None = Field(default=None, description="Defaults to agents/, teams/, workflows/.")
    policy: SyncPolicyIO | None = None
    convention: ConventionIO | None = None

    def draft(self) -> SourceDraft:
        return SourceDraft(
            provider=self.provider,
            repo=self.repo,
            branch=self.branch,
            connection_id=self.connection_id,
            clone_url=self.clone_url,
            local_path=self.local_path,
            mappings=tuple(item.mapping() for item in self.mappings) if self.mappings is not None else None,
            policy=self.policy.policy() if self.policy else None,
            convention=self.convention.model_dump() if self.convention else None,
        )


class SourcePatchIn(BaseModel):
    branch: str | None = Field(default=None, max_length=200)
    mappings: list[PathMappingIO] | None = None
    policy: SyncPolicyIO | None = None
    convention: ConventionIO | None = None
    version: int | None = Field(default=None, description="Expected version (optimistic concurrency).")

    def patch(self) -> SourcePatch:
        return SourcePatch(
            branch=self.branch,
            mappings=tuple(item.mapping() for item in self.mappings) if self.mappings is not None else None,
            policy=self.policy.policy() if self.policy else None,
            convention=self.convention.model_dump() if self.convention else None,
        )


class MappingOut(BaseModel):
    glob: str
    target_kind: TargetIn
    writable: bool
    count: int | None


class CodeSourceOut(BaseModel):
    id: str
    instance_id: str
    provider: str
    provider_label: str
    repo: str
    branch: str
    local_path: str | None
    connection_id: str | None
    connection_name: str | None
    auth: str = Field(description="``GitHub App · read & write``, ``Deploy token · pull only``…")
    status: str
    status_detail: str | None
    head_sha: str | None
    last_fetched_at: datetime | None
    mappings: list[MappingOut]
    policy: SyncPolicyIO
    convention: dict[str, Any] | None
    incoming: int
    outgoing: int
    conflicts: int
    open_pull_requests: int
    webhook: bool
    version: int

    @classmethod
    def of(cls, card: SourceCard) -> CodeSourceOut:
        source, connection = card.source, card.connection
        counts = list((source.scan_report or {}).get("counts") or [])
        return cls(
            id=source.id,
            instance_id=source.instance_id,
            provider=source.provider,
            provider_label=PROVIDER_LABEL.get(source.provider, source.provider),
            repo=source.repo,
            branch=source.branch,
            local_path=source.local_path,
            connection_id=source.connection_id,
            connection_name=connection.name if connection else None,
            auth=_auth(source, connection),
            status=source.status,
            status_detail=source.status_detail,
            head_sha=source.head_sha,
            last_fetched_at=source.last_fetched_at,
            mappings=[
                MappingOut(
                    glob=mapping.glob,
                    target_kind=mapping.target_kind,
                    writable=mapping.effective_writable,
                    count=int(counts[index]) if index < len(counts) else None,
                )
                for index, mapping in enumerate(source.mappings)
            ],
            policy=SyncPolicyIO.of(source.policy),
            convention=source.convention,
            incoming=card.incoming,
            outgoing=card.outgoing,
            conflicts=card.conflicts,
            open_pull_requests=card.open_pull_requests,
            webhook=source.webhook_id is not None,
            version=source.version,
        )


def _auth(source: Source, connection: Connection | None) -> str:
    if source.is_local:
        return "Local folder · writes go straight to disk"
    if connection is None:
        return "Public clone URL · pull only"
    kind = {"github_app": "GitHub App", "token": "Token", "deploy_key": "Deploy key"}.get(
        connection.auth_kind, connection.auth_kind
    )
    access = "read & write" if connection.access == "read_write" else "pull only"
    return f"{kind} · {access}"


class ScanReportOut(BaseModel):
    status: str
    status_detail: str | None
    head_sha: str | None
    report: dict[str, Any] | None


class BindingDecisionIn(BaseModel):
    path: str = Field(max_length=500)
    component_id: str = Field(max_length=200)
    bind: bool = True


class ActivateIn(BaseModel):
    bindings: list[BindingDecisionIn] | None = Field(
        default=None, description="Override the scan's proposals; omitted files follow them."
    )

    def decisions(self) -> list[BindingDecision] | None:
        if self.bindings is None:
            return None
        return [BindingDecision(item.path, item.component_id, item.bind) for item in self.bindings]


class JobOut(BaseModel):
    job_id: int | None = Field(description="The queued job; null when one was already waiting.")


# ---------------------------------------------------------------- changes


class ChangeOut(BaseModel):
    id: str
    direction: str
    path: str
    component_kind: str | None
    component_id: str | None
    commit_sha: str | None
    author_name: str | None
    committed_at: datetime | None
    message: str | None
    additions: int
    deletions: int
    outcome: dict[str, Any]
    outcome_sentence: str | None = Field(description="Incoming: what pulling does, for the reader.")
    summary: str | None = Field(description="Outgoing: what Studio changed (``temperature 0.7 → 0.2``).")
    draft_version: int | None
    diagnostics: list[dict[str, Any]]
    included: bool
    status: str
    result_version: int | None

    @classmethod
    def of(cls, change: Change, viewer_id: str | None) -> ChangeOut:
        outcome = (
            Outcome.of(change.outcome) if change.direction == "incoming" and change.outcome.get("action") else None
        )
        return cls(
            id=change.id,
            direction=change.direction,
            path=change.path,
            component_kind=change.component_kind,
            component_id=change.component_id,
            commit_sha=change.commit_sha,
            author_name=change.author_name,
            committed_at=change.committed_at,
            message=change.message,
            additions=change.additions,
            deletions=change.deletions,
            outcome=change.outcome,
            outcome_sentence=sentence(outcome, viewer_id) if outcome else None,
            summary=change.summary,
            draft_version=change.draft_version,
            diagnostics=change.diagnostics,
            included=change.included,
            status=change.status,
            result_version=change.result_version,
        )


class SideOut(BaseModel):
    value: Any
    present: bool
    author: str | None
    reference: str | None

    @classmethod
    def of(cls, side: Side) -> SideOut:
        present = side.present and side.value is not MISSING
        return cls(value=side.value if present else None, present=present, author=side.author, reference=side.reference)


class ConflictOut(BaseModel):
    id: str
    change_id: str
    path: str
    component_id: str
    field_path: str
    base_value: Any
    repo: SideOut
    studio: SideOut
    status: str
    resolution: str | None
    resolved_by_name: str | None

    @classmethod
    def of(cls, conflict: Conflict) -> ConflictOut:
        return cls(
            id=conflict.id,
            change_id=conflict.change_id,
            path=conflict.path,
            component_id=conflict.component_id,
            field_path=conflict.field_path,
            base_value=None if conflict.base_value is MISSING else conflict.base_value,
            repo=SideOut.of(conflict.repo_side),
            studio=SideOut.of(conflict.studio_side),
            status=conflict.status,
            resolution=conflict.resolution,
            resolved_by_name=conflict.resolved_by_name,
        )


class PullRequestOut(BaseModel):
    id: str
    number: int
    url: str
    branch: str
    base_branch: str
    status: str
    title: str | None
    review_requirement: str | None
    components: list[dict[str, Any]]
    opened_by_name: str | None
    created_at: datetime | None
    merged_at: datetime | None

    @classmethod
    def of(cls, pull: PullRequest) -> PullRequestOut:
        return cls(
            id=pull.id,
            number=pull.number,
            url=pull.url,
            branch=pull.branch,
            base_branch=pull.base_branch,
            status=pull.status,
            title=pull.title,
            review_requirement=pull.review_requirement,
            components=[dict(item) for item in pull.components],
            opened_by_name=pull.opened_by_name,
            created_at=pull.created_at,
            merged_at=pull.merged_at,
        )


class RemoteOut(BaseModel):
    ref: str
    head_sha: str | None
    fetched_at: datetime | None


class ChangesOut(BaseModel):
    remote: RemoteOut
    incoming: list[ChangeOut]
    outgoing: list[ChangeOut]
    conflicts: list[ConflictOut]
    pull_requests: list[PullRequestOut]

    @classmethod
    def of(cls, view: ChangesView, viewer_id: str | None) -> ChangesOut:
        source = view.source
        return cls(
            remote=RemoteOut(
                ref=source.local_path or f"origin/{source.branch}",
                head_sha=source.head_sha,
                fetched_at=source.last_fetched_at,
            ),
            incoming=[ChangeOut.of(change, viewer_id) for change in view.incoming],
            outgoing=[ChangeOut.of(change, viewer_id) for change in view.outgoing],
            conflicts=[ConflictOut.of(conflict) for conflict in view.conflicts],
            pull_requests=[PullRequestOut.of(pull) for pull in view.pull_requests],
        )


class ChangeDiffOut(BaseModel):
    path: str
    before: str | None
    after: str | None
    unified: str


class IncludeIn(BaseModel):
    included: bool


class PullIn(BaseModel):
    change_ids: list[str] = Field(min_length=1, max_length=200)


class PullResultOut(BaseModel):
    change_id: str
    path: str
    component_id: str | None
    version: int | None
    error: str | None

    @classmethod
    def of(cls, result: PullResult) -> PullResultOut:
        return cls(
            change_id=result.change_id,
            path=result.path,
            component_id=result.component_id,
            version=result.version,
            error=result.error,
        )


class CommitPreviewOut(BaseModel):
    branch: str
    base_branch: str
    mode: str
    message: str
    review_requirement: str | None
    sentence: str

    @classmethod
    def of(cls, preview: CommitPreview) -> CommitPreviewOut:
        return cls(
            branch=preview.branch,
            base_branch=preview.base_branch,
            mode=preview.mode,
            message=preview.message,
            review_requirement=preview.review_requirement,
            sentence=preview.sentence,
        )


class CommitIn(BaseModel):
    change_ids: list[str] = Field(min_length=1, max_length=200)
    message: str | None = Field(default=None, max_length=2000)


class ResolveIn(BaseModel):
    resolution: Literal["keep_studio", "keep_repo", "merged"]
    value: Any = Field(default=None, description="The merged value (for ``merged``).")


class ConflictCountOut(BaseModel):
    instance_id: str
    count: int


class WebhookDeliveryOut(BaseModel):
    id: str
    delivery_id: str
    event: str
    received_at: datetime
    processed_at: datetime | None
    error: str | None

    @classmethod
    def of(cls, delivery: Delivery) -> WebhookDeliveryOut:
        return cls(
            id=delivery.id,
            delivery_id=delivery.delivery_id,
            event=delivery.event,
            received_at=delivery.received_at,
            processed_at=delivery.processed_at,
            error=delivery.error,
        )


class LocalRootsOut(BaseModel):
    roots: list[str]


class PublishHoldOut(BaseModel):
    held: bool
    reason: str | None
    write_back: str | None
    link: str | None


class ComponentSourceOut(BaseModel):
    bound: bool
    source_id: str | None = None
    provider: str | None = None
    provider_label: str | None = None
    repo: str | None = None
    branch: str | None = None
    path: str | None = None
    synced_sha: str | None = None
    synced_version: int | None = None
    fetched_at: datetime | None = None
    incoming: list[ChangeOut] = Field(default_factory=list[ChangeOut])
    outgoing: list[ChangeOut] = Field(default_factory=list[ChangeOut])
    conflicts: list[ConflictOut] = Field(default_factory=list[ConflictOut])
    pull_request: PullRequestOut | None = None
    uncommitted: str | None = Field(default=None, description="``mode changed``: Studio's edits the repo doesn't have.")
    uncommitted_version: int | None = None
    incoming_marks: dict[str, str] = Field(
        default_factory=dict[str, str], description="Lines of ``marks_version``'s code that came from the repository."
    )
    marks_version: int | None = None
    other_sources: list[str] = Field(default_factory=list[str])
    hold: PublishHoldOut | None = None

    @classmethod
    def of(cls, view: ComponentSource, viewer_id: str | None) -> ComponentSourceOut:
        source, binding = view.source, view.binding
        if source is None or binding is None:
            return cls(bound=False)
        return cls(
            bound=True,
            source_id=source.id,
            provider=source.provider,
            provider_label=PROVIDER_LABEL.get(source.provider, source.provider),
            repo=source.label,
            branch=source.branch,
            path=binding.path,
            synced_sha=binding.last_synced_sha,
            synced_version=binding.last_synced_version,
            fetched_at=source.last_fetched_at,
            incoming=[ChangeOut.of(change, viewer_id) for change in view.incoming],
            outgoing=[ChangeOut.of(change, viewer_id) for change in view.outgoing],
            conflicts=[ConflictOut.of(conflict) for conflict in view.conflicts],
            pull_request=PullRequestOut.of(view.pull_request) if view.pull_request else None,
            uncommitted=view.uncommitted,
            uncommitted_version=view.uncommitted_version,
            incoming_marks=view.marks,
            marks_version=view.marks_version,
            other_sources=[item.label for item in view.others],
            hold=PublishHoldOut(
                held=view.hold.held, reason=view.hold.reason, write_back=view.hold.write_back, link=view.hold.link
            ),
        )
