"""Artefacts against a fake AgentOS: bytes served with an isolating policy, share links that expire, are revoked,
need a sign-in unless shared with anyone, and stop when the bytes change; every step audited."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.api.test_instances_gateway import connect
from tests.support.fake_agentos import FakeAgentOS
from tests.support.stack import Stack, running_stack

BASE = "/api/v1/instances/prod-agentos/artifacts"
HTML = b"<!doctype html><script>document.title='x'</script><p>Report</p>"
MARKDOWN = b"# Report\n\nAll good.\n"


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    monkeypatch.setenv("AGNOSTIC_ARTIFACTS__PUBLIC_LINKS", "true")
    async with running_stack(sqlite_database) as running:
        yield running


async def setup(stack: Stack) -> tuple[httpx.AsyncClient, FakeAgentOS]:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    fake.media["sess_1", "sess_1/art_report.md"] = (MARKDOWN, "text/markdown")
    fake.media["sess_1", "sess_1/art_page.html"] = (HTML, "text/html")
    return owner, fake


async def actions(owner: httpx.AsyncClient, action: str) -> list[dict[str, Any]]:
    return (await owner.get("/api/v1/audit/events", params={"action": action})).json()["data"]


async def test_content_is_served_with_its_real_type_inside_a_sandbox(stack: Stack) -> None:
    owner, fake = await setup(stack)

    page = await owner.get(f"{BASE}/sess_1/content/sess_1/art_page.html", params={"filename": "page.html"})
    assert page.status_code == 200, page.text
    assert page.content == HTML
    assert page.headers["content-type"].startswith("text/html")
    policy = page.headers["content-security-policy"]
    assert policy.startswith("sandbox allow-scripts")
    assert "allow-same-origin" not in policy
    assert "connect-src 'none'" in policy
    assert page.headers["x-frame-options"] == "SAMEORIGIN"
    assert page.headers["x-content-type-options"] == "nosniff"

    download = await owner.get(
        f"{BASE}/sess_1/content/sess_1/art_page.html", params={"filename": "page.html", "disposition": "attachment"}
    )
    assert download.headers["content-disposition"].startswith('attachment; filename="page.html"')
    assert download.headers["content-security-policy"].startswith("sandbox;")

    report = await owner.get(f"{BASE}/sess_1/content/sess_1/art_report.md", params={"filename": "report.md"})
    assert report.headers["content-type"] == "text/markdown; charset=utf-8"

    missing = await owner.get(f"{BASE}/sess_1/content/sess_1/nope.md")
    assert missing.status_code == 404
    assert fake.calls[-1]["path"] == "/sessions/sess_1/media/sess_1/nope.md"


async def test_share_links_open_and_revoke(stack: Stack) -> None:
    owner, _ = await setup(stack)

    created = await owner.post(
        f"{BASE}/shares",
        json={"session_id": "sess_1", "storage_key": "sess_1/art_report.md", "filename": "report.md"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    token = body["token"]
    assert body["path"] == f"/s/{token}"
    assert body["share"]["audience"] == "org"
    assert body["share"]["state"] == "active"

    meta = (await owner.get(f"/api/v1/shares/{token}")).json()
    assert meta["filename"] == "report.md"
    assert meta["content_type"] == "text/markdown"
    opened = await owner.get(f"/api/v1/shares/{token}/content")
    assert opened.status_code == 200
    assert opened.content == MARKDOWN

    anonymous = stack.client()
    assert (await anonymous.get(f"/api/v1/shares/{token}")).status_code == 401

    listed = (await owner.get(f"{BASE}/shares", params={"session_id": "sess_1"})).json()
    assert listed["public_links"] is True
    assert [item["opened_count"] for item in listed["data"]] == [1]

    revoked = await owner.delete(f"{BASE}/shares/{body['share']['id']}")
    assert revoked.json()["state"] == "revoked"
    assert (await owner.get(f"/api/v1/shares/{token}/content")).status_code == 404

    assert len(await actions(owner, "artifact.share.created")) == 1
    assert len(await actions(owner, "artifact.share.opened")) == 1
    assert len(await actions(owner, "artifact.share.revoked")) == 1


async def test_public_links_and_changed_bytes(stack: Stack) -> None:
    owner, fake = await setup(stack)
    created = await owner.post(
        f"{BASE}/shares",
        json={
            "session_id": "sess_1",
            "storage_key": "sess_1/art_page.html",
            "filename": "page.html",
            "audience": "link",
            "ttl_seconds": 3600,
        },
    )
    token = created.json()["token"]

    anonymous = stack.client()
    page = await anonymous.get(f"/api/v1/shares/{token}/content")
    assert page.status_code == 200
    assert page.content == HTML
    assert "allow-same-origin" not in page.headers["content-security-policy"]

    fake.media["sess_1", "sess_1/art_page.html"] = (b"<p>changed</p>", "text/html")
    assert (await anonymous.get(f"/api/v1/shares/{token}/content")).status_code == 404
    assert (await anonymous.get("/api/v1/shares/ash_not-a-real-token-at-all-000000000")).status_code == 404


async def test_share_validation(stack: Stack) -> None:
    owner, _ = await setup(stack)
    too_short = await owner.post(
        f"{BASE}/shares",
        json={"session_id": "sess_1", "storage_key": "sess_1/art_report.md", "filename": "r.md", "ttl_seconds": 10},
    )
    assert too_short.status_code == 422
    unknown = await owner.post(
        f"{BASE}/shares", json={"session_id": "sess_1", "storage_key": "sess_1/none.md", "filename": "r.md"}
    )
    assert unknown.status_code == 404
