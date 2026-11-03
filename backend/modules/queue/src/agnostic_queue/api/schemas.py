"""Response bodies of ``/api/v1/instances/{instance}/queue``."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_queue.application.operate import JobDetail, Overview, Summary
from agnostic_queue.domain.jobs import AttemptEntry, Checkpoint, QueueJob, Worker

type ModeName = Literal["elevated", "admin"]


class QueueSummaryOut(BaseModel):
    instance_id: str
    counts: dict[str, int]
    oldest_queued_age_seconds: float | None
    access: ModeName | None = Field(description="How you reach the queue; None: counts only")
    explanation: str | None

    @classmethod
    def of(cls, summary: Summary) -> QueueSummaryOut:
        return cls(
            instance_id=summary.instance.id,
            counts=summary.counts,
            oldest_queued_age_seconds=summary.oldest_queued_age_seconds,
            access=summary.mode,
            explanation=summary.explanation,
        )


class QueueWorkerOut(BaseModel):
    name: str
    worker_id: str | None
    heartbeat_at: datetime | None
    slots_busy: int
    slots_total: int | None
    deployment: str | None
    source: Literal["bridge", "jobs"] = Field(description="jobs: known only from locked_by of running jobs")

    @classmethod
    def of(cls, worker: Worker) -> QueueWorkerOut:
        return cls(
            name=worker.name,
            worker_id=worker.worker_id,
            heartbeat_at=worker.heartbeat_at,
            slots_busy=worker.slots_busy,
            slots_total=worker.slots_total,
            deployment=worker.deployment,
            source=worker.source,
        )


class QueueOverviewOut(BaseModel):
    summary: QueueSummaryOut
    config: dict[str, Any] = Field(description="QueueConfig as agnostic-bridge reports it (empty without the bridge)")
    workers: list[QueueWorkerOut]
    slots_total: int | None
    paused_approvals: int | None

    @classmethod
    def of(cls, overview: Overview) -> QueueOverviewOut:
        return cls(
            summary=QueueSummaryOut.of(overview.summary),
            config=dict(overview.config),
            workers=[QueueWorkerOut.of(worker) for worker in overview.workers],
            slots_total=overview.slots_total,
            paused_approvals=overview.paused_approvals,
        )


class QueueJobOut(BaseModel):
    id: str
    run_id: str
    component_type: str | None
    component_id: str | None
    session_id: str | None
    user_id: str | None
    status: str
    detail: str | None
    attempt: int
    max_attempts: int
    idempotency_key: str | None
    locked_by: str | None
    deployment: str | None
    error: str | None
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def of(cls, job: QueueJob, run_status: str | None = None) -> QueueJobOut:
        return cls(
            id=job.id,
            run_id=job.id,
            component_type=job.component_type,
            component_id=job.component_id,
            session_id=job.session_id,
            user_id=job.user_id,
            status=job.status,
            detail=job.detail(run_status),
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            idempotency_key=job.idempotency_key,
            locked_by=job.locked_by,
            deployment=job.deployment,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
            completed_at=job.completed_at,
        )


class QueueJobsPageOut(BaseModel):
    data: list[QueueJobOut]
    page: int
    limit: int
    total: int | None
    access: ModeName


class AttemptOut(BaseModel):
    text: str
    at: datetime | None
    detail: str | None
    state: Literal["done", "error", "now"]

    @classmethod
    def of(cls, entry: AttemptEntry) -> AttemptOut:
        return cls(text=entry.text, at=entry.at, detail=entry.detail, state=entry.state)


class CheckpointOut(BaseModel):
    number: int
    message_index: int
    title: str
    preview: str | None
    role: str | None
    reason: str | None
    created_at: datetime | None
    is_latest: bool

    @classmethod
    def of(cls, checkpoint: Checkpoint) -> CheckpointOut:
        return cls(
            number=checkpoint.number,
            message_index=checkpoint.message_index,
            title=checkpoint.title,
            preview=checkpoint.preview,
            role=checkpoint.role,
            reason=checkpoint.reason,
            created_at=checkpoint.created_at,
            is_latest=checkpoint.is_latest,
        )


class QueueJobDetailOut(QueueJobOut):
    run_status: str | None
    run_content: str | None
    attempts: list[AttemptOut]
    checkpoints: list[CheckpointOut]
    checkpoints_unavailable: str | None
    access: ModeName

    @classmethod
    def of_detail(cls, detail: JobDetail) -> QueueJobDetailOut:
        content = detail.run.get("content") if detail.run else None
        return cls(
            **QueueJobOut.of(detail.job, detail.run_status).model_dump(),
            run_status=detail.run_status,
            run_content=content if isinstance(content, str) else None,
            attempts=[AttemptOut.of(entry) for entry in detail.attempts],
            checkpoints=[CheckpointOut.of(checkpoint) for checkpoint in detail.checkpoints],
            checkpoints_unavailable=detail.checkpoints_unavailable,
            access=detail.mode,
        )


class ResumeIn(BaseModel):
    message_index: int = Field(ge=0, description="The checkpoint's message_index (AgentOS continue_from)")


class RequeueIn(BaseModel):
    force: bool = Field(default=False, description="Requeue even inside lock_grace_seconds of the failure")
