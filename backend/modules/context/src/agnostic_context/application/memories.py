"""Memory page actions the AgentOS memory routes don't offer.

Likely duplicates, the run a memory came from, and an audited "optimize" (the AgentOS summarize strategy, previewed
before it is applied).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_context.application.calls import FORBIDDEN, ContextCalls, page_items
from agnostic_context.domain.files import parse_time
from agnostic_context.domain.memories import (
    SOURCE_SLACK,
    Duplicate,
    MemoryText,
    RunRef,
    find_duplicates,
    source_run,
)
from agnostic_kernel.auth import Principal

PAGE = 100
READ_SCOPE = "memories:read"


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    user_id: str
    threshold: float
    scanned: int
    total: int | None
    duplicates: Sequence[Duplicate]
    method: Literal["trigram"] = "trigram"

    @property
    def partial(self) -> bool:
        return self.total is not None and self.total > self.scanned


class FindDuplicates:
    """Compare one user's memories pairwise; read as the viewer, so isolation decides whose memories are compared."""

    def __init__(self, calls: ContextCalls, threshold: float, max_scan: int) -> None:
        self._calls = calls
        self._threshold = threshold
        self._max_scan = max_scan

    async def __call__(
        self, principal: Principal, instance_ref: str, user_id: str, *, db_id: str | None = None
    ) -> DuplicateReport:
        instance = await self._calls.instance(instance_ref)
        rows: list[dict[str, Any]] = []
        total: int | None = None
        page = 1
        while len(rows) < self._max_scan:
            body = await self._calls.json(
                principal,
                instance,
                "/memories",
                params={
                    "user_id": user_id,
                    "db_id": db_id,
                    "page": page,
                    "limit": PAGE,
                    "sort_by": "updated_at",
                    "sort_order": "desc",
                },
            )
            items, total = page_items(body)
            rows.extend(items)
            if len(items) < PAGE or (total is not None and len(rows) >= total):
                break
            page += 1
        rows = rows[: self._max_scan]
        memories = [
            MemoryText(str(row["memory_id"]), str(row.get("memory") or ""), parse_time(row.get("updated_at")))
            for row in rows
            if row.get("memory_id")
        ]
        return DuplicateReport(
            user_id=user_id,
            threshold=self._threshold,
            scanned=len(memories),
            total=total,
            duplicates=find_duplicates(memories, self._threshold),
        )


@dataclass(frozen=True, slots=True)
class MemorySource:
    memory_id: str
    user_id: str | None
    agent_id: str | None
    team_id: str | None
    session_id: str | None
    run_id: str | None
    input: str | None
    run_at: datetime | None
    run_status: str | None
    reason: str | None
    """Why there is no source run."""


def _run_input(run: dict[str, Any]) -> str | None:
    value: object = run.get("run_input")
    if value is None:
        value = run.get("input")
    if isinstance(value, dict):
        nested: object = cast("dict[str, Any]", value).get("input_content")
        if nested is not None:
            value = nested
    if value is None:
        return None
    return value if isinstance(value, str) else str(cast("object", value))


def _run_refs(session_id: str, payload: object) -> list[RunRef]:
    refs: list[RunRef] = []
    for run in page_items(payload)[0]:
        created = parse_time(run.get("created_at"))
        if created is not None and run.get("run_id"):
            status = cast("str | None", run.get("status"))
            refs.append(RunRef(session_id, str(run["run_id"]), created, _run_input(run), status))
    return refs


