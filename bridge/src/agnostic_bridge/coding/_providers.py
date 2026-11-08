"""Where a coding agent's sandbox comes from: Docker on this host, or E2B.

A provider hands out one sandbox per (agent, session), runs bounded commands in it (writing config, reading files)
and starts the harness as a streamed process whose stdout is read line by line. Credentials for the turn are passed
as environment variables of that one process, never on a command line and never baked into the sandbox.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import time
from collections import deque
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from agno.sandbox.base import ExecResult, SandboxError
from agno.utils.log import log_warning

from agnostic_bridge.artifacts._sources import ArtifactSource
from agnostic_bridge.coding._spec import SandboxSpec

MAX_LINE_BYTES = 16 * 1024 * 1024
STDERR_TAIL_LINES = 40
NAMESPACE = "agnostic-coding"


class HarnessExited(SandboxError):
    """The harness process ended (or could not start) without finishing its turn."""


@dataclass
class SandboxLease:
    """One session's sandbox while a turn uses it."""

    provider: str
    ref: str
    agent_id: str
    session_id: str
    workspace: str
    """Absolute path of the working directory the harness edits; artefacts are collected under it."""
    home: str
    """Writable directory for harness configuration and native session files."""
    fresh: bool = False
    """True when this sandbox was created for this turn, so native harness sessions from earlier turns are gone."""
    handle: Any = field(default=None, repr=False)
    last_used: float = field(default_factory=time.monotonic)


@runtime_checkable
class ProcessStream(Protocol):
    def lines(self) -> AsyncIterator[bytes]: ...

    async def write(self, data: bytes) -> None: ...

    async def close_stdin(self) -> None: ...

    async def terminate(self, grace: float = 3.0) -> None: ...

    async def wait(self) -> int: ...

    def stderr_tail(self) -> str: ...


@runtime_checkable
class SandboxProvider(Protocol):
    kind: str

    async def ensure(self, *, agent_id: str, session_id: str, spec: SandboxSpec) -> SandboxLease: ...

    async def exec(
        self, lease: SandboxLease, argv: Sequence[str], *, stdin: bytes = b"", timeout: float = 60
    ) -> ExecResult: ...

    async def stream(
        self, lease: SandboxLease, argv: Sequence[str], *, env: Mapping[str, str], cwd: str, timeout: float
    ) -> ProcessStream: ...

    async def pause(self, lease: SandboxLease) -> None: ...

    async def destroy(self, lease: SandboxLease) -> None: ...

    def artifact_source(self, lease: SandboxLease, root: str) -> ArtifactSource: ...


async def write_file(provider: SandboxProvider, lease: SandboxLease, path: str, data: bytes) -> None:
    """Write ``data`` to ``path`` in the sandbox (parents created, mode 0600)."""
    script = 'umask 077 && mkdir -p "$(dirname "$1")" && cat > "$1"'
    result = await provider.exec(lease, ["sh", "-c", script, "_", path], stdin=data, timeout=30)
    if result.exit_code != 0:
        raise SandboxError(f"Cannot write {path} in the sandbox: {result.stderr.strip()[:300]}")


# ---------------------------------------------------------------------------------------------------- Docker


