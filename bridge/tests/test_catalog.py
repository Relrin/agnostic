"""The tool catalog: pulling the manifest, building entries under this runtime's rules, and keeping the registry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from agno.registry import Registry
from agno.tools import Toolkit
from fastapi.testclient import TestClient

from agnostic_bridge import install
from agnostic_bridge._catalog import Builder, NotBuildable, ToolCatalogConfig, ToolCatalogSync, resolve
from tests.conftest import make_os

URL = "https://cp.example.com"
INSTANCE = "ins_01TEST"
CONFIG = ToolCatalogConfig(control_plane_url=URL, instance_id=INSTANCE, token="agn_pat_test", interval=60)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def calculator(name: str = "org-calculator", revision: str = "r1") -> dict[str, Any]:
    return {
        "name": name,
        "kind": "toolkit",
        "toolkit": "calculator",
        "params": {},
        "local": False,
        "revision": revision,
    }


def manifest(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "instance_id": INSTANCE, "entries": list(entries)}


class MCPTools(Toolkit):
    """Stands in for agno's MCPTools: the bridge recognises MCP toolkits by class name."""

    def __init__(self, name: str, fail: bool = False) -> None:
        super().__init__(name=name, tools=[])
        self.fail = fail
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        if self.fail:
            raise ConnectionError("refused")
        self.connected = True

        def search(query: str) -> str:
            return query

        self.functions = {}
        self.register(search, name=f"{self.name.replace('-', '_')}_search")

    async def close(self) -> None:
        self.closed = True


class FakeBuilder(Builder):
    def __init__(self, *, fail: set[str] | None = None, **kwargs: Any) -> None:
        super().__init__(allow_local=kwargs.get("allow_local", False), local_commands=("npx",), env={})
        self.fail = fail or set()
        self.built: list[MCPTools] = []

    def _mcp(self, item: Any) -> Any:
        tool = MCPTools(str(item["name"]), fail=item["name"] in self.fail)
        self.built.append(tool)
        return tool


def server(name: str = "org-linear", revision: str = "r1") -> dict[str, Any]:
    return {
        "name": name,
        "kind": "mcp",
        "transport": "streamable-http",
        "url": "https://mcp.example.com/mcp",
        "headers": {},
        "local": False,
        "revision": revision,
    }


def names(registry: Registry) -> list[str]:
    return sorted(str(getattr(tool, "name", "")) for tool in registry.tools)


# ---------------------------------------------------------------- configuration


def test_config_is_off_without_url_instance_and_token() -> None:
    assert ToolCatalogConfig.from_env({}) is None
    assert ToolCatalogConfig.from_env({"AGNOSTIC_CONTROL_PLANE_URL": URL, "AGNOSTIC_INSTANCE_ID": INSTANCE}) is None


def test_config_from_env() -> None:
    config = ToolCatalogConfig.from_env(
        {
            "AGNOSTIC_CONTROL_PLANE_URL": f"{URL}/",
            "AGNOSTIC_INSTANCE_ID": INSTANCE,
            "AGNOSTIC_TOOL_CATALOG_TOKEN": "agn_pat_x",
            "AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL": "true",
            "AGNOSTIC_TOOL_CATALOG_LOCAL_COMMANDS": "uvx",
            "AGNOSTIC_TOOL_CATALOG_INTERVAL": "5",
        }
    )
    assert config is not None
    assert config.manifest_url == f"{URL}/api/v1/tool-catalog/sync/{INSTANCE}/manifest"
    assert config.allow_local is True
    assert config.local_commands == ("uvx",)
    assert config.interval == 10  # never more often than every 10 seconds


# ---------------------------------------------------------------- building


