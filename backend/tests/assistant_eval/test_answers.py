"""Question/answer pairs on the seeded data, asked to a real model: does it ground its answers in the tools?

Opt-in, because it needs a model and its answers aren't deterministic::

    AGNOSTIC_TEST_ASSISTANT_MODEL=ollama:qwen3:8b AGNOSTIC_TEST_ASSISTANT_ENDPOINT=http://localhost:11434 \\
        uv run pytest -m assistant_eval

Each case names facts the answer must contain (any spelling in a group counts) and pages it must cite. A model that
fails these hallucinates or ignores its tools; tune the model choice, not the expectations.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest

from tests.api.test_assistant import BASE, ask, enable, seed_daily_brief, settled
from tests.api.test_instances_gateway import connect
from tests.support.stack import Stack, running_stack

MODEL = os.environ.get("AGNOSTIC_TEST_ASSISTANT_MODEL")
ENDPOINT = os.environ.get("AGNOSTIC_TEST_ASSISTANT_ENDPOINT")
KEY = os.environ.get("AGNOSTIC_TEST_ASSISTANT_API_KEY")

pytestmark = [
    pytest.mark.assistant_eval,
    pytest.mark.skipif(MODEL is None, reason="set AGNOSTIC_TEST_ASSISTANT_MODEL to ask a real model"),
]


@dataclass(frozen=True)
class Case:
    question: str
    facts: tuple[tuple[str, ...], ...]
    """Each group: at least one of these appears in the answer (case-insensitive)."""
    cites: tuple[str, ...] = ()
    """Path fragments among the answer's sources."""


CASES = (
    Case(
        "Why did daily-brief fail last night?",
        facts=(("web_search",), ("timeout", "timed out", "time out")),
        cites=("/traces/tr_9c1e7d40", "scheduler?schedule=sch_1"),
    ),
    Case(
        "When does the daily-brief schedule run, and did its last runs succeed?",
        facts=(("03:00", "3:00", "3 am", "3am", "0 3 * * *"), ("fail",)),
        cites=("scheduler?schedule=sch_1",),
    ),
    Case(
        "Compare last night's daily-brief run with the last successful one.",
        facts=(("web_search",), ("write brief", "never reached", "didn't reach", "did not reach")),
        cites=("/traces/tr_9c1e7d40",),
    ),
)


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    monkeypatch.setenv("AGNOSTIC_APPROVALS__POLL_SECONDS", "0")
    monkeypatch.setenv("AGNOSTIC_OBSERVE__WARM_CRON", "")
    monkeypatch.setenv("AGNOSTIC_SEARCH__REINDEX_CRON", "")
    monkeypatch.setenv("AGNOSTIC_ASSISTANT__ANSWER_TIMEOUT_SECONDS", "600")
    async with running_stack(sqlite_database) as running:
        running.models.real = True
        yield running


async def prepared(stack: Stack) -> httpx.AsyncClient:
    owner = await stack.owner()
    fake = stack.runtime("prod.agentos.test")
    await connect(owner, fake)
    seed_daily_brief(fake)
    extra = {"endpoint": ENDPOINT} if ENDPOINT else {}
    if KEY:
        extra["api_key"] = KEY
    await enable(owner, models={"assistant": MODEL}, temperature=0, **extra)
    return owner


@pytest.mark.parametrize("case", CASES, ids=[case.question for case in CASES])
async def test_grounded_answer(stack: Stack, case: Case) -> None:
    owner = await prepared(stack)
    accepted = await ask(owner, case.question)
    assert accepted.status_code == 202, accepted.text
    answer = await settled(owner, accepted.json()["message_id"])
    assert answer["status"] == "completed", answer["error"]
    text = answer["content"].lower()
    for group in case.facts:
        assert any(fact.lower() in text for fact in group), f"expected one of {group} in: {answer['content']}"
    paths = " ".join(source["path"] for source in answer["sources"])
    for fragment in case.cites:
        assert fragment in paths, f"expected a source with {fragment}; got {paths or 'none'}"
    assert answer["tool_calls"], "answered without looking anything up"
    assert (await owner.get(f"{BASE}/messages/{answer['id']}/events")).status_code == 200
