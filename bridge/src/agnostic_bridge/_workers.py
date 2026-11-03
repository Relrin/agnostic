"""``GET /agnostic/v1/workers``: the background-run worker and scheduler of the replica that answers.

AgentOS runs one durable queue worker per process (``app.state.queue_worker``) and says nothing about it over HTTP
beyond the cross-replica ``/queue`` operator routes. Each replica only knows its own worker, so the control plane
polls this route behind the load balancer and keys the answers by ``replica_id`` / ``worker_id``: ``worker_id`` is
the value a claimed job carries in ``locked_by``, and ``in_flight`` the runs this worker holds right now.

- **Access**: admin only, like AgentOS's ``/queue`` routes (:data:`~agnostic_bridge.SCOPE_MAPPINGS`).
- **No queue**: answers with ``queue.configured`` false and nulls rather than 503; a non-durable queue has no
  worker, so ``worker_id`` is None and ``in_flight`` empty.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os import AgentOS

WORKERS_PATH = "/workers"


class WorkersQueueConfig(BaseModel):
    """The QueueConfig this replica runs with; false/None throughout when AgentOS has none."""

    configured: bool = Field(description="A QueueConfig was passed to AgentOS")
    durable: bool = Field(description="Accepted background runs are committed rows that survive restarts")
    db: str | None = Field(description="Queue store class (e.g. PostgresDb); None for a non-durable queue")
    table: str | None = Field(description="Jobs table of the queue store, when it has one (e.g. agno_jobs)")
    max_queue_depth: int | None = Field(description="Accepted-but-unstarted jobs before submissions get 429")
    max_attempts: int | None
    retry_delay_seconds: float | None = Field(description="Base retry delay; attempt N waits up to base * 2**(N-1)")
    timeout_seconds: float | None = Field(description="Per-run execution timeout; None = no timeout")
    lock_grace_seconds: float | None = Field(description="Stale-lock grace before a dead worker's jobs are reclaimed")
    stop_timeout_seconds: float | None = Field(description="Drain window on shutdown, as the worker resolves it")
    poll_interval: float | None = Field(description="Idle poll interval of the worker, in seconds")
    retention_seconds: float | None = Field(description="Terminal jobs older than this are deleted")


class WorkersScheduler(BaseModel):
    enabled: bool = Field(description="This replica runs the schedule poller (scheduler on and a db configured)")
    poll_interval_seconds: float | None = Field(description="Schedule poll interval; None when the poller is off")


class WorkersResponse(BaseModel):
    replica_id: str = Field(description="This process; same value as /capabilities")
    worker_id: str | None = Field(description="This replica's queue worker; the value a claimed job has in locked_by")
    deployment_id: str | None = Field(description="Claim affinity: the worker claims unstamped jobs and these")
    heartbeat_at: int = Field(description="When this answer was made, epoch seconds")
    max_concurrency: int | None = Field(description="Effective background runs per replica; None = uncapped or none")
    in_flight: list[str] = Field(description="Job (run) ids this worker holds now")
    queue: WorkersQueueConfig
    scheduler: WorkersScheduler


def _unwrap(store: Any) -> Any:
    # agno wraps sync stores (the sync PostgresDb) in an awaitable adapter that keeps the store as ``_store``.
    inner = getattr(store, "__dict__", {}).get("_store")
    return inner if inner is not None else store


def _in_flight(worker: Any) -> list[str]:
    # QueueWorker keeps its claimed jobs privately; the snapshot helper is what its heartbeat thread reads.
    snapshot = getattr(worker, "_in_flight_snapshot", None)
    if callable(snapshot):
        try:
            return sorted(str(job_id) for job_id in snapshot())
        except Exception:
            return []
    held = getattr(worker, "_in_flight", None)
    return sorted(str(job_id) for job_id in list(held)) if isinstance(held, dict) else []


def _stop_timeout(config: Any, worker: Any) -> float | None:
    value = getattr(worker, "stop_timeout", None) if worker is not None else None
    if value is None:
        try:
            from agno.os.job_queue import resolve_stop_timeout
        except ImportError:  # older agno: the config field, unresolved
            value = getattr(config, "stop_timeout_seconds", None)
        else:
            value = resolve_stop_timeout(config)
    return _number(value)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _max_concurrency(config: Any) -> int | None:
    cap = getattr(config, "max_concurrency", None)
    if cap is None:  # unset: the process setting (env var or agno's default), as the worker resolves it
        from agno.run.concurrency import get_background_max_concurrency

        cap = get_background_max_concurrency()
    return cap if isinstance(cap, int) and cap > 0 else None


def _queue_config(agent_os: AgentOS, config: Any, worker: Any) -> WorkersQueueConfig:
    if config is None:
        return WorkersQueueConfig(
            configured=False,
            durable=False,
            db=None,
            table=None,
            max_queue_depth=None,
            max_attempts=None,
            retry_delay_seconds=None,
            timeout_seconds=None,
            lock_grace_seconds=None,
            stop_timeout_seconds=None,
            poll_interval=None,
            retention_seconds=None,
        )
    durable = bool(getattr(config, "durable", False))
    store: Any = None
    if worker is not None:
        store = _unwrap(getattr(worker, "store", None))
    elif durable:  # before the worker starts, the store queue_lifespan would pick
        store = getattr(config, "db", None) or agent_os.db
    table = getattr(store, "job_table_name", None) if store is not None else None
    return WorkersQueueConfig(
        configured=True,
        durable=durable,
        db=type(store).__name__ if store is not None else None,
        table=table if isinstance(table, str) else None,
        max_queue_depth=_integer(getattr(config, "max_queue_depth", None)),
        max_attempts=_integer(getattr(config, "max_attempts", None)),
        retry_delay_seconds=_number(getattr(config, "retry_delay_seconds", None)),
        timeout_seconds=_number(getattr(config, "timeout_seconds", None)),
        lock_grace_seconds=_number(getattr(config, "lock_grace_seconds", None)),
        stop_timeout_seconds=_stop_timeout(config, worker),
        poll_interval=_number(getattr(config, "poll_interval", None)),
        retention_seconds=_number(getattr(config, "retention_seconds", None)),
    )


def _scheduler(agent_os: AgentOS) -> WorkersScheduler:
    # AgentOS keeps the constructor flags privately; the poller only starts with a db.
    enabled = bool(getattr(agent_os, "_scheduler_enabled", False)) and agent_os.db is not None
    interval = _number(getattr(agent_os, "_scheduler_poll_interval", None)) if enabled else None
    return WorkersScheduler(enabled=enabled, poll_interval_seconds=interval)


def build_workers(agent_os: AgentOS, worker: Any, replica_id: str) -> WorkersResponse:
    config = getattr(worker, "config", None) if worker is not None else None
    if config is None:
        config = agent_os.queue
    worker_id = getattr(worker, "worker_id", None) if worker is not None else None
    deployment_id = getattr(config, "deployment_id", None) if config is not None else None
    return WorkersResponse(
        replica_id=replica_id,
        worker_id=str(worker_id) if worker_id is not None else None,
        deployment_id=deployment_id if isinstance(deployment_id, str) else None,
        heartbeat_at=int(time.time()),
        max_concurrency=_max_concurrency(config) if config is not None else None,
        in_flight=_in_flight(worker) if worker is not None else [],
        queue=_queue_config(agent_os, config, worker),
        scheduler=_scheduler(agent_os),
    )


def add_worker_routes(router: APIRouter, agent_os: AgentOS, replica_id: str) -> None:
    @router.get(
        WORKERS_PATH,
        operation_id="agnostic_bridge_get_workers",
        summary="This replica's queue worker",
        description=(
            "The durable queue worker and schedule poller of the replica that answers: worker id, the runs it holds, "
            "and the queue config it runs with. Each replica answers for itself. Admin only, like /queue."
        ),
        response_model=WorkersResponse,
    )
    async def get_workers(request: Request) -> WorkersResponse:
        return build_workers(agent_os, getattr(request.app.state, "queue_worker", None), replica_id)
