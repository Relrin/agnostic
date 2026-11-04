"""Verifying archived months in place: an intact archive, then a damaged object, through the operator facade."""

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from agnostic_audit.facade import AuditAdmin
from tests.api.test_audit_governance import archive_policy, entry, events, ingest, maintain
from tests.support.fake_s3 import FakeS3
from tests.support.stack import Stack, running_stack


@pytest.fixture
async def stack(sqlite_database: str) -> AsyncIterator[Stack]:
    async with running_stack(sqlite_database) as running:
        yield running


async def test_verify_archive_in_place(stack: Stack) -> None:
    owner = await stack.owner()
    s3 = FakeS3()
    stack.serve("s3.test", s3.app)
    assert (await owner.put("/api/v1/audit/policy", json=archive_policy())).status_code == 200
    old = [entry(n, days_ago=460) for n in range(5)]
    assert await ingest(stack, old) == 5
    month = (await maintain(stack)).archived[0]

    async with stack.container() as request:
        admin = await request.get(AuditAdmin)
        assert [item.month for item in await admin.archives()] == [month]
        intact = await admin.verify_archive(month)
    assert intact.ok, intact.problems
    assert intact.event_count == 5

    data_key = f"agnostic/prod/audit-events-{month}.jsonl.zst"
    stored = s3.objects()[data_key]
    s3.objects()[data_key] = replace(stored, data=stored.data[:-4] + b"\0\0\0\0")
    async with stack.container() as request:
        damaged = await (await request.get(AuditAdmin)).verify_archive(month)
    assert not damaged.ok
    assert any("SHA-256" in problem for problem in damaged.problems)

    logged = await events(owner, action="audit.archive_verify")
    assert [event["summary"].rsplit(": ", 1)[1] for event in logged] == ["damaged", "intact"]
    restore = await owner.post(f"/api/v1/audit/archives/{month}/restore")
    assert restore.status_code == 202  # the restore job itself refuses the damaged object
