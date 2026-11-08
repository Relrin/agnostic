"""The adapter every coding agent shares: one sandbox per session, a harness process per turn, events as Agno's.

A turn, in order:

1. take the session's sandbox from the pool (created, resumed or reused) under a per-session lock;
2. mint a run grant and write the harness's configuration into the sandbox, pointing it at this runtime's model
   proxy and tool server with the grant's token;
3. start the harness as one streamed process and translate each JSONL line it prints into Agno run events;
4. report usage from the proxy and revoke the grant, whatever happened.

The base class (:class:`agno.agents.base.BaseExternalAgent`) emits the run's start and end, persists the session,
handles cancellation and replays history into a harness that lost its own session.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import field
from typing import Any, ClassVar

from agno.agents._config import agent_dataclass
from agno.agents.base import BaseExternalAgent, ExternalRunMetricsEvent, ExternalRunResult
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.run.agent import RunContentEvent, RunOutputEvent, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.cancel import araise_if_cancelled
from agno.tools.function import Function

from agnostic_bridge.artifacts._sources import ArtifactSource
from agnostic_bridge.coding._callback import LLM_PREFIX, MCP_PATH
from agnostic_bridge.coding._mcp import flatten_tools
from agnostic_bridge.coding._providers import HarnessExited, ProcessStream, SandboxLease, SandboxProvider
from agnostic_bridge.coding._runtime import CodingRuntime, coding_runtime
from agnostic_bridge.coding._spec import CodingAgentSpec, spec_to_metadata
from agnostic_bridge.reasoning import RUN_KWARG, with_reasoning

STATE_KEY = "agnostic_coding"
TOKEN_ENV = "AGNOSTIC_RUN_TOKEN"
CALLBACK_ENV = "AGNOSTIC_CALLBACK_URL"


class CodingHarnessError(RuntimeError):
    """The harness failed the turn (it said so, or exited without finishing)."""


class EventTranslator:
    """Turns a harness's JSONL output into Agno events. One per turn."""

    def __init__(self, agent: CodingAgent, run_id: str) -> None:
        self.agent = agent
        self.run_id = run_id
        self.session_id: str | None = None
        """The harness's own session id, once it says it."""
        self.finished = False
        """The harness reported the end of its turn."""
        self.error: str | None = None
        self.started: dict[str, dict[str, Any]] = {}

    def feed(self, line: bytes) -> list[RunOutputEvent]:
        text = line.strip()
        if not text:
            return []
        try:
            event = json.loads(text)
        except ValueError:
            return []  # diagnostics a harness prints to stdout are not events
        return self.translate(event) if isinstance(event, dict) else []

    def translate(self, event: dict[str, Any]) -> list[RunOutputEvent]:
        raise NotImplementedError

    # Builders shared by the harness translators.

    def content(self, text: str) -> RunContentEvent:
        return RunContentEvent(
            run_id=self.run_id, agent_id=self.agent.get_id(), agent_name=self.agent.name or "", content=text
        )

    def reasoning(self, text: str) -> RunContentEvent:
        return RunContentEvent(
            run_id=self.run_id,
            agent_id=self.agent.get_id(),
            agent_name=self.agent.name or "",
            content="",
            reasoning_content=text,
        )

    def tool_started(self, call_id: str, raw_name: str, args: Any) -> ToolCallStartedEvent:
        from agno.models.response import ToolExecution

        name, shown_args = display_tool(raw_name, args)
        self.started[call_id] = {"name": name, "args": shown_args}
        return ToolCallStartedEvent(
            run_id=self.run_id,
            agent_id=self.agent.get_id(),
            agent_name=self.agent.name or "",
            tool=ToolExecution(tool_call_id=call_id, tool_name=name, tool_args=shown_args),
        )

    def tool_completed(self, call_id: str, raw_name: str, args: Any, result: str, error: bool) -> list[RunOutputEvent]:
        from agno.models.response import ToolExecution

        events: list[RunOutputEvent] = []
        if call_id not in self.started:
            events.append(self.tool_started(call_id, raw_name, args))
        info = self.started[call_id]
        events.append(
            ToolCallCompletedEvent(
                run_id=self.run_id,
                agent_id=self.agent.get_id(),
                agent_name=self.agent.name or "",
                tool=ToolExecution(
                    tool_call_id=call_id,
                    tool_name=info["name"],
                    tool_args=info["args"],
                    result=result,
                    tool_call_error=error,
                ),
                content=result,
            )
        )
        return events


# Harness tool names as the web app shows them. The raw name is kept in the arguments.
_TOOL_NAMES = {
    "bash": "bash",
    "shell": "bash",
    "read": "read",
    "write": "write",
    "edit": "edit",
    "multiedit": "edit",
    "patch": "edit",
    "apply_patch": "edit",
    "grep": "grep",
    "glob": "find",
    "find": "find",
    "ls": "ls",
    "list": "ls",
}
MCP_TOOL_PREFIXES = ("mcp__agnostic__", "agnostic_")


