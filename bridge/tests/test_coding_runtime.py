"""Coding agents on a runtime: Studio components materialized, the listing route, sandboxes, workspace files."""

from __future__ import annotations

import asyncio
import base64
import io
import sys
import tarfile
import types
from pathlib import Path
from typing import Any

import pytest
from agno.agent import Agent
from agno.db.base import ComponentType
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from agno.registry import Registry
from agno.sandbox.base import ExecResult
from fastapi.testclient import TestClient

from agnostic_bridge import install
from agnostic_bridge.coding import CodingAgentSpec, CodingConfig, DockerProvider, E2BProvider, PiAgent, SandboxSpec
from agnostic_bridge.coding._materialize import CodingAgentSync
from agnostic_bridge.coding._providers import SandboxLease
from agnostic_bridge.coding._runtime import SandboxPool
from agnostic_bridge.coding._spec import spec_from_metadata, spec_to_metadata
from agnostic_bridge.coding._workspace import SandboxWorkspaceSource
from tests.coding_support import FakeProvider, ScriptedModel

MODEL = ScriptedModel(id="scripted")
MARKER = {"agnostic": {"coding_agent": {"harness": "opencode", "sandbox": {"cpus": 1.0}}}}


def _os(tmp_path: Path, *agents: Any) -> AgentOS:
    db = SqliteDb(db_file=str(tmp_path / "os.db"))
    code = PiAgent(id="pi-coder", name="Pi coder", model=MODEL)
    return AgentOS(
        id="coding-test",
        agents=[code, *agents],
        db=db,
        registry=Registry(models=[MODEL]),
        telemetry=False,
    )


def _publish(agent_os: AgentOS, component_id: str, metadata: dict[str, Any] | None) -> None:
    config = Agent(id=component_id, name=component_id, model=MODEL, instructions="Studio says hi", metadata=metadata)
    db = agent_os.db
    existing = db.get_component(component_id)
    if existing is None:
        db.create_component_with_config(
            component_id, ComponentType.AGENT, component_id, config.to_dict(), stage="published"
        )
    else:
        row = db.upsert_config(component_id, config=config.to_dict(), stage="published")
        db.upsert_component(component_id, component_type=ComponentType.AGENT, current_version=row["version"])


# ---------------------------------------------------------------------------------------------- the marker


def test_marker_round_trip_and_validation() -> None:
    spec = CodingAgentSpec(harness="pi", sandbox=SandboxSpec(provider="e2b", template="coding"))
    metadata = spec_to_metadata(spec, {"team": "x"})
    assert metadata["team"] == "x"
    assert spec_from_metadata(metadata) == spec
    assert spec_from_metadata({"agnostic": {}}) is None
    with pytest.raises(ValueError):
        spec_from_metadata({"agnostic": {"coding_agent": {"harness": "vim"}}})


# ---------------------------------------------------------------------------------------------- Studio components


def test_published_studio_coding_agents_are_served_and_follow_their_versions(tmp_path: Path) -> None:
    agent_os = _os(tmp_path)
    _publish(agent_os, "studio-coder", MARKER)
    _publish(agent_os, "plain-agent", None)
    _publish(agent_os, "pi-coder", MARKER)  # a code-defined id is never replaced
    sync = CodingAgentSync(agent_os)

    first = asyncio.run(sync.refresh())

    assert first.added == ["studio-coder"]
    served = next(agent for agent in agent_os.agents if agent.id == "studio-coder")
    assert served.sdk == "opencode" and served.spec.sandbox.cpus == 1.0
    assert served.instructions == "Studio says hi" and served.component_version == 1
    code = next(agent for agent in agent_os.agents if agent.id == "pi-coder")
    assert code.component_version is None and code.sdk == "pi"

    assert asyncio.run(sync.refresh()).added == []  # unchanged version: nothing rebuilt
    _publish(agent_os, "studio-coder", {"agnostic": {"coding_agent": {"harness": "pi"}}})
    second = asyncio.run(sync.refresh())
    assert second.updated == ["studio-coder"]
    assert next(agent for agent in agent_os.agents if agent.id == "studio-coder").sdk == "pi"

    _publish(agent_os, "studio-coder", None)  # the marker was taken off
    assert asyncio.run(sync.refresh()).removed == ["studio-coder"]
    assert [agent.id for agent in agent_os.agents] == ["pi-coder"]