def test_env_refs_are_read_on_the_runtime() -> None:
    assert resolve({"env": "TOKEN", "format": "Bearer {}"}, {"TOKEN": "abc"}, ["TOKEN"]) == "Bearer abc"
    assert resolve({"env": "LINEAR_TOKEN"}, {"LINEAR_TOKEN": "x"}, ["LINEAR_*"]) == "x"
    assert resolve("plain", {}) == "plain"
    with pytest.raises(NotBuildable) as caught:
        resolve({"env": "MISSING"}, {}, ["MISSING"])
    assert caught.value.state == "missing_env"


def test_entries_read_only_the_variables_the_runtime_allows() -> None:
    env = {"AWS_SECRET_ACCESS_KEY": "s3cr3t", "AGNOSTIC_TOOL_CATALOG_TOKEN": "agn_pat_x"}
    with pytest.raises(NotBuildable, match="AGNOSTIC_TOOL_CATALOG_ENV"):
        resolve({"env": "AWS_SECRET_ACCESS_KEY"}, env)
    with pytest.raises(NotBuildable):  # the bridge's own settings, even with a catch-all
        resolve({"env": "AGNOSTIC_TOOL_CATALOG_TOKEN"}, env, ["*"])
    builder = Builder(allow_local=False, local_commands=(), env=env)
    item = {**server(), "url": "https://elsewhere.example/mcp", "headers": {"X-A": {"env": "AWS_SECRET_ACCESS_KEY"}}}
    with pytest.raises(NotBuildable) as caught:
        builder.build(item)
    assert caught.value.state == "missing_env"


def test_local_tools_need_the_runtime_to_opt_in() -> None:
    builder = Builder(allow_local=False, local_commands=("npx",), env={})
    shell = {"name": "org-shell", "kind": "toolkit", "toolkit": "shell", "params": {}, "local": True}
    with pytest.raises(NotBuildable) as caught:
        builder.build(shell)
    assert caught.value.state == "stdio_disabled"


def test_stdio_needs_the_opt_in_whatever_the_entry_says() -> None:
    builder = Builder(allow_local=False, local_commands=("npx",), env={})
    item = {"name": "org-fs", "kind": "mcp", "transport": "stdio", "command": "npx", "args": [], "local": False}
    with pytest.raises(NotBuildable) as caught:
        builder.build(item)
    assert caught.value.state == "stdio_disabled"


def test_stdio_commands_come_from_the_allowlist() -> None:
    builder = Builder(allow_local=True, local_commands=("npx",), env={})
    item = {"name": "org-fs", "kind": "mcp", "transport": "stdio", "command": "bash", "args": [], "local": True}
    with pytest.raises(NotBuildable) as caught:
        builder.build(item)
    assert caught.value.state == "stdio_disabled"
    assert "bash" in caught.value.detail


def test_only_listed_toolkits_and_parameters_are_built() -> None:
    builder = Builder(allow_local=False, local_commands=(), env={})
    with pytest.raises(NotBuildable, match="doesn't know the toolkit"):
        builder.build({"name": "x", "kind": "toolkit", "toolkit": "os.system", "params": {}})
    with pytest.raises(NotBuildable, match="no parameter"):
        builder.build({"name": "x", "kind": "toolkit", "toolkit": "calculator", "params": {"exec": "rm"}})


def test_a_toolkit_is_named_after_its_entry() -> None:
    tool = Builder(allow_local=False, local_commands=(), env={}).build(calculator("team-data-calculator"))
    assert tool.name == "team-data-calculator"


def test_a_missing_credential_is_reported_not_sent() -> None:
    builder = Builder(allow_local=False, local_commands=(), env={})
    item = {**server(), "headers": {"Authorization": {"env": "LINEAR_TOKEN", "format": "Bearer {}"}}}
    with pytest.raises(NotBuildable) as caught:
        builder.build(item)
    assert caught.value.state == "missing_env"
    assert "LINEAR_TOKEN" in caught.value.detail


# ---------------------------------------------------------------- reconcile