def display_tool(raw_name: str, args: Any) -> tuple[str, dict[str, Any]]:
    shown = dict(args) if isinstance(args, dict) else ({"input": args} if args not in (None, "") else {})
    name = _TOOL_NAMES.get(raw_name.lower(), raw_name)
    for prefix in MCP_TOOL_PREFIXES:
        if raw_name.startswith(prefix):
            name = raw_name[len(prefix) :]
            break
    if name != raw_name:
        shown["_harness_tool"] = raw_name
    return name, shown


def result_text(value: Any) -> str:
    """Tool output as text: content parts joined, anything else as JSON."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            return "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        if isinstance(value.get("output"), str):
            return value["output"]
    if isinstance(value, list):
        return "".join(result_text(item) for item in value)
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


@agent_dataclass
class CodingAgent(BaseExternalAgent):
    """A coding harness (Pi, OpenCode) running in a sandbox of its own per session, on an Agno model.

    Args:
        model: The Agno model the harness thinks with. It is called from this process through a per-run proxy, so
            its credentials never enter the sandbox.
        instructions: Appended to the harness's own system prompt.
        tools: Agno tools (functions, toolkits, MCP tools) the harness may call, over MCP. Tools that need a person's
            confirmation or input are not offered.
        coding: Harness, sandbox and artefact settings.
        provider: The sandbox provider to use instead of the pool's default for ``coding.sandbox.provider``.
        runtime: The coding runtime (grants, sandbox pool, callback URL); defaults to this process's.
    """

    model: Model | None = None
    instructions: str | list[str] | None = None
    tools: list[Any] | None = None
    coding: CodingAgentSpec | None = None
    provider: SandboxProvider | None = field(default=None, repr=False)
    runtime: CodingRuntime | None = field(default=None, repr=False)
    component_version: int | None = None
    """The published Studio version this agent was built from; ``None`` for one defined in code."""

    _sdk_name: ClassVar[str] = "coding"
    _harness: ClassVar[str] = ""
    # The harness has no end-of-turn event: a clean exit ends the turn.
    _exit_ends_turn: ClassVar[bool] = False
    # What goes to stdin is the whole prompt: close stdin after it so the harness starts.
    _stdin_is_prompt: ClassVar[bool] = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.coding is None:
            self.coding = CodingAgentSpec(harness=self._harness)  # type: ignore[arg-type]
        elif self.coding.harness != self._harness:
            raise ValueError(f"{type(self).__name__} runs {self._harness}, not {self.coding.harness}")
        if self.model is None:
            raise ValueError(f"{type(self).__name__} needs an Agno model")
        self._functions: dict[str, Function] | None = None

    # ------------------------------------------------------------------ settings

    @property
    def spec(self) -> CodingAgentSpec:
        assert self.coding is not None
        return self.coding

    def _runtime(self) -> CodingRuntime:
        return self.runtime or coding_runtime()

    def _provider(self, runtime: CodingRuntime) -> SandboxProvider:
        if self.provider is not None:
            runtime.pool.set_provider(self.provider)
            return self.provider
        return runtime.pool.provider(self.spec.sandbox.provider)

    def _run_model(self) -> tuple[str | None, str | None]:
        if self.model is None:
            return None, None
        return self.model.id, self.model.get_provider()

    def instructions_text(self) -> str | None:
        if not self.instructions:
            return None
        if isinstance(self.instructions, str):
            return self.instructions
        return "\n".join(str(line) for line in self.instructions)

    async def functions(self) -> dict[str, Function]:
        if self._functions is None:
            self._functions = await flatten_tools(self.tools)
        return self._functions

    def to_dict(self) -> dict[str, Any]:
        """The agent in the shape of an Agno agent config, with the coding marker in its metadata."""
        model = self.model
        config: dict[str, Any] = {"id": self.get_id(), "name": self.name}
        if self.description:
            config["description"] = self.description
        if self.instructions:
            config["instructions"] = self.instructions
        if model is not None:
            config["model"] = {"id": model.id, "provider": model.get_provider(), "name": model.name}
        names = [getattr(tool, "name", None) or getattr(tool, "__name__", None) for tool in self.tools or []]
        if any(names):
            config["tools"] = [{"name": name} for name in names if name]
        config["metadata"] = spec_to_metadata(self.spec)
        return config

    # ------------------------------------------------------------------ artefacts

    async def artifact_source(self, session: Any) -> ArtifactSource | None:
        """Files of the session's live sandbox, for collection when the run is stored."""
        session_id = getattr(session, "session_id", None)
        if not session_id:
            return None
        live = self._runtime().pool.live(self.get_id(), session_id)
        if live is None:
            return None
        provider, lease = live
        return provider.artifact_source(lease, self.spec.outputs_root)

    # ------------------------------------------------------------------ harness hooks

    async def _prepare(
        self, provider: SandboxProvider, lease: SandboxLease, callback: str, functions: dict[str, Function]
    ) -> None:
        """Write the harness's configuration into the sandbox."""
        raise NotImplementedError

    def _command(
        self, prompt: str, state: dict[str, Any], lease: SandboxLease, has_tools: bool, reasoning: str | None = None
    ) -> list[str]:
        """The harness command line. ``reasoning`` is the run's ``reasoning_effort``, for harnesses with a flag."""
        raise NotImplementedError

    def _stdin(self, prompt: str) -> bytes:
        """What to send the harness on stdin once it starts (empty: the prompt is on the command line)."""
        return b""

    def _env(self, lease: SandboxLease) -> dict[str, str]:
        return {}

    def _translator(self, run_id: str, state: dict[str, Any]) -> EventTranslator:
        raise NotImplementedError

    async def _after_finish(self, process: ProcessStream) -> None:
        """Called once the harness reports the end of its turn; Pi's RPC mode waits for stdin to close."""
        await process.close_stdin()

    @staticmethod
    def llm_url(callback: str) -> str:
        return callback + LLM_PREFIX

    @staticmethod
    def mcp_url(callback: str) -> str:
        return callback + MCP_PATH

    # ------------------------------------------------------------------ the turn

    async def _ainterrupt_run(self, handle: Any) -> None:
        if isinstance(handle, ProcessStream):
            await handle.terminate()

    async def _arun_adapter(self, input: Any, *, history: list[dict[str, Any]] | None = None, **kwargs: Any) -> Any:
        content = ""
        tools: dict[str, Any] = {}
        metrics: RunMetrics | None = None
        async for event in self._arun_adapter_stream(input, history=history, **kwargs):
            if isinstance(event, RunContentEvent):
                content += event.content or ""
            elif isinstance(event, (ToolCallStartedEvent, ToolCallCompletedEvent)) and event.tool is not None:
                tools[event.tool.tool_call_id or str(len(tools))] = event.tool
            elif isinstance(event, ExternalRunMetricsEvent):
                metrics = event.metrics
        return ExternalRunResult(content=content, tools=list(tools.values()) or None, metrics=metrics)

    async def _arun_adapter_stream(
        self, input: Any, *, history: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> AsyncIterator[RunOutputEvent]:
        runtime = self._runtime()
        provider = self._provider(runtime)
        run_id: str = kwargs["run_id"]
        session_id: str = kwargs["session_id"]
        session = kwargs.get("session")
        state: dict[str, Any] = {}
        if session is not None:
            data = session.session_data if isinstance(session.session_data, dict) else {}
            session.session_data = data
            state = data.setdefault(STATE_KEY, {})
        sandbox = self.spec.sandbox
        callback = runtime.callback_url
        functions = await self.functions()
        assert self.model is not None
        reasoning = kwargs.get(RUN_KWARG) or None
        # The proxy calls the model the grant holds, so the run's level reaches the provider whatever the harness.
        model = with_reasoning(self.model, reasoning)

        async with runtime.pool.lease(self.get_id(), session_id, sandbox) as lease:
            if lease.fresh or state.get("ref") != lease.ref:
                state.pop("harness_session_id", None)
            state.update({"provider": lease.provider, "ref": lease.ref, "harness": self.spec.harness})
            resumed = bool(state.get("harness_session_id"))
            prompt = self._build_prompt(input, history, resumed=resumed)
            token, grant = runtime.grants.mint(
                agent_id=self.get_id(),
                session_id=session_id,
                run_id=run_id,
                model=model,
                functions=functions,
                ttl=sandbox.turn_timeout_s + 60,
            )
            process: ProcessStream | None = None
            try:
                await self._prepare(provider, lease, callback, functions)
                argv = self._command(prompt, state, lease, bool(functions), reasoning=reasoning)
                env = {TOKEN_ENV: token, CALLBACK_ENV: callback, **self._env(lease)}
                await araise_if_cancelled(run_id)
                process = await provider.stream(
                    lease, argv, env=env, cwd=lease.workspace, timeout=float(sandbox.turn_timeout_s)
                )
                self._set_run_handle(run_id, process)
                stdin = self._stdin(prompt)
                if stdin:
                    await process.write(stdin)
                if self._stdin_is_prompt:
                    await process.close_stdin()
                translator = self._translator(run_id, state)
                async for line in process.lines():
                    for event in translator.feed(line):
                        yield event
                    if translator.session_id and state.get("harness_session_id") != translator.session_id:
                        state["harness_session_id"] = translator.session_id
                    if translator.finished:
                        await self._after_finish(process)
                code = await process.wait()
                await araise_if_cancelled(run_id)
                if translator.error:
                    raise CodingHarnessError(translator.error)
                if not translator.finished and code == 0 and self._exit_ends_turn:
                    translator.finished = True
                if not translator.finished:
                    tail = process.stderr_tail().strip()
                    raise HarnessExited(
                        f"{self.spec.harness} exited with code {code} before finishing its turn"
                        + (f": {tail[-1500:]}" if tail else "")
                    )
                yield ExternalRunMetricsEvent(run_id=run_id, agent_id=self.get_id(), metrics=_run_metrics(grant.usage))
            finally:
                self._clear_run_handle(run_id)
                runtime.grants.revoke(token)
                if process is not None:
                    await process.terminate(grace=1.0)


def _run_metrics(usage: Any) -> RunMetrics:
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        reasoning_tokens=int(getattr(usage, "reasoning_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_tokens", 0) or 0),
        cost=getattr(usage, "cost", None),
    )