def test_a_malformed_marker_is_reported_not_served(tmp_path: Path) -> None:
    agent_os = _os(tmp_path)
    _publish(agent_os, "broken", {"agnostic": {"coding_agent": {"harness": "emacs"}}})
    result = asyncio.run(CodingAgentSync(agent_os).refresh())
    assert "broken" in result.errors and result.added == []


def test_listing_route_and_capabilities(tmp_path: Path) -> None:
    agent_os = _os(tmp_path)
    _publish(agent_os, "studio-coder", MARKER)
    app = install(agent_os, coding=CodingConfig(callback_url="http://cb:7777", sync_interval=3600))

    with TestClient(app) as client:  # the lifespan runs the first sync
        refreshed = client.post("/agnostic/v1/coding-agents/refresh").json()
        listed = client.get("/agnostic/v1/coding-agents").json()["items"]
        features = client.get("/agnostic/v1/capabilities").json()["features"]["coding_agents"]

    assert refreshed["errors"] == {}
    by_id = {item["id"]: item for item in listed}
    assert by_id["pi-coder"]["source"] == "code" and by_id["pi-coder"]["harness"] == "pi"
    assert by_id["studio-coder"]["source"] == "studio" and by_id["studio-coder"]["version"] == 1
    assert by_id["studio-coder"]["sandbox"]["provider"] == "docker"
    assert by_id["studio-coder"]["model"] == {"id": "scripted", "provider": "Scripted"}
    assert features == {"enabled": True, "agents": 2, "providers": ["docker"], "studio": True, "callback_url_set": True}


def test_coding_agents_appear_in_introspection_once(tmp_path: Path) -> None:
    agent_os = _os(tmp_path)
    app = install(agent_os, coding=CodingConfig(callback_url="http://cb", materialize=False))
    components = TestClient(app).get("/agnostic/v1/introspect/components").json()
    items = components["items"] if isinstance(components, dict) else components
    coder = [item for item in items if item["id"] == "pi-coder"]
    assert len(coder) == 1 and coder[0]["config"]["metadata"]["agnostic"]["coding_agent"]["harness"] == "pi"


# ---------------------------------------------------------------------------------------------- the pool


def test_pool_pauses_idle_sandboxes_and_destroys_expired_ones() -> None:
    provider = FakeProvider()
    pool = SandboxPool()
    pool.set_provider(provider)
    spec = SandboxSpec(idle_pause_s=10, ttl_s=60)

    async def scenario() -> None:
        async with pool.lease("a", "s", spec) as lease:
            assert lease.fresh
        entry = pool._entries[("a", "s")]
        entry.lease.last_used -= 11
        await pool.reap()
        assert provider.paused == 1 and provider.destroyed == 0
        entry.lease.last_used -= 60
        await pool.reap()
        assert provider.destroyed == 1 and len(pool) == 0

    asyncio.run(scenario())


def test_changed_sandbox_settings_start_a_new_sandbox() -> None:
    provider = FakeProvider()
    pool = SandboxPool()
    pool.set_provider(provider)

    async def scenario() -> None:
        async with pool.lease("a", "s", SandboxSpec()):
            pass
        async with pool.lease("a", "s", SandboxSpec(memory_mb=4096)) as lease:
            assert lease.fresh

    asyncio.run(scenario())
    assert (provider.created, provider.destroyed) == (2, 1)


# ---------------------------------------------------------------------------------------------- providers


