"""Contract tests: the client and its models against a live ``agnostic-runtime`` (AgentOS 3.1.x).

Start a runtime (``just runtimes``) and point ``AGNOSTIC_CONTRACT_RUNTIME_URL`` at it; CI does the same in
``contract.yml``. Skipped when the variable is unset.
"""

import os
from collections.abc import AsyncIterator

import pytest

from agnostic_agentos_client import AGENTOS_VERSION, AgentOSClient

pytestmark = pytest.mark.contract

RUNTIME_URL = os.environ.get("AGNOSTIC_CONTRACT_RUNTIME_URL")

SAMPLE_AGENTS = {"support-triage", "billing-agent", "kb-researcher", "qa-reviewer", "web-researcher", "summarizer"}
SAMPLE_TEAMS = {"research-team", "escalation-team", "onboarding-team"}
SAMPLE_WORKFLOWS = {"ticket-router", "daily-brief", "refund-review"}


@pytest.fixture
async def runtime() -> AsyncIterator[AgentOSClient]:
    if not RUNTIME_URL:
        pytest.skip("AGNOSTIC_CONTRACT_RUNTIME_URL is not set")
    async with AgentOSClient(RUNTIME_URL, retries=5, backoff=0.5) as client:
        yield client


async def test_health(runtime: AgentOSClient) -> None:
    assert (await runtime.health()).status == "ok"


async def test_info_matches_pinned_version(runtime: AgentOSClient) -> None:
    info = await runtime.info()
    assert info.agno_version == AGENTOS_VERSION
    assert info.auth_mode in {"none", "security_key", "jwt"}
    assert (info.agent_count, info.team_count, info.workflow_count) == (6, 3, 3)


async def test_config_lists_sample_components(runtime: AgentOSClient) -> None:
    config = await runtime.config()
    assert {a.id for a in config.agents} == SAMPLE_AGENTS
    assert {t.id for t in config.teams} == SAMPLE_TEAMS
    assert {w.id for w in config.workflows} == SAMPLE_WORKFLOWS
    assert config.queue is not None  # durable queue enabled by the recipe
    assert config.traces is not None  # tracing=True
