"""HTTP routes for governing the log (``/api/v1/audit``).

Saved views, export, hash-chain verification, retention policy and archives, SIEM sinks.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response, status
from fastapi.responses import StreamingResponse

from agnostic_audit.api.schemas import (
    ArchiveOut,
    AuditPolicyIn,
    AuditPolicyOut,
    EventFilters,
    ExportIn,
    ExportOut,
    RestoreOut,
    SavedViewIn,
    SavedViewOut,
    SavedViewPatch,
    SinkIn,
    SinkOut,
    SinkPatch,
    SinkTestOut,
    StreamStatusOut,
    VerifyIn,
    VerifyOut,
    WriteCheckOut,
)
from agnostic_audit.application.archive import RESTORE_TASK, Archives, VerifyChain
from agnostic_audit.application.exports import MEDIA_TYPES, Exports, decompressed_chunks, filename, render
from agnostic_audit.application.policy import POLICY_FIELDS, SECRET_FIELD, PolicyService
from agnostic_audit.application.ports import EventQuery, Jobs
from agnostic_audit.application.streaming import SinkService
from agnostic_audit.application.use_cases import RecordEvent
from agnostic_audit.application.views import SavedViews, filters_from_query
from agnostic_audit.domain.events import AuditEntry
from agnostic_audit.domain.governance import Policy
from agnostic_audit.domain.siem import Sink, public_config
from agnostic_audit.facade import actor_of
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow

router = APIRouter(route_class=DishkaRoute)

READ_SCOPE = "audit:read"
EXPORT_SCOPE = "audit:export"
ADMIN_SCOPE = "settings:write"
"""Retention, archive and SIEM settings are org settings."""


def _query(
    q: str | None,
    actor: str | None,
    actor_kind: Literal["user", "service_account", "system", "anonymous"] | None,
    action: str | None,
    decision: Literal["allowed", "denied", "n_a"] | None,
    instance: str | None,
    resource: str | None,
    source: Literal["control_plane", "agentos"] | None,
    since: datetime | None,
    until: datetime | None,
) -> EventQuery:
    return EventQuery(
        q=q,
        actor_id=actor,
        actor_kind=actor_kind,
        action=action,
        decision=decision,
        instance_id=instance,
        resource_id=resource,
        source=source,
        since=since,
        until=until,
    )


# ---------------------------------------------------------------- saved views


@router.get("/views", summary="Saved views: the caller's own and the shared ones, with event counts")
async def list_views(
    principal: FromDishka[Principal], authorizer: FromDishka[Authorizer], views: FromDishka[SavedViews]
) -> list[SavedViewOut]:
    _ = await authorizer.require(principal, READ_SCOPE)
    return [SavedViewOut.from_domain(view) for view in await views.list(principal)]


async def _audit_shared(record: RecordEvent, principal: Principal, view: SavedViewOut, change: str) -> None:
    if view.shared:
        _ = await record.now(
            AuditEntry(
                action="audit.views.share",
                actor=actor_of(principal),
                resource_kind="audit_view",
                resource_id=view.id,
                resource_display=view.name,
                diff={"title": "Shared view", "lines": [{"op": "note", "text": change}], "note": None},
            )
        )


@router.post("/views", status_code=status.HTTP_201_CREATED, summary="Save the current filters as a view")
async def create_view(
    body: SavedViewIn,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    views: FromDishka[SavedViews],
    record: FromDishka[RecordEvent],
) -> SavedViewOut:
    _ = await authorizer.require(principal, READ_SCOPE)
    created = SavedViewOut.from_domain(
        await views.create(
            principal, name=body.name, filters=body.filters.stored(), shared=body.shared, position=body.position
        )
    )
    await _audit_shared(record, principal, created, "Created")
    return created


@router.patch("/views/{view_id}", summary="Rename, re-filter or move a view")
async def update_view(
    view_id: str,
    body: SavedViewPatch,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    views: FromDishka[SavedViews],
    record: FromDishka[RecordEvent],
) -> SavedViewOut:
    _ = await authorizer.require(principal, READ_SCOPE)
    changes: dict[str, Any] = body.model_dump(exclude_unset=True, exclude={"filters"})
    if "filters" in body.model_fields_set:
        changes["filters"] = (body.filters or EventFilters()).stored()
    updated = SavedViewOut.from_domain(await views.update(principal, view_id, changes))
    await _audit_shared(record, principal, updated, "Changed")
    return updated


@router.delete("/views/{view_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a view")
async def delete_view(
    view_id: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    views: FromDishka[SavedViews],
) -> Response:
    _ = await authorizer.require(principal, READ_SCOPE)
    await views.delete(principal, view_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- export


@router.get(
    "/export",
    summary="Download matching events (up to 10 000; larger ranges answer 413: use POST /audit/exports)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}, "application/x-ndjson": {}}}},
)
async def export_events(
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    exports: FromDishka[Exports],
    record: FromDishka[RecordEvent],
    format: Literal["csv", "jsonl"] = "csv",  # noqa: A002  (the public parameter name)
    q: Annotated[str | None, Query(max_length=200)] = None,
    actor: str | None = None,
    actor_kind: Literal["user", "service_account", "system", "anonymous"] | None = None,
    action: str | None = None,
    decision: Literal["allowed", "denied", "n_a"] | None = None,
    instance: str | None = None,
    resource: str | None = None,
    source: Literal["control_plane", "agentos"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> StreamingResponse:
    _ = await authorizer.require(principal, EXPORT_SCOPE)
    query = _query(q, actor, actor_kind, action, decision, instance, resource, source, since, until)
    events = await exports.sync(query)
    _ = await record.now(
        AuditEntry(
            action="audit.export",
            actor=actor_of(principal),
            resource_kind="audit_export",
            fields={"count": str(len(events)), "format": format.upper()},
            diff={"title": "Filters", "filters": filters_from_query(query), "format": format, "rows": len(events)},
        )
    )

    def body() -> Iterator[bytes]:
        for line in render(events, format):
            yield line.encode()

    return StreamingResponse(
        body(),
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename(format, utcnow())}"'},
    )


@router.post(
    "/exports", status_code=status.HTTP_202_ACCEPTED, summary="Start a background export of any size (kept 24 h)"
)
async def request_export(
    body: ExportIn,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    exports: FromDishka[Exports],
    record: FromDishka[RecordEvent],
) -> ExportOut:
    _ = await authorizer.require(principal, EXPORT_SCOPE)
    job = await exports.request(principal.id, body.format, body.filters.stored())
    _ = await record.now(
        AuditEntry(
            action="audit.export.requested",
            actor=actor_of(principal),
            resource_kind="audit_export",
            resource_id=job.id,
            fields={"format": body.format.upper()},
            diff={"title": "Filters", "filters": dict(job.filters), "format": body.format},
        )
    )
    return ExportOut.from_domain(job)


@router.get("/exports", summary="The caller's background exports from the last 24 hours")
async def list_exports(
    principal: FromDishka[Principal], authorizer: FromDishka[Authorizer], exports: FromDishka[Exports]
) -> list[ExportOut]:
    _ = await authorizer.require(principal, EXPORT_SCOPE)
    return [ExportOut.from_domain(job) for job in await exports.mine(principal.id)]


@router.get("/exports/{export_id}", summary="One background export")
async def get_export(
    export_id: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    exports: FromDishka[Exports],
) -> ExportOut:
    _ = await authorizer.require(principal, EXPORT_SCOPE)
    return ExportOut.from_domain(await exports.get(principal.id, export_id))


@router.get(
    "/exports/{export_id}/download",
    summary="The finished export as CSV or JSONL (stored compressed, decompressed while it streams)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}, "application/x-ndjson": {}}}},
)
async def download_export(
    export_id: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    exports: FromDishka[Exports],
    record: FromDishka[RecordEvent],
) -> StreamingResponse:
    _ = await authorizer.require(principal, EXPORT_SCOPE)
    job, content = await exports.download(principal.id, export_id)
    _ = await record.now(
        AuditEntry(
            action="audit.export",
            actor=actor_of(principal),
            resource_kind="audit_export",
            resource_id=job.id,
            fields={"count": str(job.row_count or 0), "format": job.format.upper()},
            diff={"title": "Filters", "filters": dict(job.filters), "format": job.format, "rows": job.row_count},
        )
    )
    return StreamingResponse(
        decompressed_chunks(content),
        media_type=MEDIA_TYPES[job.format],
        headers={"Content-Disposition": f'attachment; filename="{filename(job.format, job.created_at)}"'},
    )


# ---------------------------------------------------------------- hash chain


@router.post("/verify", summary="Check the tamper-evidence hash chain over a time range")
async def verify_chain(
    body: VerifyIn,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    verify: FromDishka[VerifyChain],
) -> VerifyOut:
    _ = await authorizer.require(principal, READ_SCOPE)
    return VerifyOut.from_domain(await verify(body.since, body.until))


# ---------------------------------------------------------------- policy and archives


@router.get("/policy", summary="Retention, archive and hash-chain policy (the secret key is never returned)")
async def get_policy(
    principal: FromDishka[Principal], authorizer: FromDishka[Authorizer], policies: FromDishka[PolicyService]
) -> AuditPolicyOut:
    _ = await authorizer.require(principal, READ_SCOPE)
    return AuditPolicyOut.from_domain(await policies.current())


def _policy_lines(before: Policy, after: Policy, secret_changed: bool) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    for key in POLICY_FIELDS:
        old, new = getattr(before, key), getattr(after, key)
        if old != new:
            lines.append({"op": "-", "text": f"{key}: {old}"})
            lines.append({"op": "+", "text": f"{key}: {new}"})
    if secret_changed:
        lines.append({"op": "note", "text": "secret_access_key changed"})
    return lines


@router.put("/policy", summary="Change the policy (only the fields sent)")
async def update_policy(
    body: AuditPolicyIn,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    policies: FromDishka[PolicyService],
    record: FromDishka[RecordEvent],
) -> AuditPolicyOut:
    _ = await authorizer.require(principal, ADMIN_SCOPE)
    changes = body.changes()
    before, after = await policies.update(changes, by=principal.id)
    lines = _policy_lines(before, after, SECRET_FIELD in changes)
    if lines:
        _ = await record.now(
            AuditEntry(
                action="audit.policy.update",
                actor=actor_of(principal),
                resource_kind="audit_policy",
                resource_display="Audit retention and archive",
                diff={"title": "Audit policy", "lines": lines, "note": None},
            )
        )
    return AuditPolicyOut.from_domain(after)


@router.post(
    "/policy/test-write",
    summary="Write, read back and delete a small object in the archive bucket (stored settings, overlaid by the body)",
)
async def check_policy_write(
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    policies: FromDishka[PolicyService],
    body: AuditPolicyIn | None = None,
) -> WriteCheckOut:
    _ = await authorizer.require(principal, ADMIN_SCOPE)
    check = await policies.test_write(body.changes() if body else {})
    return WriteCheckOut(ok=check.ok, error=check.error, latency_ms=check.latency_ms)


@router.get("/archives", summary="Archived months, newest first")
async def list_archives(
    principal: FromDishka[Principal], authorizer: FromDishka[Authorizer], archives: FromDishka[Archives]
) -> list[ArchiveOut]:
    _ = await authorizer.require(principal, READ_SCOPE)
    now = utcnow()
    return [ArchiveOut.from_domain(archive, now) for archive in await archives.list()]


@router.post(
    "/archives/{month}/restore",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-import an archived month (YYYY-MM) for 7 days of searching (runs in the background)",
)
async def restore_archive(
    month: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    archives: FromDishka[Archives],
    jobs: FromDishka[Jobs],
    record: FromDishka[RecordEvent],
) -> RestoreOut:
    _ = await authorizer.require(principal, ADMIN_SCOPE)
    archive = await archives.get(month)
    if archive.restored(utcnow()):
        return RestoreOut(month=month, status="restored")
    await jobs.defer(RESTORE_TASK, month=month)
    _ = await record.now(
        AuditEntry(
            action="audit.restore",
            actor=actor_of(principal),
            resource_kind="audit_archive",
            resource_id=month,
            resource_display=month,
            fields={"month": month},
        )
    )
    return RestoreOut(month=month, status="queued")


# ---------------------------------------------------------------- SIEM


@router.get("/sinks", summary="SIEM sinks (secrets left out)")
async def list_sinks(
    principal: FromDishka[Principal], authorizer: FromDishka[Authorizer], sinks: FromDishka[SinkService]
) -> list[SinkOut]:
    _ = await authorizer.require(principal, READ_SCOPE)
    return [SinkOut.from_domain(sink) for sink in await sinks.list()]


async def _audit_sink(record: RecordEvent, principal: Principal, action: str, sink: Sink, lines: list[Any]) -> None:
    _ = await record.now(
        AuditEntry(
            action=action,
            actor=actor_of(principal),
            resource_kind="audit_sink",
            resource_id=sink.id,
            resource_display=sink.name,
            diff={"title": "SIEM sink", "lines": lines, "note": None} if lines else None,
        )
    )


def _sink_lines(before: Sink | None, after: Sink | None) -> list[dict[str, str]]:
    def flat(sink: Sink | None) -> dict[str, str]:
        if sink is None:
            return {}
        values = {"name": sink.name, "kind": sink.kind, "format": sink.format, "enabled": str(sink.enabled)}
        return values | {f"config.{key}": str(value) for key, value in public_config(sink.config).items()}

    old, new = flat(before), flat(after)
    lines: list[dict[str, str]] = []
    for key in sorted(old.keys() | new.keys()):
        if old.get(key) != new.get(key):
            if key in old:
                lines.append({"op": "-", "text": f"{key}: {old[key]}"})
            if key in new:
                lines.append({"op": "+", "text": f"{key}: {new[key]}"})
    return lines


@router.post("/sinks", status_code=status.HTTP_201_CREATED, summary="Add a SIEM sink (streams events from now on)")
async def create_sink(
    body: SinkIn,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    sinks: FromDishka[SinkService],
    record: FromDishka[RecordEvent],
) -> SinkOut:
    _ = await authorizer.require(principal, ADMIN_SCOPE)
    sink = await sinks.create(
        name=body.name,
        kind=body.kind,
        sink_format=body.format,
        config=body.config,
        enabled=body.enabled,
        created_by=principal.id,
    )
    await _audit_sink(record, principal, "audit.sinks.create", sink, _sink_lines(None, sink))
    return SinkOut.from_domain(sink)


@router.patch("/sinks/{sink_id}", summary="Change a sink; enabling it again clears its failing state")
async def update_sink(
    sink_id: str,
    body: SinkPatch,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    sinks: FromDishka[SinkService],
    record: FromDishka[RecordEvent],
) -> SinkOut:
    _ = await authorizer.require(principal, ADMIN_SCOPE)
    before, after = await sinks.update(sink_id, body.model_dump(exclude_unset=True))
    lines = _sink_lines(before, after)
    if body.config and any(key in body.config for key in ("secret", "headers")):
        lines.append({"op": "note", "text": "secrets changed"})
    await _audit_sink(record, principal, "audit.sinks.update", after, lines)
    return SinkOut.from_domain(after)


@router.delete("/sinks/{sink_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a sink")
async def delete_sink(
    sink_id: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    sinks: FromDishka[SinkService],
    record: FromDishka[RecordEvent],
) -> Response:
    _ = await authorizer.require(principal, ADMIN_SCOPE)
    sink = await sinks.delete(sink_id)
    await _audit_sink(record, principal, "audit.sinks.delete", sink, _sink_lines(sink, None))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sinks/{sink_id}/test", summary="Send one synthetic event to the sink now")
async def test_sink(
    sink_id: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    sinks: FromDishka[SinkService],
) -> SinkTestOut:
    _ = await authorizer.require(principal, ADMIN_SCOPE)
    result = await sinks.test(sink_id, actor_id=principal.id, actor_display=principal.display_name)
    return SinkTestOut.from_domain(result)


@router.get("/stream-status", summary="Whether events are streaming to a SIEM, for the header pill")
async def stream_status(
    principal: FromDishka[Principal], authorizer: FromDishka[Authorizer], sinks: FromDishka[SinkService]
) -> StreamStatusOut:
    _ = await authorizer.require(principal, READ_SCOPE)
    return StreamStatusOut.from_domain(await sinks.status())