async def test_reconcile_adds_changes_and_removes_entries() -> None:
    agent_os = make_os(registry=Registry())
    builder = FakeBuilder()
    sync = ToolCatalogSync(agent_os, CONFIG, builder=builder)

    await sync.reconcile(manifest(calculator(), server()))
    assert names(agent_os.registry) == ["org-calculator", "org-linear"]
    assert builder.built[0].connected
    assert {entry.name: entry.state for entry in sync.report().entries} == {
        "org-calculator": "connected",
        "org-linear": "connected",
    }
    assert sync.report().entries[1].functions == ["org_linear_search"]

    first = builder.built[0]
    await sync.reconcile(manifest(calculator(), server(revision="r2")))
    assert names(agent_os.registry) == ["org-calculator", "org-linear"]
    assert agent_os.registry.tools[-1] is builder.built[1]  # the new version replaced the old one
    assert first not in agent_os.registry.tools

    await sync.reconcile(manifest(calculator()))
    assert names(agent_os.registry) == ["org-calculator"]
    await sync.stop()


async def test_a_failed_change_keeps_the_working_version() -> None:
    agent_os = make_os(registry=Registry())
    builder = FakeBuilder()
    sync = ToolCatalogSync(agent_os, CONFIG, builder=builder)
    await sync.reconcile(manifest(server()))
    working = builder.built[0]

    builder.fail = {"org-linear"}
    await sync.reconcile(manifest(server(revision="r2")))

    assert agent_os.registry.tools == [working]
    report = sync.report().entries[0]
    assert report.state == "failed"
    assert "refused" in (report.detail or "")
    await sync.stop()


async def test_a_name_registered_in_code_wins() -> None:
    agent_os = make_os(registry=Registry(tools=[Toolkit(name="org-linear", tools=[])]))
    sync = ToolCatalogSync(agent_os, CONFIG, builder=FakeBuilder())
    await sync.reconcile(manifest(server()))
    assert sync.report().entries[0].state == "conflict"
    assert len(agent_os.registry.tools) == 1
    await sync.stop()


async def test_an_unexpected_error_fails_only_that_entry() -> None:
    agent_os = make_os(registry=Registry())
    broken = {**calculator("org-broken"), "kind": "toolkit", "toolkit": "calculator", "params": None}

    class Exploding(FakeBuilder):
        def _toolkit(self, item: Any) -> Any:
            if item["name"] == "org-broken":
                raise RuntimeError("boom")
            return super()._toolkit(item)

    sync = ToolCatalogSync(agent_os, CONFIG, builder=Exploding())
    await sync.reconcile(manifest(broken, calculator()))
    states = {entry.name: entry.state for entry in sync.report().entries}
    assert states == {"org-broken": "failed", "org-calculator": "connected"}
    await sync.stop()


async def test_failed_entries_are_retried_while_the_catalog_is_unchanged() -> None:
    agent_os = make_os(registry=Registry())
    builder = FakeBuilder(fail={"org-linear"})
    seen: list[httpx.Request] = []
    responses = [httpx.Response(200, json=manifest(server()), headers={"ETag": '"v1"'}), httpx.Response(304)]
    sync = ToolCatalogSync(
        agent_os, CONFIG, builder=builder, http=lambda: httpx.AsyncClient(transport=transport(responses, seen))
    )
    await sync.pull()
    assert sync.report().entries[0].state == "failed"
    builder.fail = set()
    assert await sync.pull() is False
    assert sync.report().entries[0].state == "connected"
    await sync.stop()


async def test_stop_closes_mcp_servers() -> None:
    agent_os = make_os(registry=Registry())
    builder = FakeBuilder()
    sync = ToolCatalogSync(agent_os, CONFIG, builder=builder)
    await sync.reconcile(manifest(server()))
    await sync.reconcile(manifest(server(revision="r2")))  # the first one is retired, in its grace period
    await sync.stop()
    assert builder.built[0].closed
    assert builder.built[1].closed
    assert agent_os.registry.tools == []


