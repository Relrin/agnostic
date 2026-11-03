"""The batch job: run every pending case as the person who started the batch, a few at a time.

AgentOS ``/eval-runs`` (and the bridge's version-pinned route) evaluate one input synchronously, so the job fans out
one request per case under a semaphore. Requests go through the gateway as the starter, so a revoked permission
stops the remaining cases instead of being bypassed. Database writes are serialised (one session per job); a
cancelled batch stops between cases; a failing case is recorded and doesn't fail the batch.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, cast

from agnostic_evals.application.access import EvalAccess, detail
from agnostic_evals.application.ports import BatchRepository
from agnostic_evals.domain.compare import compare_cases, counts
from agnostic_evals.domain.model import Batch, Case, Outcome
from agnostic_evals.domain.runs import run_input, run_path
from agnostic_evals.domain.scoring import outcome, summarize
from agnostic_gateway.facade import GatewayResponse
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.errors import AppError
from agnostic_kernel.events import EventBus, RealtimeEvent, instance_channel
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

PROGRESS_EVENT = "evals.batch.progress"
REGRESSION_EVENT = "evals.regression"
"""Domain event: a completed batch scored worse than the previous one on the same component and dataset."""


class CaseCaller(Protocol):
    """Sends one case's eval request.

    The job gives each call its own request scope (database session), so cases can run concurrently; without one,
    cases run one at a time on the job's own scope.
    """

    async def __call__(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        body: Any,  # noqa: ANN401
    ) -> GatewayResponse: ...


class RunBatch:
    def __init__(
        self,
        access: EvalAccess,
        batches: BatchRepository,
        bus: EventBus,
        concurrency: int,
        events: DomainEvents | None = None,
    ) -> None:
        self._access = access
        self._batches = batches
        self._bus = bus
        self._concurrency = concurrency
        self._events = events
        self._db = asyncio.Lock()

    async def __call__(self, batch_id: str, caller: CaseCaller | None = None) -> Batch | None:
        batch = await self._batches.get(batch_id)
        if batch is None or batch.finished:
            return batch
        instance = await self._access.by_id(batch.instance_id)
        if instance is None:
            await self._finish(batch, status="failed", error="The instance was deleted.")
            return await self._batches.get(batch_id)
        await self._batches.update(batch.id, status="running")
        await self._batches.commit()
        await self._announce(batch, "running", batch.progress)

        principal = Principal(kind="user", id=batch.started_by, display_name=batch.started_by_name, via="job")
        pending = await self._batches.pending(batch.id)
        done = batch.case_count - len(pending)
        semaphore = asyncio.Semaphore(self._concurrency if caller is not None else 1)
        send = caller or self._own_scope
        cancelled = False

        async def run(item_id: str, case: Case) -> None:
            nonlocal done, cancelled
            async with semaphore:
                async with self._db:
                    if cancelled or await self._batches.status(batch.id) == "cancelled":
                        cancelled = True
                        return
                result = await self._run_case(send, principal, instance, batch, case)
                async with self._db:
                    await self._batches.finish_item(item_id, **result)
                    done += 1
                    progress = done / batch.case_count if batch.case_count else 1.0
                    await self._batches.update(batch.id, progress=progress)
                    await self._batches.commit()
                await self._announce(batch, "running", progress)

        try:
            await asyncio.gather(*(run(item_id, case) for item_id, case in pending))
        except Exception as exc:
            log.exception("evals.batch_failed", batch=batch.id)
            await self._finish(batch, status="failed", error=str(exc)[:500])
            return await self._batches.get(batch.id)
        await self._finish(batch, status="cancelled" if cancelled else None)
        return await self._batches.get(batch.id)

    async def _own_scope(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        body: Any,  # noqa: ANN401
    ) -> GatewayResponse:
        return await self._access.call(principal, instance, method, path, body=body)

    @staticmethod
    async def _run_case(
        send: CaseCaller, principal: Principal, instance: Instance, batch: Batch, case: Case
    ) -> dict[str, Any]:
        try:
            response = await send(principal, instance, "POST", run_path(batch), run_input(batch, case))
        except AppError as exc:
            return {"status": "error", "error": exc.detail or exc.title}
        if not response.ok or not isinstance(response.body, dict):
            return {"status": "error", "error": detail(response)}
        body = cast("dict[str, Any]", response.body)
        threshold = float(batch.params.get("threshold") or 7)
        return {
            "status": "done",
            "outcome": outcome(batch.eval_type, body, threshold),
            "eval_run_id": str(body.get("id") or "") or None,
            "trace_id": cast("str | None", body.get("trace_id")),
        }

    async def _finish(self, batch: Batch, *, status: str | None = None, error: str | None = None) -> None:
        items = await self._batches.items(batch.id)
        finished = [item for item in items if item.status in {"done", "error"}]
        outcomes: list[Outcome | None] = [item.outcome for item in finished]
        threshold = float(batch.params.get("threshold") or 7)
        summary = summarize(batch.case_count, outcomes, threshold)
        final = status or ("failed" if finished and summary.completed == 0 else "completed")
        await self._batches.update(
            batch.id,
            status=final,  # pyright: ignore[reportArgumentType]
            progress=len(finished) / batch.case_count if batch.case_count else 1.0,
            summary=summary.to_dict(),
            finished_at=utcnow(),
            error=error or ("Every case failed; see the case errors." if final == "failed" and not error else None),
        )
        await self._batches.commit()
        await self._announce(batch, final, 1.0 if final == "completed" else None)
        if final == "completed":
            await self._regressions(batch, threshold)

    async def _regressions(self, batch: Batch, threshold: float) -> None:
        """Announce regressions against the previous completed batch of the same component, dataset and type."""
        if self._events is None or not self._events.subscribed(REGRESSION_EVENT):
            return
        previous = next(
            (
                other
                for other in await self._batches.latest(
                    batch.instance_id, batch.target.component_id, batch.dataset_id, batch.eval_type
                )
                if other.id != batch.id and other.status == "completed" and other.started_at <= batch.started_at
            ),
            None,
        )
        if previous is None:
            return
        found = counts(
            compare_cases(await self._batches.items(previous.id), await self._batches.items(batch.id), threshold),
            threshold,
        )
        if found.regressions == 0:
            return
        await self._events.publish(
            REGRESSION_EVENT,
            {
                "instance_id": batch.instance_id,
                "batch_id": batch.id,
                "previous_batch_id": previous.id,
                "batch_name": batch.name,
                "component_kind": batch.target.kind,
                "component_id": batch.target.component_id,
                "dataset_name": batch.dataset_name,
                "regressions": found.regressions,
                "fixes": found.fixes,
                "started_by": batch.started_by,
            },
        )

    async def _announce(self, batch: Batch, status: str, progress: float | None) -> None:
        await self._bus.publish(
            instance_channel(batch.instance_id),
            RealtimeEvent(
                type=PROGRESS_EVENT,
                instance_id=batch.instance_id,
                data={"batch_id": batch.id, "status": status, "progress": progress},
            ),
        )
