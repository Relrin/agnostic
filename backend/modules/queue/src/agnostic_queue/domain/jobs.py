"""Durable-queue jobs as AgentOS reports them, the attempts narrative, checkpoints, and the worker picture.

A job is the queue's record of a background run (its id *is* the run id). Job status (queued, running, failed…) is
not run status (the run can be ERROR while the job is failed, or PAUSED while the job waits for a person), so both
are shown. AgentOS keeps no attempt history: the timeline is rebuilt from the job's own fields.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

type TimelineState = Literal["done", "error", "now"]

STATUSES = ("queued", "running", "paused", "failed", "completed", "cancelled")
FAMILIES = {"agent": "agents", "team": "teams", "workflow": "workflows"}


def parse_time(value: object) -> datetime | None:
    if isinstance(value, bool) or value in {None, ""}:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _str(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


@dataclass(frozen=True, slots=True)
class QueueJob:
    id: str
    component_type: str | None
    component_id: str | None
    session_id: str | None
    user_id: str | None
    job_type: str | None
    status: str
    attempt: int
    max_attempts: int
    idempotency_key: str | None
    locked_by: str | None
    locked_at: datetime | None
    available_at: datetime | None
    error: str | None
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None
    payload: Mapping[str, Any]

    @classmethod
    def parse(cls, body: Mapping[str, Any]) -> QueueJob:
        return cls(
            id=str(body.get("id") or ""),
            component_type=_str(body.get("component_type")),
            component_id=_str(body.get("component_id")),
            session_id=_str(body.get("session_id")),
            user_id=_str(body.get("user_id")),
            job_type=_str(body.get("job_type")),
            status=str(body.get("status") or "queued").lower(),
            attempt=int(body.get("attempt") or 0),
            max_attempts=int(body.get("max_attempts") or 1),
            idempotency_key=_str(body.get("idempotency_key")),
            locked_by=_str(body.get("locked_by")),
            locked_at=parse_time(body.get("locked_at")),
            available_at=parse_time(body.get("available_at")),
            error=_str(body.get("error")),
            created_at=parse_time(body.get("created_at")),
            updated_at=parse_time(body.get("updated_at")),
            completed_at=parse_time(body.get("completed_at")),
            payload=cast("Mapping[str, Any]", body.get("payload") or {}),
        )

    @property
    def family(self) -> str | None:
        """The AgentOS route family of the job's component (``agents``…)."""
        return FAMILIES.get((self.component_type or "").lower().rstrip("s"))

    @property
    def deployment(self) -> str | None:
        return _str(self.payload.get("deployment_id"))

    def detail(self, run_status: str | None = None) -> str | None:
        """The sub-line under the status badge."""
        if self.status == "queued":
            return "not claimed" if not self.locked_by else f"claimed by {self.locked_by}"
        if self.status == "running":
            return self.locked_by
        if self.status == "failed":
            return f"run {run_status.upper()}" if run_status else "failed"
        if self.status == "completed" and self.created_at and self.completed_at:
            return f"{(self.completed_at - self.created_at).total_seconds():.1f} s"
        return None


@dataclass(frozen=True, slots=True)
class AttemptEntry:
    text: str
    at: datetime | None
    detail: str | None
    state: TimelineState


