"""Studio's source workers: jobs run in worker processes, a job past its timeout takes the pool down, the next job
gets a fresh one; inline mode runs on a thread with the same timeout."""

import time

import pytest

from agnostic_codegen import Lookup, RegistryConvention
from agnostic_studio.application.ports import SourceTimeoutError
from agnostic_studio.application.source_jobs import evaluate_job, parse_job
from agnostic_studio.infrastructure.isolation import SourceWorkers


def sleepy(seconds: float) -> float:
    time.sleep(seconds)
    return seconds


async def test_process_workers_run_jobs_and_recycle_after_a_timeout() -> None:
    workers = SourceWorkers("process", 1, timeout=60.0)
    try:
        code = 'from agno.agent import Agent\n\nagent = Agent(id="a", markdown=True)\n'
        parsed = await workers.run(parse_job, code, "agent", None, RegistryConvention(), Lookup())
        assert parsed.config == {"id": "a", "markdown": True}

        workers._timeout = 0.5
        with pytest.raises(SourceTimeoutError):
            await workers.run(sleepy, 30.0)
        assert workers._pool is None

        workers._timeout = 60.0
        assert await workers.run(sleepy, 0.0) == 0.0
    finally:
        workers.close()


async def test_inline_workers_time_out_too() -> None:
    workers = SourceWorkers("inline", 1, timeout=0.2)
    with pytest.raises(SourceTimeoutError, match=r"longer than 0.2 s"):
        await workers.run(sleepy, 1.0)
    evaluation = await SourceWorkers("inline", 1, timeout=5).run(
        evaluate_job, 'input.contains("x")', "condition", {"input": "xyz"}, None
    )
    assert (evaluation.result, evaluation.type, evaluation.error) == (True, "bool", None)
