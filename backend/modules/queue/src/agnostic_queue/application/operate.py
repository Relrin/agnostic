"""The durable queue over AgentOS ``/queue/*``: health, workers, jobs, and recovering failed runs.

AgentOS lets only admins (``agent_os:admin``) at ``/queue/*``. People holding the control-plane scope
``queue:operate`` (Operators and Instance admins by default) get there through delegated elevation: the control plane
checks the scope, then sends one single-use admin token, audited as ``gateway.elevated``. Instance admins on an
instance with elevation turned off go as themselves. Everyone else with access to the instance sees counts only.

Recovery actions are audited: ``queue.resume`` (continue from a checkpoint, so earlier tool calls aren't repeated),
``queue.requeue`` (one more attempt with the same run id) and ``queue.cancel``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, cast

import orjson

from agnostic_agentos_client import AgentOSError
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_gateway.facade import GatewayFacade, GatewayResponse
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ConflictError, NotFoundError, ValidationFailedError
from agnostic_queue.domain.jobs import (
    STATUSES,
    AttemptEntry,
    Checkpoint,
    QueueJob,
    Worker,
    attempts_timeline,
    merge_workers,
)

OPERATE = "queue:operate"
ADMIN = "agent_os:admin"
SUMMARY = "config:read"
WORKERS_KEY = "queue:workers:{instance}"
BRIDGE_PROBES = 3
NOT_FOUND = 404
CONFLICT = 409
SERVICE_UNAVAILABLE = 503

type Mode = Literal["elevated", "admin"]


class QueueRequiresAdminError(AppError):
    status = 403
    code = "queue_requires_admin"
    title = "The queue needs queue:operate or Instance admin"


class QueueUnavailableError(AppError):
    status = 503
    code = "queue_unavailable"
    title = "The instance has no durable queue on this replica"


class QueueCallError(AppError):
    status = 502
    code = "instance_error"
    title = "The instance answered with an error"


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300  # noqa: PLR2004


def _detail(reply: Reply) -> str:
    body: object = reply.body
    if isinstance(body, dict):
        value = cast("dict[str, Any]", body).get("detail")
        return str(value) if value is not None else f"HTTP {reply.status}"
    return str(body)[:300] if body else f"HTTP {reply.status}"


class Operator:
    """Sends queue calls the way this person may: elevated, as an admin, or not at all."""

    def __init__(self, gateway: GatewayFacade, principal: Principal, instance: Instance, mode: Mode) -> None:
        self._gateway = gateway
        self.principal = principal
        self.instance = instance
        self.mode: Mode = mode

    async def send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
        action: str = "operate the queue",
    ) -> Reply:
        if self.mode == "elevated":
            response = await self._gateway.elevated(
                self.principal,
                self.instance,
                method,
                path,
                justification=OPERATE,
                action_label=action,
                params=params,
                form=form,
            )
            return Reply(response.status, response.body)
        plain: GatewayResponse = await self._gateway.call(
            self.principal, self.instance, method, path, params=params, form=form
        )
        return Reply(plain.status, plain.body)

    async def json(self, path: str, *, params: Mapping[str, str] | None = None) -> Any:  # noqa: ANN401
        reply = await self.send("GET", path, params=params, action="read the queue")
        return checked(self.instance, reply)


def checked(instance: Instance, reply: Reply) -> Any:  # noqa: ANN401
    if reply.status == NOT_FOUND:
        raise NotFoundError(f"{instance.display_name}: {_detail(reply)}")
    if reply.status == SERVICE_UNAVAILABLE:
        raise QueueUnavailableError(f"{instance.display_name}: {_detail(reply)}")
    if reply.status == CONFLICT:
        raise ConflictError(f"{instance.display_name}: {_detail(reply)}")
    if not reply.ok:
        raise QueueCallError(f"{instance.display_name}: {_detail(reply)}", extra={"upstream_status": reply.status})
    return reply.body


def page_items(payload: object) -> tuple[list[dict[str, Any]], int | None]:
    if isinstance(payload, dict):
        body = cast("dict[str, Any]", payload)
        data = cast("list[Any]", body.get("data") or [])
        total = cast("dict[str, Any]", body.get("meta") or {}).get("total_count")
        rows = [cast("dict[str, Any]", item) for item in data if isinstance(item, dict)]
        return rows, int(total) if isinstance(total, int | float) else None
    if isinstance(payload, list):
        items = cast("list[Any]", payload)
        return [cast("dict[str, Any]", item) for item in items if isinstance(item, dict)], len(items)
    return [], None


@dataclass(frozen=True, slots=True)
class Summary:
    instance: Instance
    counts: dict[str, int]
    oldest_queued_age_seconds: float | None
    mode: Mode | None
    """How this person reaches the queue (``None``: counts only)."""
    explanation: str | None


@dataclass(frozen=True, slots=True)
class Overview:
    summary: Summary
    config: Mapping[str, Any]
    """``QueueConfig`` from the bridge (empty without it)."""
    workers: list[Worker]
    slots_total: int | None
    paused_approvals: int | None


@dataclass(frozen=True, slots=True)
class JobDetail:
    job: QueueJob
    run: Mapping[str, Any] | None
    run_status: str | None
    attempts: list[AttemptEntry]
    checkpoints: list[Checkpoint]
    checkpoints_unavailable: str | None
    mode: Mode


class Queue:
    def __init__(
        self,
        gateway: GatewayFacade,
        instances: InstancesFacade,
        authorizer: Authorizer,
        store: EphemeralStore,
        audit: AuditLog,
    ) -> None:
        self._gateway = gateway
        self._instances = instances
        self._authorizer = authorizer
        self._store = store
        self._audit = audit

    async def _allowed(self, principal: Principal, scope: str, instance: Instance) -> bool:
        return (await self._authorizer.check(principal, scope, instance_id=instance.id)).allowed

    async def _mode(self, principal: Principal, instance: Instance) -> tuple[Mode | None, str | None]:
        if instance.elevation_enabled and await self._allowed(principal, OPERATE, instance):
            return "elevated", None
        if await self._allowed(principal, ADMIN, instance):
            return "admin", None
        if await self._allowed(principal, OPERATE, instance):
            return None, (
                f"Delegated elevation is off on {instance.display_name}, so queue:operate doesn't reach the queue "
                "there: only Instance admins can open it."
            )
        return None, (
            "The queue is admin-only in AgentOS. Operators (queue:operate) reach it through the control plane; "
            "ask an Owner for Operator or Instance admin on this instance."
        )

    async def operator(self, principal: Principal, ref: str) -> Operator:
        instance = await self._gateway.instance(ref)
        mode, reason = await self._mode(principal, instance)
        if mode is None:
            raise QueueRequiresAdminError(reason, extra={"required_scopes": [OPERATE, ADMIN]})
        return Operator(self._gateway, principal, instance, mode)

    async def summary(self, principal: Principal, ref: str) -> Summary:
        instance = await self._gateway.instance(ref)
        _ = await self._authorizer.require(principal, SUMMARY, instance_id=instance.id)
        mode, reason = await self._mode(principal, instance)
        try:
            stats = await self._instances.system_call(instance, "GET", "/queue/stats")
        except AgentOSError as exc:
            if exc.status == SERVICE_UNAVAILABLE:
                raise QueueUnavailableError(f"{instance.display_name} has no durable queue.") from exc
            raise QueueCallError(f"{instance.display_name}: {exc}") from exc
        body = cast("dict[str, Any]", stats) if isinstance(stats, dict) else {}
        counts = {status: int(cast("dict[str, Any]", body.get("counts") or {}).get(status) or 0) for status in STATUSES}
        oldest = body.get("oldest_queued_age_seconds")
        return Summary(
            instance=instance,
            counts=counts,
            oldest_queued_age_seconds=float(oldest) if isinstance(oldest, int | float) else None,
            mode=mode,
            explanation=reason,
        )

    async def _bridge(self, instance: Instance) -> list[dict[str, Any]]:
        """Fresh worker snapshots from the bridge, merged with the ones other replicas answered before."""
        key = WORKERS_KEY.format(instance=instance.id)
        raw = await self._store.get(key)
        known = cast("dict[str, dict[str, Any]]", orjson.loads(raw)) if raw else {}
        for _ in range(BRIDGE_PROBES):
            try:
                body = await self._instances.system_call(instance, "GET", "/agnostic/v1/workers")
            except AgentOSError:
                break
            if not isinstance(body, dict):
                break
            snapshot = cast("dict[str, Any]", body)
            replica = str(snapshot.get("replica_id") or "replica")
            fresh = replica not in known or known[replica].get("heartbeat_at") != snapshot.get("heartbeat_at")
            known[replica] = snapshot
            if not fresh:
                break
        if known:
            await self._store.set(key, orjson.dumps(known), ttl=600)
        return list(known.values())

    async def overview(self, principal: Principal, ref: str) -> Overview:
        operator = await self.operator(principal, ref)
        summary = await self.summary(principal, ref)
        snapshots = await self._bridge(operator.instance)
        config = cast("dict[str, Any]", (snapshots[0].get("queue") if snapshots else None) or {})
        running_body = await operator.json("/queue/jobs", params={"status": "running", "limit": "200"})
        running = [QueueJob.parse(item) for item in page_items(running_body)[0]]
        grace = config.get("lock_grace_seconds")
        stale = timedelta(seconds=max(float(grace) if isinstance(grace, int | float) else 60.0, 30.0) * 2)
        workers = merge_workers(snapshots, running, now=utcnow(), stale_after=stale)
        totals = [worker.slots_total for worker in workers if worker.slots_total]
        try:
            approvals = await self._instances.system_call(operator.instance, "GET", "/approvals/count")
            paused = int(cast("dict[str, Any]", approvals).get("count") or 0) if isinstance(approvals, dict) else None
        except AgentOSError:
            paused = None
        return Overview(
            summary=summary,
            config=config,
            workers=workers,
            slots_total=sum(totals) if totals else None,
            paused_approvals=paused,
        )

    async def jobs(
        self, principal: Principal, ref: str, *, status: str | None, page: int, limit: int
    ) -> tuple[list[QueueJob], int | None, Mode]:
        operator = await self.operator(principal, ref)
        params = {"page": str(page), "limit": str(limit), "sort_by": "created_at", "sort_order": "desc"}
        if status:
            if status not in STATUSES:
                raise ValidationFailedError(f"status must be one of {', '.join(STATUSES)}.")
            params["status"] = status
        items, total = page_items(await operator.json("/queue/jobs", params=params))
        return [QueueJob.parse(item) for item in items], total, operator.mode

    async def _job(self, operator: Operator, job_id: str) -> QueueJob:
        body = await operator.json(f"/queue/jobs/{job_id}")
        if not isinstance(body, dict):
            raise NotFoundError(f"There is no queued job {job_id}.")
        return QueueJob.parse(cast("dict[str, Any]", body))

    async def job(self, principal: Principal, ref: str, job_id: str) -> JobDetail:
        operator = await self.operator(principal, ref)
        job = await self._job(operator, job_id)
        run: dict[str, Any] | None = None
        if job.session_id:
            reply = await operator.send(
                "GET",
                f"/sessions/{job.session_id}/runs/{job.id}",
                params={"type": (job.component_type or "agent").rstrip("s")},
                action="read the failed run",
            )
            run = cast("dict[str, Any]", reply.body) if reply.ok and isinstance(reply.body, dict) else None
        checkpoints: list[Checkpoint] = []
        unavailable: str | None = None
        if job.family in {"agents", "teams"} and job.component_id and job.session_id:
            reply = await operator.send(
                "GET",
                f"/{job.family}/{job.component_id}/runs/{job.id}/checkpoints",
                params={"session_id": job.session_id},
                action="read checkpoints",
            )
            if reply.ok and isinstance(reply.body, dict):
                items = cast("list[Any]", cast("dict[str, Any]", reply.body).get("checkpoints") or [])
                checkpoints = [
                    Checkpoint.parse(cast("dict[str, Any]", item), index + 1)
                    for index, item in enumerate(items)
                    if isinstance(item, dict)
                ]
            else:
                unavailable = _detail(reply)
        elif job.family == "workflows":
            unavailable = "Workflows don't keep message checkpoints: requeue the job or continue its paused step."
        config = await self._config(operator.instance)
        delay = config.get("retry_delay_seconds")
        return JobDetail(
            job=job,
            run=run,
            run_status=str(run.get("status")) if run and run.get("status") else None,
            attempts=attempts_timeline(
                job, retry_delay_seconds=float(delay) if isinstance(delay, int | float) else None
            ),
            checkpoints=checkpoints,
            checkpoints_unavailable=unavailable,
            mode=operator.mode,
        )

    async def _config(self, instance: Instance) -> dict[str, Any]:
        raw = await self._store.get(WORKERS_KEY.format(instance=instance.id))
        known = cast("dict[str, dict[str, Any]]", orjson.loads(raw)) if raw else {}
        configs = [cast("dict[str, Any]", snapshot.get("queue") or {}) for snapshot in known.values()]
        return configs[0] if configs else {}

    async def resume(self, principal: Principal, ref: str, job_id: str, message_index: int) -> JobDetail:
        operator = await self.operator(principal, ref)
        job = await self._job(operator, job_id)
        if job.family not in {"agents", "teams"} or not job.component_id:
            raise ValidationFailedError("Only agent and team runs resume from a checkpoint.")
        form = {"continue_from": str(message_index), "background": "true", "stream": "false"}
        if job.session_id:
            form["session_id"] = job.session_id
        if job.user_id:
            form["user_id"] = job.user_id
        reply = await operator.send(
            "POST", f"/{job.family}/{job.component_id}/runs/{job.id}/continue", form=form, action="resume failed runs"
        )
        _ = checked(operator.instance, reply)
        await self._record(operator, "queue.resume", job, {"message_index": message_index})
        return await self.job(principal, ref, job_id)

    async def requeue(self, principal: Principal, ref: str, job_id: str, *, force: bool) -> JobDetail:
        operator = await self.operator(principal, ref)
        job = await self._job(operator, job_id)
        params = {"force": "true"} if force else None
        reply = await operator.send("POST", f"/queue/jobs/{job_id}/requeue", params=params, action="requeue jobs")
        _ = checked(operator.instance, reply)
        await self._record(operator, "queue.requeue", job, {"force": force})
        return await self.job(principal, ref, job_id)

    async def cancel(self, principal: Principal, ref: str, job_id: str) -> JobDetail:
        operator = await self.operator(principal, ref)
        job = await self._job(operator, job_id)
        if job.status in {"failed", "completed", "cancelled"}:
            raise ConflictError(f"The job is {job.status}: there is nothing to cancel.")
        if not job.family or not job.component_id:
            raise ValidationFailedError("The job names no agent, team or workflow.")
        params = {"session_id": job.session_id} if job.session_id else None
        reply = await operator.send(
            "POST", f"/{job.family}/{job.component_id}/runs/{job.id}/cancel", params=params, action="cancel runs"
        )
        _ = checked(operator.instance, reply)
        await self._record(operator, "queue.cancel", job, {})
        return await self.job(principal, ref, job_id)

    async def _record(self, operator: Operator, action: str, job: QueueJob, details: Mapping[str, Any]) -> None:
        component = f"{job.component_type or 'run'} {job.component_id or ''}".strip()
        _ = await self._audit.record_now(
            AuditEntry(
                action=action,
                actor=actor_of(operator.principal),
                resource_kind="queue_job",
                resource_id=job.id,
                resource_display=job.id,
                instance_id=operator.instance.id,
                decision="allowed",
                scope_checked=OPERATE if operator.mode == "elevated" else ADMIN,
                response_status=200,
                fields={"run": job.id, "component": component, "instance": operator.instance.display_name},
                links={"session_id": job.session_id, "mode": operator.mode, **details},
                via="web",
            )
        )