def attempts_timeline(job: QueueJob, *, retry_delay_seconds: float | None) -> list[AttemptEntry]:
    entries = [
        AttemptEntry(
            "Accepted · 202 with run_id",
            job.created_at,
            f"Idempotency-Key {job.idempotency_key}" if job.idempotency_key else None,
            "done",
        )
    ]
    if job.attempt > 1:
        delay = f" · retry_delay_seconds {retry_delay_seconds:g}" if retry_delay_seconds else ""
        earlier = "Attempt 1 was" if job.attempt == 2 else f"Attempts 1–{job.attempt - 1} were"  # noqa: PLR2004
        entries.append(AttemptEntry(f"{earlier} retried", None, f"restarted from the beginning{delay}", "error"))
    if job.attempt >= 1 and (job.locked_by or job.locked_at):
        entries.append(
            AttemptEntry(
                f"Attempt {job.attempt} claimed by {job.locked_by or 'a worker'}",
                job.locked_at,
                None,
                "now" if job.status == "running" else "done",
            )
        )
    if job.status == "failed":
        final = job.attempt >= job.max_attempts
        entries.append(
            AttemptEntry(
                f"Attempt {job.attempt} ended in ERROR · job marked failed",
                job.completed_at or job.updated_at,
                f"max_attempts {job.max_attempts} reached" if final else job.error,
                "error",
            )
        )
    elif job.status == "completed":
        entries.append(AttemptEntry(f"Attempt {job.attempt} completed", job.completed_at, None, "done"))
    elif job.status == "cancelled":
        entries.append(AttemptEntry("Cancelled", job.completed_at or job.updated_at, None, "done"))
    elif job.status == "paused":
        entries.append(AttemptEntry("Paused for human input", job.updated_at, "Not retried as a failure", "now"))
    elif job.status == "queued":
        entries.append(AttemptEntry("Waiting for a free slot", job.available_at, None, "now"))
    return entries


@dataclass(frozen=True, slots=True)
class Checkpoint:
    number: int
    message_index: int
    continue_from: str
    title: str
    preview: str | None
    role: str | None
    reason: str | None
    created_at: datetime | None
    is_latest: bool

    @classmethod
    def parse(cls, body: Mapping[str, Any], position: int) -> Checkpoint:
        index = body.get("message_index")
        role = _str(body.get("message_role"))
        preview = _str(body.get("message_preview"))
        reason = _str(body.get("reason"))
        if role == "tool" and preview:
            title = f"After {preview.split('(')[0].split(':')[0][:60]}"
        elif reason == "end":
            title = "End of the run"
        else:
            title = f"After the {role or 'previous'} message"
        return cls(
            number=int(body.get("checkpoint_id") or position),
            message_index=int(index) if isinstance(index, int | str) and str(index).lstrip("-").isdigit() else position,
            continue_from=str(body.get("continue_from") or index or position),
            title=title,
            preview=preview,
            role=role,
            reason=reason,
            created_at=parse_time(body.get("created_at")),
            is_latest=bool(body.get("is_latest")),
        )


@dataclass(frozen=True, slots=True)
class Worker:
    name: str
    """The bridge's replica id, or the queue worker id when only the jobs mention it."""
    worker_id: str | None
    heartbeat_at: datetime | None
    slots_busy: int
    slots_total: int | None
    deployment: str | None
    source: Literal["bridge", "jobs"]


def merge_workers(
    snapshots: Iterable[Mapping[str, Any]],
    running: Sequence[QueueJob],
    *,
    now: datetime,
    stale_after: timedelta,
) -> list[Worker]:
    """Bridge snapshots (fresh ones), plus workers known only from ``locked_by`` of running jobs."""
    workers: list[Worker] = []
    busy: dict[str, int] = {}
    for job in running:
        if job.locked_by:
            busy[job.locked_by] = busy.get(job.locked_by, 0) + 1
    seen: set[str] = set()
    for snapshot in snapshots:
        heartbeat = parse_time(snapshot.get("heartbeat_at"))
        if heartbeat is None or now - heartbeat > stale_after:
            continue
        worker_id = _str(snapshot.get("worker_id"))
        in_flight = cast("list[Any]", snapshot.get("in_flight") or [])
        concurrency = snapshot.get("max_concurrency")
        workers.append(
            Worker(
                name=str(snapshot.get("replica_id") or worker_id or "replica"),
                worker_id=worker_id,
                heartbeat_at=heartbeat,
                slots_busy=max(len(in_flight), busy.get(worker_id or "", 0)),
                slots_total=int(concurrency) if isinstance(concurrency, int) else None,
                deployment=_str(snapshot.get("deployment_id")),
                source="bridge",
            )
        )
        if worker_id:
            seen.add(worker_id)
    workers.extend(
        Worker(
            name=worker_id,
            worker_id=worker_id,
            heartbeat_at=None,
            slots_busy=count,
            slots_total=None,
            deployment=None,
            source="jobs",
        )
        for worker_id, count in sorted(busy.items())
        if worker_id not in seen
    )
    return sorted(workers, key=lambda worker: worker.name)