class FindMemorySource:
    """The run a memory most likely came from: the memory's user and agent (or team), its sessions, their runs."""

    def __init__(self, calls: ContextCalls, max_sessions: int) -> None:
        self._calls = calls
        self._max_sessions = max_sessions

    async def __call__(
        self, principal: Principal, instance_ref: str, memory_id: str, *, db_id: str | None = None
    ) -> MemorySource:
        instance = await self._calls.instance(instance_ref)
        memory = cast(
            "dict[str, Any]",
            await self._calls.json(principal, instance, f"/memories/{memory_id}", params={"db_id": db_id}),
        )
        user_id = cast("str | None", memory.get("user_id"))
        agent_id = cast("str | None", memory.get("agent_id"))
        team_id = cast("str | None", memory.get("team_id"))
        written = parse_time(memory.get("updated_at"))

        def none(reason: str) -> MemorySource:
            return MemorySource(memory_id, user_id, agent_id, team_id, None, None, None, None, None, reason)

        component, kind = (agent_id, "agent") if agent_id else (team_id, "team")
        if not component:
            return none("This memory was added directly, not by an agent or team.")
        if not user_id or written is None:
            return none("This memory has no user or time to match a run against.")

        response = await self._calls.call(
            principal,
            instance,
            "GET",
            "/sessions",
            params={
                "type": kind,
                "component_id": component,
                "user_id": user_id,
                "sort_by": "updated_at",
                "sort_order": "desc",
                "limit": self._max_sessions,
                "page": 1,
            },
        )
        if response.status == FORBIDDEN:
            return none("Finding the source run needs sessions:read on this instance.")
        if not response.ok:
            return none("The instance didn't list the sessions to match against.")
        sessions = [
            str(session["session_id"])
            for session in page_items(response.body)[0]
            if session.get("session_id")
            and (parse_time(session.get("created_at")) or written) <= written + SOURCE_SLACK
        ]

        async def runs_of(session_id: str) -> list[RunRef]:
            reply = await self._calls.call(
                principal, instance, "GET", f"/sessions/{session_id}/runs", params={"type": kind}
            )
            return _run_refs(session_id, reply.body) if reply.ok else []

        runs = [run for found in await asyncio.gather(*(runs_of(item) for item in sessions)) for run in found]
        match = source_run(runs, written)
        if match is None:
            return none(f"No run of {component} for {user_id} before this memory was written.")
        return MemorySource(
            memory_id=memory_id,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            session_id=match.session_id,
            run_id=match.run_id,
            input=match.input,
            run_at=match.created_at,
            run_status=match.status,
            reason=None,
        )


@dataclass(frozen=True, slots=True)
class Optimization:
    user_id: str
    applied: bool
    memories: Sequence[dict[str, Any]]
    memories_before: int
    memories_after: int
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    reduction_percentage: float


class OptimizeMemories:
    """``POST /optimize-memories`` as the person; applying is audited with the counts."""

    def __init__(self, calls: ContextCalls, audit: AuditLog) -> None:
        self._calls = calls
        self._audit = audit

    async def __call__(
        self,
        principal: Principal,
        instance_ref: str,
        user_id: str,
        *,
        apply: bool,
        model: str | None = None,
        db_id: str | None = None,
    ) -> Optimization:
        instance = await self._calls.instance(instance_ref)
        body: dict[str, Any] = {"user_id": user_id, "apply": apply}
        if model:
            body["model"] = model
        result = cast(
            "dict[str, Any]",
            await self._calls.json(
                principal, instance, "/optimize-memories", method="POST", params={"db_id": db_id}, body=body
            ),
        )
        optimization = Optimization(
            user_id=user_id,
            applied=apply,
            memories=[cast("dict[str, Any]", item) for item in cast("list[Any]", result.get("memories") or [])],
            memories_before=int(result.get("memories_before") or 0),
            memories_after=int(result.get("memories_after") or 0),
            tokens_before=int(result.get("tokens_before") or 0),
            tokens_after=int(result.get("tokens_after") or 0),
            tokens_saved=int(result.get("tokens_saved") or 0),
            reduction_percentage=float(result.get("reduction_percentage") or 0.0),
        )
        if apply:
            _ = await self._audit.record_now(
                AuditEntry(
                    action="context.memories.optimized",
                    actor=actor_of(principal),
                    resource_kind="user_memories",
                    resource_id=user_id,
                    resource_display=f"memories of {user_id}",
                    instance_id=instance.id,
                    response_status=200,
                    fields={
                        "user": user_id,
                        "where": instance.display_name,
                        "before": str(optimization.memories_before),
                        "after": str(optimization.memories_after),
                        "tokens_saved": str(optimization.tokens_saved),
                    },
                    diff={
                        "memories": {"before": optimization.memories_before, "after": optimization.memories_after},
                        "tokens": {"before": optimization.tokens_before, "after": optimization.tokens_after},
                    },
                )
            )
        return optimization
