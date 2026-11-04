"""Upgrade dry runs, job-queue administration and secret rotation on PostgreSQL."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_kernel import migrations_runner
from agnostic_kernel.container import build_container
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import create_engine
from agnostic_kernel.job_admin import JobAdmin
from agnostic_kernel.jobs import JobQueue
from agnostic_kernel.modules import SealedColumn, load_modules
from agnostic_kernel.rewrap import scan
from agnostic_kernel.testing import make_settings

pytestmark = pytest.mark.integration


async def test_upgrade_check_rolls_back(fresh_postgres: str) -> None:
    engine = create_engine(make_settings(fresh_postgres).database)
    modules = list(load_modules().installed.values())
    try:
        applied = await migrations_runner.check_upgrade(engine, modules)
        assert {"k0001_kernel_base", "n0003_mtls_direct_mode"} <= {step.revision for step in applied}
        assert all(step.seconds >= 0 for step in applied)
        state = await migrations_runner.state(engine, modules)
        assert state.current == ()
        await migrations_runner.upgrade(engine, modules)
        assert await migrations_runner.check_upgrade(engine, modules) == []
    finally:
        await engine.dispose()


async def test_job_admin_queues_failed_retry_discard(fresh_postgres: str, redis_url: str) -> None:
    settings = make_settings(fresh_postgres, redis_url)
    engine = create_engine(settings.database)
    await migrations_runner.upgrade(engine, list(load_modules().installed.values()))
    await engine.dispose()
    container = build_container(settings, load_modules())
    try:
        admin = await container.get(JobAdmin)
        queue = await container.get(JobQueue)
        await queue.defer("kernel.domain_event", event="test.ping", payload={})
        engine = await container.get(AsyncEngine)
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL search_path TO procrastinate, public"))
            ids = (await connection.execute(text("SELECT id FROM procrastinate.procrastinate_jobs"))).scalars().all()
            await connection.execute(
                text("UPDATE procrastinate.procrastinate_jobs SET status = 'failed' WHERE id = :id"), {"id": ids[0]}
            )
            await connection.execute(
                text("INSERT INTO procrastinate.procrastinate_events (job_id, type) VALUES (:id, 'failed')"),
                {"id": ids[0]},
            )
        await queue.defer("kernel.domain_event", event="test.pong", payload={})

        stats = {item.queue: item for item in await admin.queues()}
        assert (stats["default"].waiting, stats["default"].failed) == (1, 1)
        assert stats["default"].oldest_wait_seconds is not None

        failed = await admin.failed()
        assert [job.id for job in failed] == [ids[0]]
        assert failed[0].argument_names == ("event", "payload")
        assert failed[0].failed_at is not None

        await admin.retry(ids[0])
        assert (await admin.queues())[0].waiting == 2
        assert await admin.discard(ids[0]) is False  # no longer failed
    finally:
        await container.close()


async def test_rewrap_jsonb_column(fresh_postgres: str) -> None:
    engine = create_engine(make_settings(fresh_postgres).database)
    await migrations_runner.upgrade(engine, list(load_modules().installed.values()))
    old, new = SecretBox(bytes(32)), SecretBox(bytes(range(32)), [bytes(32)])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO agnostic.identity_login_providers (id, kind, display_name, preset, config, "
                    "allowed_email_domains, jit_provisioning, enabled, created_by) VALUES ('okta', 'oidc', 'Okta', "
                    "'okta', CAST(:config AS jsonb), '[]', true, true, 'test')"
                ),
                {"config": f'{{"client_id": "abc", "client_secret": "{old.seal(b"s3cret")}"}}'},
            )
        column = SealedColumn("identity_login_providers", "config", json_keys=("client_secret",))
        report = (await scan(engine, new, [column], reseal=True))[0]
        assert report.resealed == 1
        async with engine.connect() as connection:
            config = (
                await connection.execute(text("SELECT config FROM agnostic.identity_login_providers"))
            ).scalar_one()
        assert config["client_id"] == "abc"
        assert new.sealed_with(config["client_secret"]) == new.key_id
    finally:
        await engine.dispose()
