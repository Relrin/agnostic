"""CPU-bound source work (parsing code, editing it, evaluating CEL) in worker processes with a timeout per job.

The jobs only read text: nothing in them imports or runs user code. Processes keep a runaway parse or expression
from stalling the event loop or the server; a job that outlives its timeout takes its pool down with it (the
workers are terminated and a fresh pool starts with the next job). ``inline`` runs jobs on a thread of this
process instead, for tests and single-process setups.
"""

from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Literal

from agnostic_kernel.logging import get_logger
from agnostic_studio.application.ports import SourceTimeoutError

log = get_logger(__name__)


class SourceWorkers:
    def __init__(self, mode: Literal["process", "inline"], size: int, timeout: float) -> None:
        self._mode = mode
        self._size = size
        self._timeout = timeout
        self._pool: ProcessPoolExecutor | None = None

    async def run[**P, T](self, job: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        if self._mode == "inline":
            try:
                return await asyncio.wait_for(asyncio.to_thread(job, *args, **kwargs), self._timeout)
            except TimeoutError as exc:
                raise SourceTimeoutError(self._timeout) from exc
        loop = asyncio.get_running_loop()
        pool = self._executor()
        try:
            future = loop.run_in_executor(pool, _call, job, args, kwargs)
            return await asyncio.wait_for(future, self._timeout)
        except TimeoutError as exc:
            log.warning("studio.source_job_timeout", job=getattr(job, "__name__", str(job)), seconds=self._timeout)
            self._recycle()
            raise SourceTimeoutError(self._timeout) from exc
        except BrokenProcessPool:
            self._recycle()
            raise

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def _executor(self) -> ProcessPoolExecutor:
        if self._pool is None:
            # Spawned, not forked: the server's event loop, sockets and threads stay out of the workers.
            self._pool = ProcessPoolExecutor(max_workers=self._size, mp_context=multiprocessing.get_context("spawn"))
        return self._pool

    def _recycle(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.terminate_workers()
            pool.shutdown(wait=False, cancel_futures=True)


def _call[T](job: Callable[..., T], args: tuple[object, ...], kwargs: dict[str, object]) -> T:
    return job(*args, **kwargs)
