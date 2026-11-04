"""A Procrastinate worker that takes ``chaos.block`` jobs and never finishes them: the test kills it mid-job.

    python tests/chaos/stall_worker.py <postgres-url>

Heartbeats every second, so the job counts as stalled a couple of seconds after the process dies.
"""

import asyncio
import sys

import procrastinate

from agnostic_kernel.jobs import create_jobs_app
from agnostic_kernel.testing import make_settings
from agnostic_server.loops import new_event_loop

BLOCK_TASK = "chaos.block"
HEARTBEAT_SECONDS = 1.0


def jobs_app(database_url: str) -> procrastinate.App:
    return create_jobs_app(make_settings(database_url).database)


async def main(database_url: str) -> None:
    app = jobs_app(database_url)

    @app.task(name=BLOCK_TASK, pass_context=True)
    async def block(context: procrastinate.JobContext) -> None:  # pyright: ignore[reportUnusedFunction]
        _ = sys.stdout.write(f"running {context.job.id}\n")
        _ = sys.stdout.flush()
        await asyncio.Event().wait()

    async with app.open_async():
        _ = sys.stdout.write("ready\n")
        _ = sys.stdout.flush()
        await app.run_worker_async(
            concurrency=1, install_signal_handlers=False, update_heartbeat_interval=HEARTBEAT_SECONDS
        )


if __name__ == "__main__":
    new_event_loop().run_until_complete(main(sys.argv[1]))
