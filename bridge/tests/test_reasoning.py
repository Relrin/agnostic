"""Reasoning effort: the levels each provider takes, how a level reaches the model, and the route that lists them."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pytest
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.team import Team
from fastapi.testclient import TestClient

from agnostic_bridge import install
from agnostic_bridge.coding import CodingAgentSpec, CodingConfig, CodingRuntime, PiAgent
from agnostic_bridge.reasoning import (
    REASONING_HOOK,
    ReasoningOptions,
    apply_reasoning_effort,
    has_reasoning_hook,
    reasoning_options,
    register_reasoning_profile,
    with_reasoning,
)
from tests.coding_support import FakeProcess, FakeProvider, ScriptedModel, fixture_lines
from tests.conftest import make_os


@dataclass
class EchoModel(Model):
    """Answers "ok" and records the reasoning effort each call ran with. The provider SDKs aren't installed here, so
    the provider stand-ins below carry the same fields as Agno's own model classes."""

    id: str = "echo"
    name: str = "Echo"
    provider: str = "Echo"
    seen: list[Any] = field(default_factory=list)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.seen.append(getattr(self, "reasoning_effort", None))
        return ModelResponse(role="assistant", content="ok")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


@dataclass
class OpenAIChat(EchoModel):
    id: str = "gpt-4.1"
    provider: str = "OpenAI"
    reasoning_effort: str | None = None


@dataclass
class AzureOpenAI(OpenAIChat):
    provider: str = "Azure"


@dataclass
class xAI(EchoModel):
    id: str = "grok-4"
    provider: str = "xAI"
    reasoning_effort: str | None = None


@dataclass
class Claude(EchoModel):
    id: str = "claude-sonnet-4-5"
    provider: str = "Anthropic"
    max_tokens: int | None = 8192
    thinking: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None
    NON_THINKING_MODELS: ClassVar[set[str]] = {"claude-3-5-haiku-20241022"}


@dataclass
class Gemini(EchoModel):
    id: str = "gemini-2.5-flash"
    provider: str = "Google"
    thinking_budget: int | None = None
    thinking_level: str | None = None
    include_thoughts: bool | None = None


@dataclass
class LevelledModel(EchoModel):
    """A custom model that declares its levels."""

    reasoning_levels: ClassVar[tuple[str, ...]] = ("low", "high")
    reasoning_effort: str | None = None


def _levels(model: Any) -> list[str] | None:
    options = reasoning_options(model)
    return list(options.levels) if options else None


# ------------------------------------------------------------------------------------------- options per provider


def test_openai_reasoning_models_take_reasoning_effort() -> None:
    assert _levels(OpenAIChat(id="o4-mini")) == ["low", "medium", "high"]
    assert _levels(AzureOpenAI(id="gpt-5.1", reasoning_effort="high")) == ["low", "medium", "high"]
    assert reasoning_options(AzureOpenAI(id="gpt-5.1", reasoning_effort="high")).configured == "high"  # type: ignore[union-attr]
    # Models that refuse the parameter get no picker.
    assert _levels(OpenAIChat(id="gpt-4.1")) is None


def test_xai_mini_models_take_two_levels() -> None:
    assert _levels(xAI(id="grok-3-mini")) == ["low", "high"]
    assert _levels(xAI(id="grok-4")) is None


def test_claude_budget_and_adaptive_models() -> None:
    old = Claude(id="claude-sonnet-4-5")
    new = Claude(id="claude-opus-5-5")
    old_options = reasoning_options(old)
    new_options = reasoning_options(new)
    assert old_options is not None and new_options is not None
    assert old_options.levels == ["off", "low", "medium", "high"]
    assert old_options.parameter == "thinking.budget_tokens"
    assert old_options.configured == "off"
    assert new_options.levels[-1] == "max"
    assert new_options.parameter == "output_config.effort"
    assert reasoning_options(Claude(id="claude-3-5-haiku-20241022")) is None


def test_gemini_levels_follow_the_generation() -> None:
    assert _levels(Gemini(id="gemini-3-pro-preview")) == ["low", "high"]
    assert _levels(Gemini(id="gemini-2.5-flash")) == ["off", "low", "medium", "high"]
    assert _levels(Gemini(id="gemini-2.5-pro")) == ["low", "medium", "high"]
    assert _levels(Gemini(id="gemini-2.0-flash")) is None


def test_unknown_models_have_no_levels_but_declared_ones_do() -> None:
    assert reasoning_options(EchoModel()) is None
    assert reasoning_options(None) is None
    assert _levels(LevelledModel()) == ["low", "high"]


def test_a_registered_profile_wins() -> None:
    class Everything:
        def matches(self, model: Any) -> bool:
            return model.id == "custom"

        def options(self, model: Any) -> ReasoningOptions:
            return ReasoningOptions(levels=["minimal", "max"], parameter="custom")

        def apply(self, model: Any, level: str) -> None:
            model.name = f"custom@{level}"

    register_reasoning_profile(Everything())
    model = EchoModel(id="custom")
    assert _levels(model) == ["minimal", "max"]
    assert with_reasoning(model, "max").name == "custom@max"


# ----------------------------------------------------------------------------------------- applying a level


