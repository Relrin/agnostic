"""Where a workspace file came from.

File-tool calls (``write_file``, ``read_file``…) found in traces, and the "Where this came from" summary built from
them: the last write, and who has read the file since.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

type FileAction = Literal["write", "read", "delete"]

TOOL_ACTIONS: Mapping[str, FileAction] = {
    "write_file": "write",
    "awrite_file": "write",
    "append_file": "write",
    "edit_file": "write",
    "aedit_file": "write",
    "move_file": "write",
    "amove_file": "write",
    "read_file": "read",
    "aread_file": "read",
    "delete_file": "delete",
    "adelete_file": "delete",
}
_PATH_ARGUMENTS = ("path", "file_path", "dst", "destination", "src", "source")


def normalize(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.strip("/")


def same_file(left: str, right: str) -> bool:
    """Equal relative paths, or one is the other under a mount prefix (``/workspace/reports/x.md``)."""
    a, b = normalize(left), normalize(right)
    return bool(a and b) and (a == b or a.endswith(f"/{b}") or b.endswith(f"/{a}"))


@dataclass(frozen=True, slots=True)
class FileEvent:
    action: FileAction
    tool: str
    path: str
    trace_id: str
    run_id: str | None
    session_id: str | None
    component_kind: Literal["agent", "team", "workflow"] | None
    component_id: str | None
    step: str | None
    """The workflow step (or the agent) the tool ran under."""
    status: str
    """The tool call's status: OK or ERROR."""
    run_status: str
    at: datetime | None


def _dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _arguments(node: Mapping[str, Any]) -> dict[str, Any]:
    """Tool arguments from the span input (a JSON object, as agno records it) or its ``parameters`` metadata."""
    for candidate in (node.get("input"), _dict(node.get("metadata")).get("parameters")):
        if isinstance(candidate, dict):
            return cast("dict[str, Any]", candidate)
        if isinstance(candidate, str) and candidate.strip().startswith("{"):
            try:
                parsed: object = json.loads(candidate)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return cast("dict[str, Any]", parsed)
    return {}


def _tool_name(node: Mapping[str, Any]) -> str:
    metadata = _dict(node.get("metadata"))
    return str(metadata.get("tool_name") or node.get("name") or "")


def _component(raw: Mapping[str, Any]) -> tuple[Literal["agent", "team", "workflow"] | None, str | None]:
    for key, kind in (("workflow_id", "workflow"), ("team_id", "team"), ("agent_id", "agent")):
        if raw.get(key):
            return cast("Literal['agent', 'team', 'workflow']", kind), str(raw[key])
    return None, None


def file_events(trace: Mapping[str, Any], path: str) -> list[FileEvent]:
    """File-tool calls on ``path`` in one ``GET /traces/{trace_id}`` body."""
    kind, component = _component(trace)
    events: list[FileEvent] = []

    def visit(node: Mapping[str, Any], step: str | None) -> None:
        node_type = str(node.get("type") or "").upper()
        name = str(node.get("name") or "")
        if node.get("step_type") or node_type in {"STEP", "AGENT", "TEAM"}:
            step = name or step
        tool = _tool_name(node)
        action = TOOL_ACTIONS.get(tool)
        if action is not None and (node_type in {"TOOL", ""} or tool == name):
            arguments = _arguments(node)
            touched = next(
                (
                    str(arguments[key])
                    for key in _PATH_ARGUMENTS
                    if isinstance(arguments.get(key), str) and same_file(str(arguments[key]), path)
                ),
                None,
            )
            if touched is not None:
                events.append(
                    FileEvent(
                        action=action,
                        tool=tool,
                        path=touched,
                        trace_id=str(trace.get("trace_id") or ""),
                        run_id=cast("str | None", trace.get("run_id")),
                        session_id=cast("str | None", trace.get("session_id")),
                        component_kind=kind,
                        component_id=component,
                        step=step,
                        status=str(node.get("status") or "OK").upper(),
                        run_status=str(trace.get("status") or "OK").upper(),
                        at=parse_time(node.get("start_time")) or parse_time(trace.get("start_time")),
                    )
                )
        for child in cast("list[Any]", node.get("spans") or []):
            if isinstance(child, dict):
                visit(cast("dict[str, Any]", child), step)

    for root in cast("list[Any]", trace.get("tree") or []):
        if isinstance(root, dict):
            visit(cast("dict[str, Any]", root), None)
    return events


@dataclass(frozen=True, slots=True)
class Reader:
    component_id: str
    step: str | None
    count: int


@dataclass(frozen=True, slots=True)
class FileProvenance:
    path: str
    written: FileEvent | None
    """The newest successful write (a failed one only when no write succeeded)."""
    partial: bool
    """The run that last wrote the file ended in error, so the file may stop part-way."""
    writes: Sequence[FileEvent]
    read_by: Sequence[Reader]
    """Components that read the file after its last write, most reads first."""
    exact: bool
    """From agnostic-bridge (every trace of the namespace's agents) rather than a best-effort scan."""
    scanned_traces: int


def _newest(events: Iterable[FileEvent]) -> list[FileEvent]:
    floor = datetime.min.replace(tzinfo=UTC)
    return sorted(events, key=lambda event: event.at or floor, reverse=True)


def summarize(path: str, events: Iterable[FileEvent], *, exact: bool, scanned_traces: int) -> FileProvenance:
    ordered = _newest(events)
    writes = [event for event in ordered if event.action == "write"]
    written = next((event for event in writes if event.status == "OK"), writes[0] if writes else None)
    since = written.at if written is not None else None
    counts: dict[tuple[str, str | None], int] = {}
    for event in ordered:
        if event.action != "read" or event.component_id is None:
            continue
        if since is not None and event.at is not None and event.at < since:
            continue
        key = (event.component_id, event.step if event.component_kind == "workflow" else None)
        counts[key] = counts.get(key, 0) + 1
    readers = [Reader(component, step, total) for (component, step), total in counts.items()]
    readers.sort(key=lambda reader: (-reader.count, reader.component_id))
    return FileProvenance(
        path=path,
        written=written,
        partial=written is not None and written.run_status == "ERROR",
        writes=writes,
        read_by=readers,
        exact=exact,
        scanned_traces=scanned_traces,
    )
