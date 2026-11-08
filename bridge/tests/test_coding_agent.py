"""Coding agent turns: harness output as Agno events, sessions across turns, cancellation and failures.

The Pi and OpenCode fixtures were recorded from the pinned CLIs in the coding image, driven by the reference
runtime's mock coder through the model proxy.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agno.db.sqlite import SqliteDb

from agnostic_bridge.coding import CodingAgentSpec, CodingConfig, CodingRuntime, OpenCodeAgent, PiAgent
from agnostic_bridge.coding._agent import display_tool
from agnostic_bridge.coding._opencode import OpenCodeTranslator
from agnostic_bridge.coding._pi import PiTranslator
from tests.coding_support import FakeProcess, FakeProvider, ScriptedModel, fixture_lines

PI = "pi-write-and-bash.jsonl"
OPENCODE = "opencode-write-and-bash.jsonl"


def _events(translator: Any, lines: list[bytes]) -> list[Any]:
    found: list[Any] = []
    for line in lines:
        found.extend(translator.feed(line))
    return found


def _summary(events: list[Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for event in events:
        name = event.event
        if name == "RunContent":
            rows.append(
                ("reasoning" if event.reasoning_content else "content", event.reasoning_content or event.content)
            )
        elif event.tool is not None:
            rows.append((name, event.tool.tool_name))
    merged: list[tuple[str, str]] = []
    for kind, value in rows:
        if merged and merged[-1][0] == kind and kind in ("reasoning", "content"):
            merged[-1] = (kind, merged[-1][1] + value)
        else:
            merged.append((kind, value))
    return merged


def _agent(cls: type, harness: str, provider: FakeProvider, tmp_path: Path, **kwargs: Any) -> Any:
    return cls(
        id=f"{harness}-test",
        name=f"{harness} test",
        model=ScriptedModel(),
        coding=CodingAgentSpec(harness=harness),
        provider=provider,
        runtime=CodingRuntime(CodingConfig(callback_url="http://callback:7777")),
        db=SqliteDb(db_file=str(tmp_path / "os.db")),
        **kwargs,
    )


async def _collect(stream: Any) -> list[Any]:
    return [event async for event in stream]


def _run(agent: Any, text: str, **kwargs: Any) -> list[Any]:
    return asyncio.run(_collect(agent.arun(text, session_id="session-1", stream=True, stream_events=True, **kwargs)))


# ---------------------------------------------------------------------------------------------- translators


def test_pi_events_become_agno_events() -> None:
    translator = PiTranslator(_agent_stub(), "run-1")
    events = _events(translator, fixture_lines(PI))

    assert _summary(events) == [
        ("reasoning", "The request is about files, so I will write the result under outputs/ and then check it."),
        ("ToolCallStarted", "write"),
        ("ToolCallCompleted", "write"),
        ("ToolCallStarted", "bash"),
        ("ToolCallCompleted", "bash"),
        (
            "content",
            "I wrote `outputs/hello.md` with a short note about your request (write a hello file)"
            " and checked the folder.",
        ),
    ]
    assert translator.finished and translator.error is None
    bash = [event for event in events if event.event == "ToolCallCompleted"][-1].tool
    assert bash.tool_args == {"command": "ls -la outputs"}
    assert "hello.md" in bash.result and not bash.tool_call_error


def test_opencode_events_become_agno_events() -> None:
    translator = OpenCodeTranslator(_agent_stub(), "run-1")
    events = _events(translator, fixture_lines(OPENCODE))

    assert [kind for kind, _ in _summary(events)] == [
        "reasoning",
        "ToolCallStarted",
        "ToolCallCompleted",
        "ToolCallStarted",
        "ToolCallCompleted",
        "content",
    ]
    assert translator.session_id and translator.session_id.startswith("ses_")
    write = next(event for event in events if event.event == "ToolCallCompleted").tool
    assert write.tool_args["filePath"] == "outputs/hello.md"


def test_pi_reports_model_failures_and_exit_codes() -> None:
    translator = PiTranslator(_agent_stub(), "run-1")
    lines = [
        {"type": "tool_execution_start", "toolCallId": "c", "toolName": "bash", "args": {"command": "false"}},
        {
            "type": "tool_execution_end",
            "toolCallId": "c",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "nope"}], "structuredContent": {"exit_code": 2}},
            "isError": True,
        },
        {
            "type": "message_end",
            "message": {"role": "assistant", "stopReason": "error", "errorMessage": "429 slow down"},
        },
        {"type": "agent_settled", "aborted": False},
    ]
    events = _events(translator, [json.dumps(line).encode() for line in lines])
    assert events[-1].tool.result == "nope\n[exit code 2]" and events[-1].tool.tool_call_error
    assert translator.error == "429 slow down" and translator.finished


def test_tool_names_are_shown_plainly() -> None:
    assert display_tool("mcp__agnostic__lookup_order", {"order_id": "1"}) == (
        "lookup_order",
        {"order_id": "1", "_harness_tool": "mcp__agnostic__lookup_order"},
    )
    assert display_tool("glob", {"pattern": "*"})[0] == "find"
    assert display_tool("write", {"path": "a"}) == ("write", {"path": "a"})


def _agent_stub() -> Any:
    return PiAgent(id="stub", name="stub", model=ScriptedModel(), runtime=CodingRuntime(CodingConfig()))


# ---------------------------------------------------------------------------------------------- turns


def test_a_pi_turn_end_to_end(tmp_path: Path) -> None:
    provider = FakeProvider(processes=[FakeProcess(fixture_lines(PI))])
    agent = _agent(PiAgent, "pi", provider, tmp_path, instructions="Be careful.")

    events = _run(agent, "write a hello file")

    names = [event.event for event in events]
    assert names[0] == "RunStarted" and names[-1] == "RunCompleted"
    assert "ToolCallCompleted" in names
    assert events[-1].content.startswith("I wrote `outputs/hello.md`")
    # Configuration points at the callback with the token by reference only.
    models = json.loads(provider.files["/runtime/agnostic/pi/models.json"])
    assert models["providers"]["agnostic"]["baseUrl"] == "http://callback:7777/agnostic/v1/coding/llm/v1"
    assert models["providers"]["agnostic"]["apiKey"] == "${AGNOSTIC_RUN_TOKEN}"
    (stream,) = provider.streams
    token = stream["env"]["AGNOSTIC_RUN_TOKEN"]
    assert token.startswith("agr_")
    assert all(token not in arg for arg in stream["argv"])
    assert all(token.encode() not in data for data in provider.files.values())
    assert "--no-mcp" in stream["argv"]  # no tools, no MCP server
    assert stream["argv"][stream["argv"].index("--append-system-prompt") + 1] == "Be careful."
    assert agent._runtime().grants.verify(token) is None  # revoked when the turn ended


def test_pi_prompt_goes_on_stdin_and_stdin_closes_once_settled(tmp_path: Path) -> None:
    process = FakeProcess(fixture_lines(PI))
    agent = _agent(PiAgent, "pi", FakeProvider(processes=[process]), tmp_path)

    _run(agent, "write a hello file")

    assert json.loads(process.stdin) == {"id": "prompt", "type": "prompt", "message": "write a hello file"}
    assert process.stdin_closed


def test_turns_resume_in_the_same_sandbox_and_replay_history_in_a_new_one(tmp_path: Path) -> None:
    provider = FakeProvider(processes=[FakeProcess(fixture_lines(PI)) for _ in range(3)])
    agent = _agent(PiAgent, "pi", provider, tmp_path)

    _run(agent, "write a hello file")
    second = provider.processes[0]
    _run(agent, "and again")
    assert json.loads(second.stdin)["message"] == "and again"  # Pi has the session; no history pasted
    assert provider.created == 1

    provider.forget("pi-test", "session-1")  # the sandbox went past its TTL
    third = provider.processes[0]
    _run(agent, "one more")
    replayed = json.loads(third.stdin)["message"]
    assert replayed.startswith("Previous conversation") and "and again" in replayed
    assert provider.created == 2

    session = agent.get_session("session-1")
    state = session.session_data["agnostic_coding"]
    assert state["harness"] == "pi" and state["ref"] == "fake-2"


def test_opencode_turn_uses_stdin_and_its_own_session(tmp_path: Path) -> None:
    provider = FakeProvider(processes=[FakeProcess(fixture_lines(OPENCODE)) for _ in range(2)])
    agent = _agent(OpenCodeAgent, "opencode", provider, tmp_path)

    first = provider.processes[0]
    events = _run(agent, "write a hello file")
    _run(agent, "and again")

    assert events[-1].event == "RunCompleted"
    assert first.stdin == b"write a hello file" and first.stdin_closed
    assert "--session" not in provider.streams[0]["argv"]
    second_argv = provider.streams[1]["argv"]
    assert second_argv[second_argv.index("--session") + 1].startswith("ses_")
    config = json.loads(provider.files["/runtime/agnostic/opencode/opencode.json"])
    assert config["provider"]["agnostic"]["options"]["apiKey"] == "{env:AGNOSTIC_RUN_TOKEN}"
    assert config["mcp"] == {}


def test_a_harness_that_dies_fails_the_run_with_its_stderr(tmp_path: Path) -> None:
    lines = fixture_lines(PI)[:5]
    provider = FakeProvider(processes=[FakeProcess(lines, exit_code=1, stderr="pi: out of memory")])
    agent = _agent(PiAgent, "pi", provider, tmp_path)

    events = _run(agent, "write a hello file")

    assert events[-1].event == "RunError"
    assert "pi: out of memory" in events[-1].content


def test_cancelling_a_turn_stops_the_harness(tmp_path: Path) -> None:
    process = FakeProcess(fixture_lines(PI)[:3], hang=True)
    agent = _agent(PiAgent, "pi", FakeProvider(processes=[process]), tmp_path)

    async def scenario() -> list[Any]:
        events: list[Any] = []
        async for event in agent.arun("go", session_id="session-1", run_id="run-x", stream=True, stream_events=True):
            events.append(event)
            if event.event == "RunStarted":
                asyncio.get_running_loop().call_later(0.2, lambda: asyncio.ensure_future(agent.acancel_run("run-x")))
        return events

    events = asyncio.run(asyncio.wait_for(scenario(), 20))

    assert events[-1].event == "RunCancelled"
    assert process.terminated
    assert b'{"type":"abort"}' in bytes(process.stdin)


def test_coding_settings_must_match_the_harness() -> None:
    with pytest.raises(ValueError, match="runs pi"):
        PiAgent(id="x", model=ScriptedModel(), coding=CodingAgentSpec(harness="opencode"))
    with pytest.raises(ValueError, match="model"):
        PiAgent(id="x")


def test_to_dict_carries_the_marker() -> None:
    agent = PiAgent(id="x", name="X", model=ScriptedModel(id="m"), instructions="hi")
    config = agent.to_dict()
    assert config["metadata"]["agnostic"]["coding_agent"]["harness"] == "pi"
    assert config["model"]["id"] == "m"
    assert agent.sdk == "pi"
