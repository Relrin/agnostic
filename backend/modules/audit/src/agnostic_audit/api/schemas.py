"""Response bodies of ``/api/v1/audit``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_audit.application.ports import ActorSummary
from agnostic_audit.application.streaming import StreamStatus
from agnostic_audit.application.views import CountedView
from agnostic_audit.domain.chain import ChainResult
from agnostic_audit.domain.events import AuditEvent, can_request_access
from agnostic_audit.domain.governance import ArchivedMonth, ExportJob, Policy
from agnostic_audit.domain.siem import SECRET_KEYS, DeliveryResult, Sink, public_config


class ActorOut(BaseModel):
    kind: Literal["user", "service_account", "system", "anonymous"]
    id: str
    display: str


class AuditEventOut(BaseModel):
    id: str
    occurred_at: datetime
    request_id: str | None
    actor: ActorOut
    via: str
    ip: str | None
    client: str | None
    action: str
    resource_kind: str | None
    resource_id: str | None
    resource_display: str | None
    instance_id: str | None
    decision: Literal["allowed", "denied", "n_a"]
    scope_checked: str | None
    missing_scopes: list[str]
    response_status: int | None
    summary: str
    diff: dict[str, Any] | None
    links: dict[str, Any] | None
    source: Literal["control_plane", "agentos"]
    source_event_id: str | None = None
    denial_reason: str | None = None
    """Why it was denied, in a sentence (denied events)."""
    can_request_access: bool = False
    """The person was denied a scope on an instance and can ask for temporary access to it."""
    hash: str | None = None
    """Set while the tamper-evidence chain is on."""

    @classmethod
    def from_domain(cls, event: AuditEvent) -> AuditEventOut:
        return cls(
            id=event.id,
            occurred_at=event.occurred_at,
            request_id=event.request_id,
            actor=ActorOut(kind=event.actor.kind, id=event.actor.id, display=event.actor.display),
            via=event.via,
            ip=event.ip,
            client=event.client,
            action=event.action,
            resource_kind=event.resource_kind,
            resource_id=event.resource_id,
            resource_display=event.resource_display,
            instance_id=event.instance_id,
            decision=event.decision,
            scope_checked=event.scope_checked,
            missing_scopes=list(event.missing_scopes),
            response_status=event.response_status,
            summary=event.summary,
            diff=dict(event.diff) if event.diff is not None else None,
            links=dict(event.links) if event.links is not None else None,
            source=event.source,
            source_event_id=event.source_event_id,
            denial_reason=event.denial_reason,
            can_request_access=can_request_access(event),
            hash=event.hash,
        )


class AuditActionOut(BaseModel):
    action: str
    summary_template: str


class ActorSummaryOut(BaseModel):
    kind: Literal["user", "service_account", "system", "anonymous"]
    id: str
    display: str
    count: int

    @classmethod
    def from_domain(cls, actor: ActorSummary) -> ActorSummaryOut:
        return cls(kind=actor.kind, id=actor.id, display=actor.display, count=actor.count)


class EventFilters(BaseModel):
    """The event list's filters, as stored in saved views and exports (all optional)."""

    q: str | None = None
    actor: str | None = None
    actor_kind: Literal["user", "service_account", "system", "anonymous"] | None = None
    action: str | None = None
    decision: Literal["allowed", "denied", "n_a"] | None = None
    instance: str | None = None
    resource: str | None = None
    source: Literal["control_plane", "agentos"] | None = None
    since: datetime | None = None
    until: datetime | None = None

    def stored(self) -> dict[str, str]:
        values: dict[str, Any] = self.model_dump(exclude_none=True)
        return {key: value.isoformat() if isinstance(value, datetime) else str(value) for key, value in values.items()}


class SavedViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: EventFilters = Field(default_factory=EventFilters)
    shared: bool = False
    """Shared with everyone who can read the log (needs audit:export or an org admin role)."""
    position: int | None = None


class SavedViewPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    filters: EventFilters | None = None
    position: int | None = None


