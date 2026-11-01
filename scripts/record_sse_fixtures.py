"""Record AgentOS SSE runs from a reference runtime as reducer fixtures for the frontend RunStream tests.

    cd backend && uv run python ../scripts/record_sse_fixtures.py [--url http://127.0.0.1:7790]

Needs a runtime without JWT auth (``auth_mode=none``), e.g. started like ``just runtimes`` without a key. Each scenario
is submitted as the web app does (``background=true``, ``stream=true``), and paused runs are continued the way the
control plane does after an approval decision, then replayed with ``/resume``. Writes one JSON array of events per
scenario to ``frontend/packages/core/src/run-stream/__fixtures__/recorded/``; ``recorded.test.ts`` folds every file
through the reducer.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "packages" / "core" / "src" / "run-stream" / "__fixtures__" / "recorded"


def parse(text: str) -> list[dict[str, Any]]:
    return [json.loads(line.removeprefix("data: ")) for line in text.splitlines() if line.startswith("data: ")]


def submit(client: httpx.Client, family: str, component: str, message: str) -> tuple[list[dict[str, Any]], str]:
    session = str(uuid.uuid4())
    data = {"message": message, "stream": "true", "background": "true", "session_id": session, "user_id": "fixtures"}
    if family == "workflows":
        response = client.post(f"/{family}/{component}/runs", data=data)
    else:
        response = client.post(f"/{family}/{component}/runs", files={key: (None, value) for key, value in data.items()})
    response.raise_for_status()
    return parse(response.text), session


def replay(client: httpx.Client, family: str, component: str, run_id: str, session: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for _ in range(40):
        response = client.post(f"/{family}/{component}/runs/{run_id}/resume", data={"session_id": session})
        response.raise_for_status()
        events = [event for event in parse(response.text) if "event_index" in event]
        if events and events[-1].get("event") in {"RunCompleted", "TeamRunCompleted", "WorkflowCompleted", "RunError"}:
            break
        time.sleep(0.5)
    return events


def continue_paused(client: httpx.Client, family: str, component: str, events: list[dict[str, Any]], session: str) -> None:
    run_id = events[0]["run_id"]
    approvals = client.get("/approvals", params={"run_id": run_id, "status": "pending"}).json().get("data", [])
    for approval in approvals:
        client.post(f"/approvals/{approval['id']}/resolve", json={"status": "approved", "resolved_by": "fixtures"})
    paused = events[-1]
    form: dict[str, str] = {"session_id": session, "background": "true", "stream": "false"}
    if family == "workflows":
        requirements = paused.get("step_requirements") or []
        for requirement in requirements:
            requirement["confirmed"] = True
            if requirement.get("requires_user_input"):
                requirement["user_input"] = {"amount": 45.0, "reason": "recorded fixture"}
        form["step_requirements"] = json.dumps(requirements)
    else:
        tools = paused.get("tools") or []
        for tool in tools:
            tool["confirmed"] = True
        form["tools"] = json.dumps(tools)
    client.post(f"/{family}/{component}/runs/{run_id}/continue", data=form).raise_for_status()


SCENARIOS: list[tuple[str, str, str, str, bool]] = [
    ("agent-completed", "agents", "support-triage", "Where is order ord_1001?", False),
    ("agent-paused-continued", "agents", "support-triage", "Please refund 49 to cus_8812", True),
    ("team-coordinate", "teams", "research-team", "search the knowledge base for refund policy", False),
    ("team-tasks", "teams", "onboarding-team", "search onboarding docs and summarise them", False),
    ("workflow-router", "workflows", "ticket-router", "I need a refund for my invoice", False),
    ("workflow-loop-hitl", "workflows", "refund-review", "refund 49 for cus_8812", True),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7790")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.url, timeout=120) as client:
        for name, family, component, message, resume in SCENARIOS:
            events, session = submit(client, family, component, message)
            if not events:
                print(f"{name}: no events", file=sys.stderr)
                continue
            if resume and events[-1].get("event", "").endswith("Paused"):
                continue_paused(client, family, component, events, session)
                events = replay(client, family, component, events[0]["run_id"], session)
            (OUT / f"{name}.json").write_text(json.dumps(events, indent=1) + "\n", encoding="utf-8")
            print(f"{name}: {len(events)} events, last {events[-1].get('event')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