class _DockerProcess:
    """A ``docker container exec -i`` of the harness. Killing the local client would leave the remote process
    running, so :meth:`terminate` signals the remote process group by the pid file it wrote on start."""

    def __init__(self, process: asyncio.subprocess.Process, kill: Any, deadline: float) -> None:
        self._process = process
        self._kill = kill
        self._deadline = deadline
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._stderr_task = asyncio.ensure_future(self._drain_stderr())
        self._terminated = False

    async def _drain_stderr(self) -> None:
        assert self._process.stderr is not None
        while True:
            line = await self._process.stderr.readline()
            if not line:
                return
            self._stderr.append(line.decode(errors="replace").rstrip())

    async def lines(self) -> AsyncIterator[bytes]:
        assert self._process.stdout is not None
        while True:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                await self.terminate()
                raise asyncio.TimeoutError("The harness turn ran past its timeout")
            try:
                line = await asyncio.wait_for(self._process.stdout.readline(), remaining)
            except asyncio.TimeoutError:
                await self.terminate()
                raise
            except ValueError as error:  # a line over the reader limit
                await self.terminate()
                raise HarnessExited(f"The harness wrote an oversized line: {error}") from error
            if not line:
                return
            yield line.rstrip(b"\r\n")

    async def write(self, data: bytes) -> None:
        stdin = self._process.stdin
        if stdin is None or stdin.is_closing():
            return
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            stdin.write(data)
            await stdin.drain()

    async def close_stdin(self) -> None:
        stdin = self._process.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()

    async def terminate(self, grace: float = 3.0) -> None:
        if self._terminated:
            return
        self._terminated = True
        try:
            await self._kill("TERM")
            try:
                await asyncio.wait_for(self._process.wait(), grace)
            except asyncio.TimeoutError:
                await self._kill("KILL")
        except Exception as error:
            log_warning(f"Coding sandbox: could not signal the harness: {error}")
        finally:
            if self._process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    self._process.kill()

    async def wait(self) -> int:
        code = await self._process.wait()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._stderr_task, 2)
        return code

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr)


class DockerProvider:
    """Sandboxes from Agno's :class:`agno.sandbox.docker.DockerSandbox`: non-root, read-only root filesystem, all
    capabilities dropped, no new privileges, CPU/memory/process limits, and per-session workspace volumes. Nothing
    from the host is mounted and the Docker socket never enters the sandbox."""

    kind = "docker"
    workspace = "/workspace"
    home = "/runtime"

    def __init__(self, *, docker_binary: str = "docker", namespace: str = NAMESPACE) -> None:
        self.docker_binary = docker_binary
        self.namespace = namespace
        self._sandboxes: dict[tuple[Any, ...], Any] = {}

    def _sandbox(self, spec: SandboxSpec) -> Any:
        from agno.sandbox.docker import DockerSandbox

        key = (spec.image, spec.cpus, spec.memory_mb, spec.workspace_mb, spec.pids_limit, spec.network)
        sandbox = self._sandboxes.get(key)
        if sandbox is None:
            sandbox = DockerSandbox(
                spec.image,
                namespace=self.namespace,
                cpus=spec.cpus,
                memory_mb=spec.memory_mb,
                pids_limit=spec.pids_limit,
                workspace_mb=spec.workspace_mb,
                network=spec.network,
                docker_binary=self.docker_binary,
                execution_timeout=float(spec.turn_timeout_s),
            )
            self._sandboxes[key] = sandbox
        return sandbox

    async def ensure(self, *, agent_id: str, session_id: str, spec: SandboxSpec) -> SandboxLease:
        sandbox = self._sandbox(spec)
        handle = await sandbox.afind(session_id, agent_id=agent_id, env={})
        fresh = False
        if handle is not None and handle.state == "paused":
            handle = await sandbox.aresume(handle)
        elif handle is not None and handle.state != "running":
            # A stopped DockerSandbox cannot be restarted (its volumes are memory-backed); start over.
            await sandbox.adestroy(handle)
            handle = None
        if handle is None:
            handle = await sandbox.acreate(session_id, agent_id=agent_id, env={})
            fresh = True
        lease = SandboxLease(
            provider=self.kind,
            ref=handle.provider_ref,
            agent_id=agent_id,
            session_id=session_id,
            workspace=self.workspace,
            home=self.home,
            fresh=fresh,
            handle=(sandbox, handle),
        )
        if fresh:
            await self.exec(lease, ["mkdir", "-p", f"{self.workspace}/.agnostic", f"{self.home}/agnostic"])
        return lease

    async def exec(
        self, lease: SandboxLease, argv: Sequence[str], *, stdin: bytes = b"", timeout: float = 60
    ) -> ExecResult:
        sandbox, handle = lease.handle
        return await sandbox.aexec(handle, list(argv), stdin=stdin, timeout=timeout, max_output_bytes=4 * 1024 * 1024)

    async def stream(
        self, lease: SandboxLease, argv: Sequence[str], *, env: Mapping[str, str], cwd: str, timeout: float
    ) -> ProcessStream:
        pid_file = f"/tmp/agnostic-{os.urandom(6).hex()}.pid"
        launcher = 'echo $$ > "$0"; cd "$1" && shift && exec "$@"'
        names: list[str] = []
        for name in env:
            names.extend(["--env", name])  # the value is read from this client's environment, not the argv
        process = await asyncio.create_subprocess_exec(
            self.docker_binary,
            "container",
            "exec",
            "-i",
            *names,
            lease.ref,
            # --wait: when the exec'd process already leads a group, setsid forks; without waiting, docker exec
            # would end (and close the stream) while the harness still runs.
            "setsid",
            "--wait",
            "sh",
            "-c",
            launcher,
            pid_file,
            cwd,
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **env},
            limit=MAX_LINE_BYTES,
        )

        async def kill(signal: str) -> None:
            # The harness leads its own process group (setsid), so the whole tree gets the signal.
            script = (
                "import os, signal, sys\n"
                "try:\n"
                "    os.killpg(int(open(sys.argv[1]).read().strip()), getattr(signal, 'SIG' + sys.argv[2]))\n"
                "except (OSError, ValueError):\n"
                "    pass\n"
            )
            await self.exec(lease, ["python3", "-I", "-c", script, pid_file, signal], timeout=10)

        return _DockerProcess(process, kill, time.monotonic() + timeout)

    async def pause(self, lease: SandboxLease) -> None:
        sandbox, handle = lease.handle
        await sandbox.apause(handle)

    async def destroy(self, lease: SandboxLease) -> None:
        sandbox, handle = lease.handle
        await sandbox.adestroy(handle)

    def artifact_source(self, lease: SandboxLease, root: str) -> ArtifactSource:
        from agnostic_bridge.coding._workspace import SandboxWorkspaceSource

        return SandboxWorkspaceSource(self, lease, root=root)