# ---------------------------------------------------------------- pulling


def transport(responses: list[httpx.Response], seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses.pop(0)

    return httpx.MockTransport(handler)


async def test_pull_sends_the_token_and_honours_the_etag(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    responses = [
        httpx.Response(200, json=manifest(calculator()), headers={"ETag": '"v1"'}),
        httpx.Response(304),
    ]
    config = ToolCatalogConfig(
        control_plane_url=URL, instance_id=INSTANCE, token="agn_pat_test", cache_path=tmp_path / "catalog.json"
    )
    agent_os = make_os(registry=Registry())
    sync = ToolCatalogSync(agent_os, config, http=lambda: httpx.AsyncClient(transport=transport(responses, seen)))

    assert await sync.pull() is True
    assert await sync.pull() is False

    assert seen[0].headers["authorization"] == "Bearer agn_pat_test"
    assert seen[0].url == httpx.URL(config.manifest_url)
    assert "if-none-match" not in seen[0].headers
    assert seen[1].headers["if-none-match"] == '"v1"'
    assert names(agent_os.registry) == ["org-calculator"]
    assert json.loads((tmp_path / "catalog.json").read_text())["entries"][0]["name"] == "org-calculator"
    await sync.stop()


async def test_a_refused_token_is_an_error() -> None:
    seen: list[httpx.Request] = []
    sync = ToolCatalogSync(
        make_os(registry=Registry()),
        CONFIG,
        http=lambda: httpx.AsyncClient(transport=transport([httpx.Response(403)], seen)),
    )
    with pytest.raises(PermissionError):
        await sync.pull()


async def test_start_builds_from_the_cached_manifest(tmp_path: Path) -> None:
    cache = tmp_path / "catalog.json"
    cache.write_text(json.dumps(manifest(calculator())))
    config = ToolCatalogConfig(control_plane_url=URL, instance_id=INSTANCE, token="t", cache_path=cache)
    agent_os = make_os(registry=Registry())

    def unreachable() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))

    sync = ToolCatalogSync(agent_os, config, http=unreachable)
    await sync.start()
    await asyncio.sleep(0)
    assert names(agent_os.registry) == ["org-calculator"]
    await sync.stop()


# ---------------------------------------------------------------- routes


def test_status_route_is_off_without_configuration() -> None:
    client = TestClient(install(make_os(registry=Registry())))
    body = client.get("/agnostic/v1/tool-catalog/status").json()
    assert body["enabled"] is False
    assert client.post("/agnostic/v1/tool-catalog/sync").json() == {"queued": False}


def test_toolkits_route_lists_what_this_runtime_can_build() -> None:
    client = TestClient(install(make_os(registry=Registry())))
    body = client.get("/agnostic/v1/toolkits").json()
    by_key = {item["key"]: item for item in body["toolkits"]}
    assert by_key["calculator"]["importable"] is True
    assert by_key["shell"]["local"] is True
    assert body["agno_version"]


def test_lifespan_registers_catalog_tools(tmp_path: Path) -> None:
    cache = tmp_path / "catalog.json"
    cache.write_text(json.dumps(manifest(calculator())))
    config = ToolCatalogConfig(
        control_plane_url="http://127.0.0.1:9", instance_id=INSTANCE, token="t", cache_path=cache
    )
    agent_os = make_os(registry=Registry())
    app = install(agent_os, tool_catalog=config)
    with TestClient(app) as client:
        status = client.get("/agnostic/v1/tool-catalog/status").json()
        assert status["enabled"] is True
        assert status["entries"][0] == {
            "name": "org-calculator",
            "state": "connected",
            "detail": None,
            "functions": status["entries"][0]["functions"],
        }
        assert "org-calculator" in names(agent_os.registry)
        assert client.get("/agnostic/v1/capabilities").json()["features"]["tool_catalog"]["enabled"] is True
    assert agent_os.registry.tools == []
