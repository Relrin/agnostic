"""Copying AgentOS authorization trails into the audit log.

Each connected instance with the authorization store (``authz_store``) keeps two trails: every allow/deny decision
(``GET /authz/decisions``) and every role or assignment change (``GET /authz/audit``). Both answer
``{data: [...], meta: {page, limit, total_pages, total_count}}``, newest first by ``created_at`` (epoch seconds),
paged by ``page``/``limit``. Rows carry no id of their own, so an event's id is a hash of its content (plus its
place among identical rows of the same second); the cursor is the newest ``created_at`` already read, and every
run re-reads that second so nothing written later in it is missed (the audit log skips what it already stored).

All knowledge of the row shape lives in :func:`parse_rows` and :func:`entry_from_row`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from agnostic_agentos_client import AgentOSError
from agnostic_agentos_client import NotFoundError as RuntimeNotFoundError
from agnostic_audit.facade import Actor, AuditLog, IngestCursors, IngestedEntry
from agnostic_instances.facade import Instance, InstancesFacade, InstanceStatus
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

type Stream = Literal["decisions", "audit"]
STREAMS: Mapping[Stream, str] = {"decisions": "/authz/decisions", "audit": "/authz/audit"}
PAGE_LIMIT = 500
MAX_PAGES = 20
"""Per stream and run; a longer backlog is read newest first, so the first run of a busy instance starts recent."""
CAPABILITY = "authz_store"


@dataclass(frozen=True, slots=True)
class Row:
    """One trail row, normalised."""

    created_at: datetime
    actor: str | None
    action: str
    target: str
    metadata: Mapping[str, Any]
    before: Any = None
    after: Any = None
    id: str | None = None


def _time(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value  # noqa: PLR2004  (milliseconds)
        return datetime.fromtimestamp(seconds, UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def parse_rows(body: object) -> tuple[list[Row], int | None]:
    """``{data, meta}`` (or a bare list) → rows and the total page count when the runtime says it."""
    items: object = body
    pages: int | None = None
    if isinstance(body, Mapping):
        envelope = cast("Mapping[str, Any]", body)
        items = envelope.get("data", [])
        paging: object = envelope.get("meta")
        if isinstance(paging, Mapping):
            total = cast("Mapping[str, Any]", paging).get("total_pages")
            pages = total if isinstance(total, int) else None
    rows: list[Row] = []
    if not isinstance(items, list):
        return rows, pages
    for raw in cast("list[object]", items):
        if not isinstance(raw, Mapping):
            continue
        item = cast("Mapping[str, Any]", raw)
        created = _time(item.get("created_at", item.get("timestamp")))
        if created is None:
            continue
        metadata = item.get("metadata")
        meta: Mapping[str, Any] = cast("Mapping[str, Any]", metadata) if isinstance(metadata, Mapping) else {}
        allowed = item.get("allowed")
        action = str(item.get("action") or "")
        if not action and isinstance(allowed, bool):
            action = "access.allowed" if allowed else "access.denied"
        subject = item.get("actor", item.get("subject"))
        target = item.get("target")
        if target is None and item.get("path"):
            target = f"{item.get('method') or ''} {item['path']}".strip()
        identifier = item.get("event_id", item.get("id"))
        rows.append(
            Row(
                created_at=created,
                actor=str(subject) if subject else None,
                action=action or "unknown",
                target=str(target or ""),
                metadata={
                    **meta,
                    **({"required": item["required"]} if "required" in item and "required" not in meta else {}),
                    **({"scopes": item["scopes"]} if "scopes" in item and "scopes" not in meta else {}),
                    **({"reason": item["reason"]} if item.get("reason") and "reason" not in meta else {}),
                },
                before=item.get("before"),
                after=item.get("after"),
                id=str(identifier) if identifier else None,
            )
        )
    return rows, pages


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [value]
    if isinstance(value, list):
        return [str(item) for item in cast("list[object]", value)]
    return []


def _items(value: object) -> list[str]:
    """A role's scopes or a subject's roles, one line each."""
    if isinstance(value, list):
        return [
            item if isinstance(item, str) else json.dumps(item, sort_keys=True) for item in cast("list[object]", value)
        ]
    return _strings(value)


def actor_of(subject: str | None) -> Actor:
    if not subject:
        return Actor(kind="anonymous", id="anonymous", display="Someone")
    if subject.startswith("sa:"):
        return Actor(kind="service_account", id=subject, display=subject)
    if subject.startswith("usr_") or "@" in subject:
        return Actor(kind="user", id=subject, display=subject)
    if subject in {"agnostic-system", "__scheduler__"}:
        return Actor(kind="system", id=subject, display="Scheduler" if subject == "__scheduler__" else "Agnostic")
    return Actor(kind="anonymous", id=subject, display=subject)


def via_of(subject: str | None, metadata: Mapping[str, Any]) -> str:
    """AgentOS-native service accounts call with ``agno_pat_`` tokens; everyone else with a JWT."""
    reference = str(metadata.get("token") or "")
    kind = str(metadata.get("token_kind") or "")
    if reference.startswith("agno_pat_") or kind == "pat" or (subject or "").startswith("sa:"):
        return "native-pat"
    return "jwt"


def source_id(stream: Stream, row: Row, occurrence: int) -> str:
    if row.id:
        return f"{stream}:{row.id}"
    content = json.dumps(
        [
            int(row.created_at.timestamp()),
            row.actor,
            row.action,
            row.target,
            dict(row.metadata),
            row.before,
            row.after,
        ],
        sort_keys=True,
        default=str,
    )
    return f"{stream}:{hashlib.sha256(content.encode()).hexdigest()[:40]}:{occurrence}"


def entry_from_row(stream: Stream, row: Row, instance: Instance, occurrence: int) -> IngestedEntry:
    actor = actor_of(row.actor)
    route = row.target or "a route"
    if stream == "decisions":
        required = _strings(row.metadata.get("required"))
        held = set(_strings(row.metadata.get("scopes")))
        denied = row.action.endswith("denied")
        missing = tuple(scope for scope in required if scope not in held) if denied else ()
        reason = str(row.metadata.get("reason") or "")
        denial = None
        if denied:
            needs = ", ".join(missing or tuple(required)) or "a scope the token doesn't hold"
            denial = f"{route} on {instance.display_name} needs {needs}." + (f" AgentOS: {reason}." if reason else "")
        verb = "was denied" if denied else "called"
        return IngestedEntry(
            source_event_id=source_id(stream, row, occurrence),
            occurred_at=row.created_at,
            action="agentos.access",
            actor=actor,
            summary=f"{actor.display} {verb} {route} on {instance.display_name}",
            via=via_of(row.actor, row.metadata),
            resource_kind="route",
            resource_id=row.target or None,
            resource_display=row.target or None,
            instance_id=instance.id,
            decision="denied" if denied else "allowed",
            scope_checked=required[0] if required else None,
            missing_scopes=missing,
            response_status=403 if denied else None,
            denial_reason=denial,
        )
    action = f"agentos.{row.action}" if row.action else "agentos.change"
    diff = None
    if row.before is not None or row.after is not None:
        before = _items(row.before)
        after = _items(row.after)
        lines = [{"op": "-", "text": item} for item in before if item not in after]
        lines += [{"op": "+", "text": item} for item in after if item not in before]
        diff = {"title": f"{row.action} on {instance.display_name}", "lines": lines, "note": None}
    return IngestedEntry(
        source_event_id=source_id(stream, row, occurrence),
        occurred_at=row.created_at,
        action=action,
        actor=actor,
        summary=f"{actor.display}: {row.action} {row.target} on {instance.display_name}".replace("  ", " "),
        via=via_of(row.actor, row.metadata),
        resource_kind="agentos_authz",
        resource_id=row.target or None,
        resource_display=row.target or None,
        instance_id=instance.id,
        diff=diff,
    )


def entries(stream: Stream, rows: Sequence[Row], instance: Instance) -> list[IngestedEntry]:
    """Identical rows of the same second (no id to tell them apart) are numbered in the order the runtime sent."""
    seen: dict[str, int] = {}
    result: list[IngestedEntry] = []
    for row in sorted(rows, key=lambda item: item.created_at):
        base = source_id(stream, row, 0)
        occurrence = seen.get(base, 0)
        seen[base] = occurrence + 1
        result.append(entry_from_row(stream, row, instance, occurrence))
    return result


class IngestAuthz:
    def __init__(self, instances: InstancesFacade, audit: AuditLog, cursors: IngestCursors) -> None:
        self._instances = instances
        self._audit = audit
        self._cursors = cursors

    async def __call__(self) -> dict[str, int]:
        """Events newly stored, per instance."""
        stored: dict[str, int] = {}
        for instance in await self._instances.list():
            if instance.status != InstanceStatus.CONNECTED:
                continue
            if await self._instances.capability(instance, CAPABILITY) != "available":
                continue
            count = 0
            for stream in STREAMS:
                try:
                    count += await self._stream(instance, stream)
                except RuntimeNotFoundError:
                    continue  # this trail is turned off on the runtime
                except AgentOSError as exc:
                    log.warning("gateway.ingest_failed", instance=instance.id, stream=stream, error=str(exc))
            stored[instance.id] = count
        return stored

    async def _stream(self, instance: Instance, stream: Stream) -> int:
        cursor = await self._cursors.get(instance.id, stream)
        since = datetime.fromtimestamp(int(cursor), UTC) if cursor and cursor.isdigit() else None
        rows: list[Row] = []
        for page in range(1, MAX_PAGES + 1):
            body = await self._instances.system_call(
                instance,
                "GET",
                STREAMS[stream],
                params={"page": page, "limit": PAGE_LIMIT, "sort_by": "created_at", "sort_order": "desc"},
            )
            batch, pages = parse_rows(body)
            fresh = [row for row in batch if since is None or row.created_at >= since]
            rows.extend(fresh)
            if len(fresh) < len(batch) or len(batch) < PAGE_LIMIT or (pages is not None and page >= pages):
                break
        if not rows:
            return 0
        stored = await self._audit.ingest(entries(stream, rows, instance))
        newest = max(row.created_at for row in rows)
        await self._cursors.save(instance.id, stream, str(int(newest.timestamp())))
        return stored