# ---------------------------------------------------------------------------------------------------- E2B


class _E2BProcess:
    def __init__(self, sandbox: Any, handle: Any, queue: asyncio.Queue[bytes | None], deadline: float) -> None:
        self._sandbox = sandbox
        self._handle = handle
        self._queue = queue
        self._deadline = deadline
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._code: int | None = None
        self._waiter = asyncio.ensure_future(self._wait())

    def on_stderr(self, text: str) -> None:
        for line in text.splitlines():
            self._stderr.append(line)

    async def _wait(self) -> int:
        try:
            result = await self._handle.wait()
            code = int(getattr(result, "exit_code", 0) or 0)
        except Exception as error:
            code = int(getattr(error, "exit_code", 1) or 1)
        self._code = code
        await self._queue.put(None)
        return code

    async def lines(self) -> AsyncIterator[bytes]:
        while True:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                await self.terminate()
                raise asyncio.TimeoutError("The harness turn ran past its timeout")
            try:
                line = await asyncio.wait_for(self._queue.get(), remaining)
            except asyncio.TimeoutError:
                await self.terminate()
                raise
            if line is None:
                return
            yield line

    async def write(self, data: bytes) -> None:
        await self._sandbox.commands.send_stdin(self._handle.pid, data.decode())

    async def close_stdin(self) -> None:
        close = getattr(self._sandbox.commands, "close_stdin", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await close(self._handle.pid)

    async def terminate(self, grace: float = 3.0) -> None:
        with contextlib.suppress(Exception):
            await self._handle.kill()

    async def wait(self) -> int:
        return await self._waiter

    def stderr_tail(self) -> str:
        return "\n".join(self._stderr)


class E2BProvider:
    """Sandboxes from E2B, built from a template made of the same Dockerfile as the Docker image.

    The sandbox calls back over the internet, so the runtime's callback URL must be reachable from E2B (a public
    HTTPS address, or a tunnel in development).
    """

    kind = "e2b"
    workspace = "/home/user/workspace"
    home = "/home/user/.agnostic-home"

    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("E2B_API_KEY")
        self._live: dict[str, Any] = {}

    @staticmethod
    def _sdk() -> Any:
        try:
            import e2b
        except ImportError as error:
            raise ImportError("E2B sandboxes need the e2b package: pip install 'agnostic-bridge[e2b]'") from error
        return e2b

    async def ensure(self, *, agent_id: str, session_id: str, spec: SandboxSpec) -> SandboxLease:
        sdk = self._sdk()
        key = f"{agent_id}\x00{session_id}"
        sandbox = self._live.get(key)
        fresh = False
        if sandbox is not None:
            try:
                running = await sandbox.is_running()
            except Exception:
                running = False
            if not running:
                try:
                    sandbox = await sdk.AsyncSandbox.connect(sandbox.sandbox_id, api_key=self.api_key)
                except Exception:
                    sandbox = None
        if sandbox is None:
            sandbox = await sdk.AsyncSandbox.create(
                template=spec.template or "base",
                timeout=spec.ttl_s,
                api_key=self.api_key,
                metadata={"namespace": NAMESPACE, "agent": agent_id, "session": session_id},
            )
            self._live[key] = sandbox
            fresh = True
        lease = SandboxLease(
            provider=self.kind,
            ref=str(sandbox.sandbox_id),
            agent_id=agent_id,
            session_id=session_id,
            workspace=self.workspace,
            home=self.home,
            fresh=fresh,
            handle=sandbox,
        )
        if fresh:
            await self.exec(lease, ["mkdir", "-p", f"{self.workspace}/.agnostic", f"{self.home}/agnostic"])
        return lease

    async def exec(
        self, lease: SandboxLease, argv: Sequence[str], *, stdin: bytes = b"", timeout: float = 60
    ) -> ExecResult:
        sandbox = lease.handle
        command = shlex.join(list(argv))
        if stdin:
            # Commands take no stdin in one call; stage it as a file the command reads.
            staged = f"/tmp/agnostic-stdin-{os.urandom(6).hex()}"
            await sandbox.files.write(staged, stdin)
            command = f"{command} < {shlex.quote(staged)}; status=$?; rm -f {shlex.quote(staged)}; exit $status"
        try:
            result = await sandbox.commands.run(command, timeout=timeout)
        except Exception as error:
            code = getattr(error, "exit_code", None)
            if code is None:
                raise SandboxError(f"E2B command failed: {error}") from error
            return ExecResult(
                exit_code=int(code), stdout=getattr(error, "stdout", ""), stderr=getattr(error, "stderr", "")
            )
        return ExecResult(exit_code=int(result.exit_code or 0), stdout=result.stdout or "", stderr=result.stderr or "")

    async def stream(
        self, lease: SandboxLease, argv: Sequence[str], *, env: Mapping[str, str], cwd: str, timeout: float
    ) -> ProcessStream:
        sandbox = lease.handle
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        buffer = bytearray()
        process: _E2BProcess | None = None

        def on_stdout(text: str) -> None:
            buffer.extend(text.encode())
            while (index := buffer.find(b"\n")) >= 0:
                queue.put_nowait(bytes(buffer[:index]).rstrip(b"\r"))
                del buffer[: index + 1]

        def on_stderr(text: str) -> None:
            if process is not None:
                process.on_stderr(text)

        handle = await sandbox.commands.run(
            shlex.join(list(argv)),
            background=True,
            envs=dict(env),
            cwd=cwd,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            stdin=True,
            timeout=0,
        )
        process = _E2BProcess(sandbox, handle, queue, time.monotonic() + timeout)
        return process

    async def pause(self, lease: SandboxLease) -> None:
        pause = getattr(lease.handle, "pause", None) or getattr(lease.handle, "beta_pause", None)
        if pause is not None:
            with contextlib.suppress(Exception):
                await pause()

    async def destroy(self, lease: SandboxLease) -> None:
        self._live.pop(f"{lease.agent_id}\x00{lease.session_id}", None)
        with contextlib.suppress(Exception):
            await lease.handle.kill()

    def artifact_source(self, lease: SandboxLease, root: str) -> ArtifactSource:
        from agnostic_bridge.artifacts._sources import E2BSource

        return E2BSource(lease.handle, root=self.workspace)


def make_provider(kind: str) -> SandboxProvider:
    if kind == "docker":
        return DockerProvider()
    if kind == "e2b":
        return E2BProvider()
    raise ValueError(f"Unknown sandbox provider: {kind}")