def test_docker_stream_passes_credentials_by_name_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class Process:
        stdin = stdout = stderr = None
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def fake_exec(*args: str, **kwargs: Any) -> Any:
        captured["args"], captured["env"] = list(args), kwargs["env"]
        process = Process()
        process.stderr = asyncio.StreamReader()
        process.stderr.feed_eof()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    lease = SandboxLease(
        provider="docker", ref="abc", agent_id="a", session_id="s", workspace="/workspace", home="/runtime"
    )

    async def scenario() -> None:
        await DockerProvider().stream(
            lease, ["pi", "--mode", "rpc"], env={"AGNOSTIC_RUN_TOKEN": "agr_secret"}, cwd="/workspace", timeout=5
        )

    asyncio.run(scenario())
    args = captured["args"]
    assert args[:4] == ["docker", "container", "exec", "-i"]
    assert args[4:6] == ["--env", "AGNOSTIC_RUN_TOKEN"]
    assert "agr_secret" not in " ".join(args)
    assert captured["env"]["AGNOSTIC_RUN_TOKEN"] == "agr_secret"
    assert args[args.index("abc") + 1 : args.index("abc") + 3] == ["setsid", "--wait"]
    assert args[-3:] == ["pi", "--mode", "rpc"]


def test_e2b_provider_streams_lines_from_output_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    class Handle:
        pid = 7

        def __init__(self, on_stdout: Any) -> None:
            self.on_stdout = on_stdout

        async def wait(self) -> Any:
            await asyncio.sleep(0)
            self.on_stdout('{"a":1}\n{"b"')
            self.on_stdout(":2}\n")
            return types.SimpleNamespace(exit_code=0)

        async def kill(self) -> None:
            pass

    class Commands:
        async def run(self, command: str, **kwargs: Any) -> Any:
            assert kwargs["background"] and kwargs["envs"] == {"AGNOSTIC_RUN_TOKEN": "agr_x"}
            return Handle(kwargs["on_stdout"])

    class Sandbox:
        sandbox_id = "sbx-1"
        commands = Commands()

    class AsyncSandbox:
        @staticmethod
        async def create(**kwargs: Any) -> Any:
            assert kwargs["template"] == "coding"
            return Sandbox()

    monkeypatch.setitem(sys.modules, "e2b", types.SimpleNamespace(AsyncSandbox=AsyncSandbox))
    provider = E2BProvider(api_key="e2b_test")
    monkeypatch.setattr(provider, "exec", lambda *a, **k: _done())

    async def scenario() -> list[bytes]:
        lease = await provider.ensure(agent_id="a", session_id="s", spec=SandboxSpec(provider="e2b", template="coding"))
        assert lease.workspace == "/home/user/workspace" and lease.fresh
        process = await provider.stream(
            lease, ["pi"], env={"AGNOSTIC_RUN_TOKEN": "agr_x"}, cwd=lease.workspace, timeout=5
        )
        return [line async for line in process.lines()]

    assert asyncio.run(scenario()) == [b'{"a":1}', b'{"b":2}']


async def _done() -> ExecResult:
    return ExecResult(exit_code=0, stdout="", stderr="")


# ---------------------------------------------------------------------------------------------- workspace files


def test_workspace_source_reads_only_regular_files_under_the_root() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in (("outputs/report.md", b"# Report"), ("outputs/../../etc/passwd", b"x"), ("notes.txt", b"n")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("outputs/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/shadow"
        archive.addfile(link)
    encoded = base64.b64encode(buffer.getvalue()).decode()

    class Provider:
        kind = "docker"

        async def exec(self, lease: Any, argv: list[str], **kwargs: Any) -> ExecResult:
            assert argv[0] == "python3" and argv[-2:] == ["outputs", "2500000"]
            return ExecResult(exit_code=0, stdout=encoded, stderr="")

    lease = SandboxLease(
        provider="docker", ref="r", agent_id="a", session_id="s", workspace="/workspace", home="/runtime"
    )
    source = SandboxWorkspaceSource(Provider(), lease, root="outputs")  # type: ignore[arg-type]

    entries = asyncio.run(source.list())
    assert [entry.path for entry in entries] == ["outputs/report.md"]
    assert asyncio.run(source.read("outputs/report.md", limit=100)) == b"# Report"
    with pytest.raises(Exception, match="larger"):
        asyncio.run(source.read("outputs/report.md", limit=2))
