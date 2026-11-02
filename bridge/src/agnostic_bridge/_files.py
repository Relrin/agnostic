"""``GET /agnostic/v1/files/provenance``: which runs wrote and read a workspace file.

AgentOS's filesystem routes say what a file holds, not where it came from. Agent file tools (``write_file``,
``read_file``, ``edit_file``…) are traced like any tool: an OpenInference ``TOOL`` span with ``tool.name`` and the
call's arguments as JSON in ``tool.parameters``. This route reads the newest traces from the OS db, keeps the
file-tool spans whose path argument names the file, and returns them as events, newest first. The control plane
turns them into "Where this came from" (the last write, who read the file since).

- **Access**: ``filesystem:read`` and ``traces:read`` (:data:`~agnostic_bridge.SCOPE_MAPPINGS`). Under user
  isolation a non-admin caller only sees traces of their own runs, as on ``GET /traces``.
- **Cost**: at most ``limit`` traces (newest first) and their spans; nothing is cached or stored.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.middleware.user_scope import get_scoped_user_id
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os import AgentOS

PROVENANCE_PATH = "/files/provenance"

TOOL_ACTIONS: dict[str, Literal["write", "read", "delete"]] = {
    "write_file": "write",
    "append_file": "write",
    "edit_file": "write",
    "move_file": "write",
    "read_file": "read",
    "delete_file": "delete",
}
_PATH_ARGUMENTS = ("path", "file_path", "dst", "destination", "src", "source")
_STEP_KINDS = {"CHAIN", "AGENT"}


class FileEvent(BaseModel):
    action: Literal["write", "read", "delete"]
    tool: str
    path: str = Field(description="The path as the tool was called with it")
    trace_id: str
    run_id: str | None = None
    session_id: str | None = None
    component_kind: Literal["agent", "team", "workflow"] | None = None
    component_id: str | None = None
    step: str | None = Field(None, description="The workflow step or agent the tool ran under")
    status: str = Field(description="The tool call: OK or ERROR")
    run_status: str = Field(description="The whole run: OK or ERROR")
    at: datetime | None = None


class FileProvenanceResponse(BaseModel):
    path: str
    namespace: str | None = None
    scanned_traces: int
    events: list[FileEvent]


def normalize(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.strip("/")


def same_file(left: str, right: str) -> bool:
    """Equal relative paths, or one is the other under a mount prefix (``/workspace/reports/x.md``)."""
    a, b = normalize(left), normalize(right)
    return bool(a and b) and (a == b or a.endswith(f"/{b}") or b.endswith(f"/{a}"))


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _arguments(attributes: dict[str, Any]) -> dict[str, Any]:
    for key in ("tool.parameters", "input.value"):
        value = attributes.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                parsed = json.loads(value)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def trace_events(trace: Any, spans: list[Any], path: str) -> list[FileEvent]:
    """File-tool spans of one trace that touch ``path``."""
    by_id = {_field(span, "span_id"): span for span in spans}
    kind: Literal["agent", "team", "workflow"] | None = None
    component: str | None = None
    for key, name in (("workflow_id", "workflow"), ("team_id", "team"), ("agent_id", "agent")):
        if _field(trace, key):
            kind, component = name, str(_field(trace, key))  # type: ignore[assignment]
            break

    def step_of(span: Any) -> str | None:
        parent = by_id.get(_field(span, "parent_span_id"))
        while parent is not None:
            attributes = _field(parent, "attributes") or {}
            if str(attributes.get("openinference.span.kind", "")).upper() in _STEP_KINDS:
                return str(_field(parent, "name"))
            parent = by_id.get(_field(parent, "parent_span_id"))
        return None

    events: list[FileEvent] = []
    for span in spans:
        attributes = _field(span, "attributes") or {}
        tool = str(attributes.get("tool.name") or _field(span, "name") or "")
        action = TOOL_ACTIONS.get(tool)
        if action is None:
            continue
        arguments = _arguments(attributes)
        touched = next(
            (str(arguments[key]) for key in _PATH_ARGUMENTS if isinstance(arguments.get(key), str)
             and same_file(str(arguments[key]), path)),
            None,
        )  # fmt: skip
        if touched is None:
            continue
        events.append(
            FileEvent(
                action=action,
                tool=tool,
                path=touched,
                trace_id=str(_field(trace, "trace_id")),
                run_id=_field(trace, "run_id"),
                session_id=_field(trace, "session_id"),
                component_kind=kind,
                component_id=component,
                step=step_of(span),
                status=str(_field(span, "status_code") or "OK").upper().removeprefix("STATUS_CODE_"),
                run_status=str(_field(trace, "status") or "OK").upper(),
                at=_time(_field(span, "start_time")),
            )
        )
    return events


async def _db_call(db: BaseDb | AsyncBaseDb, method: str, **kwargs: Any) -> Any:
    function = getattr(db, method)
    if isinstance(db, AsyncBaseDb):
        return await function(**kwargs)
    return await asyncio.to_thread(function, **kwargs)


def add_file_routes(router: APIRouter, agent_os: AgentOS) -> None:
    @router.get(
        PROVENANCE_PATH,
        operation_id="agnostic_bridge_file_provenance",
        summary="Where a workspace file came from",
        description=(
            "File-tool calls (write_file, read_file, edit_file…) on one path, from the newest traces in the OS db, "
            "newest first. Needs filesystem:read and traces:read; isolated callers see their own runs only."
        ),
        response_model=FileProvenanceResponse,
        responses={503: {"description": "The AgentOS has no db, so no traces"}},
    )
    async def file_provenance(
        request: Request,
        path: str = Query(..., min_length=1, description="File path inside the filesystem"),
        namespace: str | None = Query(None, description="Filesystem namespace (informational)"),
        limit: int = Query(200, ge=1, le=1000, description="Newest traces to read"),
    ) -> FileProvenanceResponse:
        db = agent_os.db
        if not isinstance(db, (BaseDb, AsyncBaseDb)):
            raise HTTPException(status_code=503, detail="This AgentOS has no db, so no traces to read")
        user_id = get_scoped_user_id(request)
        traces, _ = await _db_call(db, "get_traces", user_id=user_id, limit=limit, page=1)
        events: list[FileEvent] = []
        for trace in traces or []:
            spans = await _db_call(db, "get_spans", trace_id=_field(trace, "trace_id"))
            events.extend(trace_events(trace, list(spans or []), path))
        floor = datetime.min.replace(tzinfo=timezone.utc)
        events.sort(key=lambda event: event.at or floor, reverse=True)
        return FileProvenanceResponse(
            path=normalize(path), namespace=namespace, scanned_traces=len(traces or []), events=events
        )