def test_with_reasoning_sets_provider_parameters_on_a_copy() -> None:
    openai = OpenAIChat(id="o4-mini")
    tuned = with_reasoning(openai, "high")
    assert tuned is not openai
    assert (tuned.reasoning_effort, openai.reasoning_effort) == ("high", None)  # type: ignore[attr-defined]

    budgeted = with_reasoning(Claude(id="claude-sonnet-4-5", max_tokens=1024), "medium")
    assert budgeted.thinking == {"type": "enabled", "budget_tokens": 8192}  # type: ignore[attr-defined]
    assert budgeted.max_tokens > 8192  # type: ignore[attr-defined]

    adaptive = with_reasoning(Claude(id="claude-opus-5-5", output_config={"keep": True}), "max")
    assert adaptive.thinking["type"] == "adaptive"  # type: ignore[attr-defined]
    assert adaptive.output_config == {"keep": True, "effort": "max"}  # type: ignore[attr-defined]
    assert with_reasoning(Claude(id="claude-sonnet-4-5", thinking={"type": "enabled"}), "off").thinking is None  # type: ignore[attr-defined]

    gemini3 = with_reasoning(Gemini(id="gemini-3-pro-preview"), "low")
    assert (gemini3.thinking_level, gemini3.include_thoughts) == ("low", True)  # type: ignore[attr-defined]
    assert with_reasoning(Gemini(id="gemini-2.5-flash"), "off").thinking_budget == 0  # type: ignore[attr-defined]


def test_levels_a_model_does_not_take_leave_it_as_configured() -> None:
    model = xAI(id="grok-3-mini")
    assert with_reasoning(model, "medium") is model
    assert with_reasoning(EchoModel(), "high").id == "echo"
    assert with_reasoning(model, None) is model


def test_the_hook_derives_from_the_configured_model_and_restores_it() -> None:
    configured = OpenAIChat(id="o3")
    agent = Agent(id="thinker", model=configured)

    apply_reasoning_effort(agent=agent, reasoning_effort="low")
    assert agent.model is not configured and agent.model.reasoning_effort == "low"  # type: ignore[union-attr]
    apply_reasoning_effort(agent=agent, reasoning_effort="high")
    assert agent.model.reasoning_effort == "high"  # type: ignore[union-attr]
    apply_reasoning_effort(agent=agent)
    assert agent.model is configured
    assert configured.reasoning_effort is None


def test_a_run_applies_its_reasoning_effort_before_the_model_call() -> None:
    model = LevelledModel()
    agent = Agent(id="levelled", model=model, pre_hooks=[REASONING_HOOK])
    asyncio.run(agent.arun("hi", reasoning_effort="high"))
    asyncio.run(agent.arun("hi again"))
    assert model.seen == ["high", None]
    assert model.reasoning_effort is None


# --------------------------------------------------------------------------------------------- install + route


def test_install_hooks_code_agents_and_the_route_lists_their_levels() -> None:
    member = Agent(id="member", model=LevelledModel())
    agents = [Agent(id="thinker", model=OpenAIChat(id="o4-mini")), Agent(id="plain", model=EchoModel())]
    team = Team(id="crew", model=Claude(id="claude-sonnet-4-5"), members=[member])
    os_ = make_os(agents=agents, teams=[team])

    client = TestClient(install(os_))

    assert all(has_reasoning_hook(component) for component in [*agents, team, member])
    thinker = client.get("/agnostic/v1/reasoning/agents/thinker").json()
    assert thinker == {"levels": ["low", "medium", "high"], "configured": None, "parameter": "reasoning_effort"}
    assert client.get("/agnostic/v1/reasoning/teams/crew").json()["levels"] == ["off", "low", "medium", "high"]
    assert client.get("/agnostic/v1/reasoning/agents/plain").json() is None
    assert client.get("/agnostic/v1/reasoning/agents/missing").json() is None
    assert client.get("/agnostic/v1/reasoning/workflows/noop").status_code == 422

    install(os_)  # idempotent
    assert agents[0].pre_hooks == [REASONING_HOOK]


# ---------------------------------------------------------------------------------------------- coding agents


def test_a_coding_run_passes_its_level_to_the_proxy_model_and_to_pi(tmp_path: Path) -> None:
    provider = FakeProvider(processes=[FakeProcess(fixture_lines("pi-write-and-bash.jsonl"))])
    runtime = CodingRuntime(CodingConfig(callback_url="http://callback:7777"))
    minted: list[Any] = []
    original = runtime.grants.mint

    def mint(**kwargs: Any) -> Any:
        minted.append(kwargs["model"])
        return original(**kwargs)

    runtime.grants.mint = mint  # type: ignore[method-assign]
    agent = PiAgent(
        id="pi-levelled",
        model=LevelledModel(),
        coding=CodingAgentSpec(harness="pi", thinking="low"),
        provider=provider,
        runtime=runtime,
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
    )

    async def run() -> None:
        async for _ in agent.arun(
            "write a file", session_id="s-1", stream=True, stream_events=True, reasoning_effort="high"
        ):
            pass

    asyncio.run(run())

    (stream,) = provider.streams
    assert stream["argv"][stream["argv"].index("--thinking") + 1] == "high"
    (model,) = minted
    assert model.reasoning_effort == "high"
    assert agent.model.reasoning_effort is None  # type: ignore[union-attr]


@pytest.mark.parametrize(("level", "flag"), [("max", "high"), ("minimal", "low"), (None, "low")])
def test_pi_maps_the_shared_levels_onto_its_own(level: str | None, flag: str) -> None:
    agent = PiAgent(
        id="pi-map",
        model=ScriptedModel(),
        coding=CodingAgentSpec(harness="pi", thinking="low"),
        runtime=CodingRuntime(CodingConfig(callback_url="http://callback:7777")),
    )

    class Lease:
        session_id = "s"
        home = "/runtime"
        workspace = "/workspace"

    argv = agent._command("hi", {}, Lease(), False, reasoning=level)  # type: ignore[arg-type]
    assert argv[argv.index("--thinking") + 1] == flag