class SavedViewOut(BaseModel):
    id: str
    name: str
    filters: dict[str, str]
    shared: bool
    owner_id: str | None
    position: int
    count: int
    count_capped: bool
    """More than ``count`` (1000) events match; show "999+"."""
    editable: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, counted: CountedView) -> SavedViewOut:
        view = counted.view
        return cls(
            id=view.id,
            name=view.name,
            filters=dict(view.filters),
            shared=view.shared,
            owner_id=view.owner_id,
            position=view.position,
            count=counted.count,
            count_capped=counted.count_capped,
            editable=counted.editable,
            created_at=view.created_at,
            updated_at=view.updated_at,
        )


class ExportIn(BaseModel):
    format: Literal["csv", "jsonl"] = "csv"
    filters: EventFilters = Field(default_factory=EventFilters)


class ExportOut(BaseModel):
    id: str
    format: Literal["csv", "jsonl"]
    filters: dict[str, str]
    status: Literal["queued", "running", "done", "failed"]
    row_count: int | None
    size_bytes: int | None
    """Compressed size."""
    error: str | None
    created_at: datetime
    expires_at: datetime
    download_url: str | None
    """Set once done: the file, decompressed (``text/csv`` or ``application/x-ndjson``)."""

    @classmethod
    def from_domain(cls, job: ExportJob) -> ExportOut:
        return cls(
            id=job.id,
            format=job.format,
            filters=dict(job.filters),
            status=job.status,
            row_count=job.row_count,
            size_bytes=job.size_bytes,
            error=job.error,
            created_at=job.created_at,
            expires_at=job.expires_at,
            download_url=f"/api/v1/audit/exports/{job.id}/download" if job.status == "done" else None,
        )


class VerifyIn(BaseModel):
    since: datetime | None = None
    until: datetime | None = None


class VerifyOut(BaseModel):
    ok: bool
    checked: int
    """Chained events checked (events written while the chain was off are skipped)."""
    first_broken_event_id: str | None

    @classmethod
    def from_domain(cls, result: ChainResult) -> VerifyOut:
        return cls(ok=result.ok, checked=result.checked, first_broken_event_id=result.first_broken_event_id)


type ObjectLockMode = Literal["off", "governance", "compliance"]


class AuditPolicyOut(BaseModel):
    hot_retention_days: int
    archive_enabled: bool
    endpoint: str | None
    bucket: str | None
    prefix: str
    region: str
    access_key_id: str | None
    has_secret: bool
    """A secret access key is stored (it is never returned)."""
    object_lock_mode: ObjectLockMode
    archive_retention_days: int | None
    """``None``: archives never expire."""
    hash_chain: bool
    updated_by: str | None
    updated_at: datetime | None
    last_archive_at: datetime | None
    last_archive_error: str | None

    @classmethod
    def from_domain(cls, policy: Policy) -> AuditPolicyOut:
        return cls(
            hot_retention_days=policy.hot_retention_days,
            archive_enabled=policy.archive_enabled,
            endpoint=policy.endpoint,
            bucket=policy.bucket,
            prefix=policy.prefix,
            region=policy.region,
            access_key_id=policy.access_key_id,
            has_secret=policy.has_secret,
            object_lock_mode=policy.object_lock_mode,
            archive_retention_days=policy.archive_retention_days,
            hash_chain=policy.hash_chain,
            updated_by=policy.updated_by,
            updated_at=policy.updated_at,
            last_archive_at=policy.last_archive_at,
            last_archive_error=policy.last_archive_error,
        )


class AuditPolicyIn(BaseModel):
    """Only the fields sent change. ``secret_access_key``: a value replaces it, an empty string removes it."""

    hot_retention_days: int | None = Field(default=None, ge=30, le=36500)
    archive_enabled: bool | None = None
    endpoint: str | None = Field(default=None, max_length=512)
    bucket: str | None = Field(default=None, max_length=255)
    prefix: str | None = Field(default=None, max_length=512)
    region: str | None = Field(default=None, max_length=64)
    access_key_id: str | None = Field(default=None, max_length=255)
    secret_access_key: str | None = Field(default=None, max_length=1024)
    object_lock_mode: ObjectLockMode | None = None
    archive_retention_days: int | None = Field(default=None, ge=1, le=36500)
    hash_chain: bool | None = None

    def changes(self) -> dict[str, Any]:
        """Fields that were sent; an explicit ``archive_retention_days: null`` means "never expire"."""
        values: dict[str, Any] = self.model_dump(exclude_unset=True)
        return {key: value for key, value in values.items() if value is not None or key == "archive_retention_days"}


