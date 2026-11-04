"""Contract: the inline-approval payloads against a live runtime.

support-triage (mock model) calls ``refund_customer`` for "refund 49 …", which pauses the run for approval. The
control plane resolves the approval, then continues the run with the payload ``agnostic_approvals`` builds; this
checks that AgentOS accepts it and that the edited amount is what the tool ran with. Runs as user ``contract``;
needs a runtime without JWT auth (``auth_mode=none``, as CI starts it) and approvals enabled (``db=``).
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from agnostic_approvals.domain.decisions import Approval, continue_form

pytestmark = pytest.mark.contract

RUNTIME_URL = os.environ.get("AGNOSTIC_CONTRACT_RUNTIME_URL")


@pytest.fixture
async def runtime() -> AsyncIterator[httpx.AsyncClient]:
    if not RUNTIME_URL:
        pytest.skip("AGNOSTIC_CONTRACT_RUNTIME_URL is not set")
    async with httpx.AsyncClient(base_url=RUNTIME_URL, timeout=60) as client:
        yield client


def events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line.removeprefix("data: ")) for line in text.splitlines() if line.startswith("data: ")]


async def test_refund_pauses_and_continues_with_edited_args(runtime: httpx.AsyncClient) -> None:
    session_id = str(uuid.uuid4())
    started = await runtime.post(
        "/agents/support-triage/runs",
        # As the web app submits: in the background (indexed, resumable events), streamed.
        data={
            "message": "Please refund 49 to cus_8812",
            "stream": "true",
            "background": "true",
            "session_id": session_id,
            "user_id": "contract",
        },
    )
    assert started.status_code == 200, started.text
    stream = events(started.text)
    names = [event["event"] for event in stream]
    assert names[0] == "RunStarted"
    assert names[-1] == "RunPaused", names
    assert all(isinstance(event.get("event_index"), int) for event in stream)
    run_id = stream[0]["run_id"]

    listed = await runtime.get("/approvals", params={"run_id": run_id, "status": "pending"})
    assert listed.status_code == 200, listed.text
    [pending] = listed.json()["data"]
    approval = Approval.parse(pending)
    assert approval.tool_name == "refund_customer"
    assert approval.tool_args["amount"] == 49

    edited = {**approval.tool_args, "amount": 45}
    resolved = await runtime.post(
        f"/approvals/{approval.id}/resolve",
        json={"status": "approved", "resolved_by": "contract", "resolution_data": {"edited_args": edited}},
    )
    assert resolved.status_code == 200, resolved.text

    family, component_id, form = continue_form(approval, "approve", edited)
    # Exactly what the decide endpoint sends: the durable queue owns the continuation (background, no stream).
    continued = await runtime.post(f"/{family}/{component_id}/runs/{run_id}/continue", data=form)
    assert continued.status_code in {200, 202}, continued.text

    # The continuation streams to whoever watches the run: /resume replays it from the start.
    replay: list[dict[str, Any]] = []
    for _ in range(30):
        resumed = await runtime.post(f"/{family}/{component_id}/runs/{run_id}/resume", data={"session_id": session_id})
        assert resumed.status_code == 200, resumed.text
        replay = events(resumed.text)
        if any(event.get("event") == "RunCompleted" for event in replay):
            break
        await asyncio.sleep(0.5)
    assert any(event.get("event") == "RunCompleted" for event in replay), [event.get("event") for event in replay]
    results = [
        event["tool"].get("result")
        for event in replay
        if event.get("event") == "ToolCallCompleted" and event.get("tool", {}).get("tool_name") == "refund_customer"
    ]
    assert results == ["Refunded 45.00 to cus_8812 (requested in chat)."]


async def test_resume_replays_a_finished_run(runtime: httpx.AsyncClient) -> None:
    session_id = str(uuid.uuid4())
    started = await runtime.post(
        "/agents/summarizer/runs",
        data={"message": "summarise this", "stream": "true", "background": "true", "session_id": session_id},
    )
    stream = events(started.text)
    run_id = stream[0]["run_id"]
    resumed = await runtime.post(
        f"/agents/summarizer/runs/{run_id}/resume", data={"last_event_index": "0", "session_id": session_id}
    )
    assert resumed.status_code == 200, resumed.text
    replay = events(resumed.text)
    indexes = [event["event_index"] for event in replay if "event_index" in event]
    assert indexes
    assert min(indexes) >= 1
    assert any(event.get("event") == "RunCompleted" for event in replay)
