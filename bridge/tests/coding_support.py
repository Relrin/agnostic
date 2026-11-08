"""Doubles for coding agent tests: a scripted Agno model, a sandbox provider and a harness process."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.sandbox.base import ExecResult

from agnostic_bridge.coding._providers import SandboxLease
from agnostic_bridge.coding._spec import SandboxSpec

FIXTURES = Path(__file__).parent / "fixtures" / "coding"


def fixture_lines(name: str) -> list[bytes]:
    return [line.encode() for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class ScriptedModel(Model):
    """Streams a fixed list of deltas; records what it was asked. Never runs tools."""

    id: str = "scripted"
    name: str = "ScriptedModel"
    provider: str = "Scripted"
    deltas: list[ModelResponse] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("the proxy only streams")

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("the proxy only streams")

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("the proxy is async")

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        self.calls.append(kwargs)
        for delta in self.deltas:
            yield delta

    async def aresponse_stream(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise AssertionError("aresponse_stream runs tools itself; the proxy must not use it")

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class FakeProcess:
    """A harness process printing scripted lines; records stdin; can be terminated mid-stream."""

    def __init__(self, lines: Sequence[bytes], *, exit_code: int = 0, stderr: str = "", hang: bool = False) -> None:
        self._lines = list(lines)
        self.exit_code = exit_code
        self._stderr = stderr
        self._hang = hang
        self.stdin = bytearray()
        self.stdin_closed = False
        self.terminated = False
        self._stop = asyncio.Event()

    async def lines(self) -> AsyncIterator[bytes]:
        for line in self._lines:
            if self.terminated:
                return
            await asyncio.sleep(0)
            yield line
        if self._hang:
            await self._stop.wait()

    async def write(self, data: bytes) -> None:
        self.stdin.extend(data)

    async def close_stdin(self) -> None:
        self.stdin_closed = True

    async def terminate(self, grace: float = 3.0) -> None:
        self.terminated = True
        self._stop.set()

    async def wait(self) -> int:
        return 143 if self.terminated and self._hang else self.exit_code

    def stderr_tail(self) -> str:
        return self._stderr


@dataclass
class FakeProvider:
    """A sandbox provider whose sandboxes are dicts of files; each turn plays the next scripted process."""

    kind: str = "docker"
    processes: list[FakeProcess] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)
    streams: list[dict[str, Any]] = field(default_factory=list)
    created: int = 0
    destroyed: int = 0
    paused: int = 0
    _live: dict[tuple[str, str], SandboxLease] = field(default_factory=dict)

    async def ensure(self, *, agent_id: str, session_id: str, spec: SandboxSpec) -> SandboxLease:
        key = (agent_id, session_id)
        if key in self._live:
            lease = self._live[key]
            lease.fresh = False
            return lease
        self.created += 1
        lease = SandboxLease(
            provider=self.kind,
            ref=f"fake-{self.created}",
            agent_id=agent_id,
            session_id=session_id,
            workspace="/workspace",
            home="/runtime",
            fresh=True,
        )
        self._live[key] = lease
        return lease

    async def exec(
        self, lease: SandboxLease, argv: Sequence[str], *, stdin: bytes = b"", timeout: float = 60
    ) -> ExecResult:
        if argv[:2] == ["sh", "-c"] and "cat >" in argv[2]:
            self.files[argv[-1]] = stdin
        return ExecResult(exit_code=0, stdout="", stderr="")

    async def stream(
        self, lease: SandboxLease, argv: Sequence[str], *, env: Mapping[str, str], cwd: str, timeout: float
    ) -> Any:
        self.streams.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "lease": lease.ref})
        return self.processes.pop(0)

    async def pause(self, lease: SandboxLease) -> None:
        self.paused += 1

    async def destroy(self, lease: SandboxLease) -> None:
        self.destroyed += 1
        self._live.pop((lease.agent_id, lease.session_id), None)

    def forget(self, agent_id: str, session_id: str) -> None:
        """Drop a sandbox as its TTL would, without telling the pool."""
        self._live.pop((agent_id, session_id), None)

    def artifact_source(self, lease: SandboxLease, root: str) -> Any:
        return None


def sse_events(body: str) -> list[Any]:
    events: list[Any] = []
    for block in body.split("\n\n"):
        if block.startswith("data: "):
            payload = block[len("data: ") :]
            events.append(payload if payload == "[DONE]" else json.loads(payload))
    return events