class WriteCheckOut(BaseModel):
    ok: bool
    error: str | None = None
    latency_ms: int | None = None


class ArchiveOut(BaseModel):
    month: str
    object_key: str
    manifest_key: str
    bytes: int
    event_count: int
    sha256: str
    chain_head: str | None
    archived_at: datetime
    purge_after: datetime | None
    restored: bool
    """Searchable now (until ``restore_expires_at``)."""
    restored_at: datetime | None
    restore_expires_at: datetime | None

    @classmethod
    def from_domain(cls, archive: ArchivedMonth, now: datetime) -> ArchiveOut:
        return cls(
            month=archive.month,
            object_key=archive.object_key,
            manifest_key=archive.manifest_key,
            bytes=archive.bytes,
            event_count=archive.event_count,
            sha256=archive.sha256,
            chain_head=archive.chain_head,
            archived_at=archive.archived_at,
            purge_after=archive.purge_after,
            restored=archive.restored(now),
            restored_at=archive.restored_at,
            restore_expires_at=archive.restore_expires_at,
        )


class RestoreOut(BaseModel):
    month: str
    status: Literal["queued", "restored"]
    """``restored`` when the month is already searchable."""


type SinkKindName = Literal["https_webhook", "syslog", "otlp_logs"]
type SinkFormatName = Literal["json", "ocsf", "cef"]


class SinkIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: SinkKindName
    format: SinkFormatName = "json"
    config: dict[str, Any]
    """https_webhook: ``url`` (https), ``secret`` (HMAC key), ``headers``; syslog: ``host``, ``port``, ``tls``
    (default true), ``tls_verify``, ``ca_pem``, ``hostname``; otlp_logs: ``endpoint`` (``/v1/logs`` is appended),
    ``headers``."""
    enabled: bool = True


class SinkPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    format: SinkFormatName | None = None
    config: dict[str, Any] | None = None
    """Merged into the current config; ``secret`` and ``headers`` stay unless sent again."""
    enabled: bool | None = None


class SinkOut(BaseModel):
    id: str
    name: str
    kind: SinkKindName
    format: SinkFormatName
    config: dict[str, Any]
    """Without secrets: header values are left out (``header_names`` lists them)."""
    has_secret: bool
    enabled: bool
    status: Literal["ok", "failing", "paused"]
    failure_count: int
    last_event_at: datetime | None
    last_error: str | None
    created_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, sink: Sink) -> SinkOut:
        return cls(
            id=sink.id,
            name=sink.name,
            kind=sink.kind,
            format=sink.format,
            config=public_config(sink.config),
            has_secret=any(sink.config.get(key) for key in SECRET_KEYS),
            enabled=sink.enabled,
            status=sink.status,
            failure_count=sink.failure_count,
            last_event_at=sink.last_event_at,
            last_error=sink.last_error,
            created_by=sink.created_by,
            created_at=sink.created_at,
        )


class SinkTestOut(BaseModel):
    ok: bool
    status_code: int | None
    error: str | None
    latency_ms: int | None

    @classmethod
    def from_domain(cls, result: DeliveryResult) -> SinkTestOut:
        return cls(ok=result.ok, status_code=result.status_code, error=result.error, latency_ms=result.latency_ms)


class StreamSinkOut(BaseModel):
    id: str
    name: str
    kind: SinkKindName
    status: Literal["ok", "failing", "paused"]
    enabled: bool
    last_event_at: datetime | None
    last_error: str | None


class StreamStatusOut(BaseModel):
    streaming: bool
    """At least one enabled sink is delivering without errors."""
    sinks: list[StreamSinkOut]
    last_event_at: datetime | None
    """Newest event any sink accepted."""

    @classmethod
    def from_domain(cls, status: StreamStatus) -> StreamStatusOut:
        return cls(
            streaming=status.streaming,
            sinks=[
                StreamSinkOut(
                    id=sink.id,
                    name=sink.name,
                    kind=sink.kind,
                    status=sink.status,
                    enabled=sink.enabled,
                    last_event_at=sink.last_event_at,
                    last_error=sink.last_error,
                )
                for sink in status.sinks
            ],
            last_event_at=status.last_event_at,
        )
