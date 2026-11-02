"""Where a workspace file came from.

With agnostic-bridge: every file-tool call the instance traced on that path. Without it: the newest traces the viewer
can read, searched for those calls (best effort).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

from agnostic_context.application.calls import FORBIDDEN, ContextCalls, page_items
from agnostic_context.domain.files import FileEvent, FileProvenance, file_events, normalize, parse_time, summarize
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal

BRIDGE_PROVENANCE = "GET /agnostic/v1/files/provenance"
DETAIL_CONCURRENCY = 8


def _bridge_event(raw: dict[str, Any]) -> FileEvent | None:
    action = raw.get("action")
    if action not in {"write", "read", "delete"}:
        return None
    kind = raw.get("component_kind")
    return FileEvent(
        action=action,
        tool=str(raw.get("tool") or ""),
        path=str(raw.get("path") or ""),
        trace_id=str(raw.get("trace_id") or ""),
        run_id=cast("str | None", raw.get("run_id")),
        session_id=cast("str | None", raw.get("session_id")),
        component_kind=kind if kind in {"agent", "team", "workflow"} else None,
        component_id=cast("str | None", raw.get("component_id")),
        step=cast("str | None", raw.get("step")),
        status=str(raw.get("status") or "OK").upper(),
        run_status=str(raw.get("run_status") or "OK").upper(),
        at=parse_time(raw.get("at")),
    )


class FindFileProvenance:
    def __init__(self, calls: ContextCalls, max_traces: int) -> None:
        self._calls = calls
        self._max_traces = max_traces

    async def __call__(
        self, principal: Principal, instance_ref: str, path: str, *, namespace: str | None = None
    ) -> tuple[FileProvenance | None, str | None]:
        """The provenance, or ``None`` and the reason it couldn't be built."""
        instance = await self._calls.instance(instance_ref)
        await self._calls.require(principal, "filesystem:read", instance)
        target = normalize(path)
        if await self._calls.bridge_serves(instance, BRIDGE_PROVENANCE):
            response = await self._calls.call(
                principal,
                instance,
                "GET",
                "/agnostic/v1/files/provenance",
                params={"path": target, "namespace": namespace},
            )
            if response.status == FORBIDDEN:
                return None, "Provenance needs traces:read on this instance."
            if response.ok and isinstance(response.body, dict):
                body = cast("dict[str, Any]", response.body)
                events = [
                    event
                    for raw in cast("list[Any]", body.get("events") or [])
                    if isinstance(raw, dict) and (event := _bridge_event(cast("dict[str, Any]", raw)))
                ]
                return summarize(target, events, exact=True, scanned_traces=int(body.get("scanned_traces") or 0)), None
        return await self._scan(principal, instance, target)

    async def _scan(
        self, principal: Principal, instance: Instance, path: str
    ) -> tuple[FileProvenance | None, str | None]:
        listing = await self._calls.call(
            principal, instance, "GET", "/traces", params={"limit": self._max_traces, "page": 1}
        )
        if listing.status == FORBIDDEN:
            return None, "Provenance needs traces:read on this instance."
        if not listing.ok:
            return None, "The instance didn't list its traces."
        trace_ids = [str(item["trace_id"]) for item in page_items(listing.body)[0] if item.get("trace_id")]
        gate = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def events_of(trace_id: str) -> list[FileEvent]:
            async with gate:
                detail = await self._calls.call(principal, instance, "GET", f"/traces/{trace_id}")
            if not detail.ok or not isinstance(detail.body, dict):
                return []
            return file_events(cast("dict[str, Any]", detail.body), path)

        found = await asyncio.gather(*(events_of(trace_id) for trace_id in trace_ids))
        events = [event for batch in found for event in batch]
        return summarize(path, events, exact=False, scanned_traces=len(trace_ids)), None
