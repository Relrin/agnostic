"""The tool catalog: pull this instance's approved MCP servers and Agno toolkits, build them, keep the registry in step.

The control plane keeps the catalog; this process pulls ``GET {control plane}/api/v1/tool-catalog/sync/{instance}/
manifest`` with a sync token every ``interval`` seconds (and when the control plane asks, ``POST /tool-catalog/
sync``). For every entry it builds the toolkit, connects MCP servers, and adds it to the AgentOS registry under the
entry's name (``org-linear``), so Studio lists it like any registered tool. Entries that go away are taken out of the
registry and closed.

Nothing secret is in the manifest. Credentials are environment variable names that are read here, on the runtime.
Tools that run commands here (stdio MCP servers, the shell, python and file toolkits) are built only when this
runtime opts in with ``AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL=true``, and stdio commands only from
``AGNOSTIC_TOOL_CATALOG_LOCAL_COMMANDS``.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import random
import shlex
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agnostic_bridge.toolkits import ToolkitSpec, importable, load_class, toolkit_list

if TYPE_CHECKING:
    from agno.os import AgentOS

STATUS_PATH = "/tool-catalog/status"
SYNC_PATH = "/tool-catalog/sync"
PROBE_PATH = "/tool-catalog/probe"
TOOLKITS_PATH = "/toolkits"

MANIFEST_VERSION = 1
DEFAULT_INTERVAL = 60
MAX_BACKOFF = 600
CLOSE_GRACE = 30.0
"""Seconds a removed tool stays open, so runs that already hold it can finish."""
DEFAULT_LOCAL_COMMANDS = ("npx", "uvx")
STDIO_BASE_ENV = frozenset(
    {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL"}
)
"""What a stdio server inherits from the runtime besides the variables its entry names (not the bridge's secrets)."""

State = Literal["pending", "connected", "failed", "stdio_disabled", "missing_env", "conflict"]


# ---------------------------------------------------------------- configuration


def _names(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ToolCatalogConfig:
    control_plane_url: str
    instance_id: str
    token: str
    interval: int = DEFAULT_INTERVAL
    allow_local: bool = False
    local_commands: tuple[str, ...] = DEFAULT_LOCAL_COMMANDS
    cache_path: Path | None = None
    """Where the last good manifest is kept, so a restart builds the tools while the control plane is away."""
    ca_bundle: str | None = None
    env_allow: tuple[str, ...] = ()
    """Environment variables catalog entries may read (names, or prefixes ending in ``*``). None by default."""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ToolCatalogConfig | None:
        """``None`` (the catalog is off) unless the control plane URL, instance id and token are all set."""
        env = os.environ if env is None else env
        url = (env.get("AGNOSTIC_CONTROL_PLANE_URL") or "").strip().rstrip("/")
        instance = (env.get("AGNOSTIC_INSTANCE_ID") or "").strip()
        token = (env.get("AGNOSTIC_TOOL_CATALOG_TOKEN") or "").strip()
        if not (url and instance and token):
            return None
        commands = env.get("AGNOSTIC_TOOL_CATALOG_LOCAL_COMMANDS")
        cache = env.get("AGNOSTIC_TOOL_CATALOG_CACHE")
        return cls(
            control_plane_url=url,
            instance_id=instance,
            token=token,
            interval=max(10, int(env.get("AGNOSTIC_TOOL_CATALOG_INTERVAL") or DEFAULT_INTERVAL)),
            allow_local=_flag(env.get("AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL")),
            local_commands=tuple(item.strip() for item in commands.split(",") if item.strip())
            if commands is not None
            else DEFAULT_LOCAL_COMMANDS,
            cache_path=Path(cache) if cache else None,
            ca_bundle=env.get("AGNOSTIC_CONTROL_PLANE_CA_BUNDLE") or None,
            env_allow=_names(env.get("AGNOSTIC_TOOL_CATALOG_ENV")),
        )

    @property
    def manifest_url(self) -> str:
        return f"{self.control_plane_url}/api/v1/tool-catalog/sync/{self.instance_id}/manifest"


# ---------------------------------------------------------------- building tools


class NotBuildable(Exception):
    """An entry this runtime can't build; ``state`` says why (shown in the control plane and in Studio)."""

    def __init__(self, state: State, detail: str) -> None:
        super().__init__(detail)
        self.state: State = state
        self.detail = detail


RESERVED_ENV_PREFIX = "AGNOSTIC_"
"""The bridge's own settings (the sync token among them) are never handed to a catalog entry."""


def env_allowed(name: str, allowed: Sequence[str]) -> bool:
    if name.startswith(RESERVED_ENV_PREFIX):
        return False
    return any(name == item or (item.endswith("*") and name.startswith(item[:-1])) for item in allowed)


def resolve(value: Any, env: Mapping[str, str], allowed: Sequence[str] = ()) -> Any:
    """A literal, or ``{"env": NAME, "format": "Bearer {}"}`` read from this runtime's environment.

    Only variables the runtime lists in ``AGNOSTIC_TOOL_CATALOG_ENV`` are read: an entry is written in the control
    plane, and without the list it could send any of the runtime's secrets to a server of its choosing.
    """
    if isinstance(value, Mapping) and "env" in value:
        name = str(value["env"])
        if not env_allowed(name, allowed):
            raise NotBuildable(
                "missing_env", f"Add {name} to AGNOSTIC_TOOL_CATALOG_ENV on the runtime to let catalog entries read it."
            )
        found = env.get(name)
        if found is None or found == "":
            raise NotBuildable("missing_env", f"Set {name} on the runtime.")
        fmt = value.get("format")
        return fmt.replace("{}", found, 1) if isinstance(fmt, str) else found
    return value


def _accepts(cls: type, name: str) -> bool:
    try:
        parameters = inspect.signature(cls).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values())


@dataclass
class Builder:
    """Turns a manifest entry into an agno toolkit, under this runtime's rules."""

    allow_local: bool
    local_commands: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)
    env_allow: tuple[str, ...] = ()

    def _resolve(self, value: Any) -> Any:
        return resolve(value, self.env, self.env_allow)

    def build(self, item: Mapping[str, Any]) -> Any:
        if item.get("local") and not self.allow_local:
            raise NotBuildable(
                "stdio_disabled",
                "Runs commands on the runtime; set AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL=true to allow it.",
            )
        if item.get("kind") == "mcp":
            return self._mcp(item)
        if item.get("kind") == "toolkit":
            return self._toolkit(item)
        raise NotBuildable("failed", f"Unknown kind {item.get('kind')!r}; update agnostic-bridge.")

    def _mcp(self, item: Mapping[str, Any]) -> Any:
        from agno.tools.mcp import MCPTools

        transport = item.get("transport")
        kwargs: dict[str, Any] = {
            "name": item["name"],
            "transport": transport,
            "timeout_seconds": int(item.get("timeout_seconds") or 10),
            "include_tools": list(item.get("include_tools") or []) or None,
            "exclude_tools": list(item.get("exclude_tools") or []) or None,
            "tool_name_prefix": item.get("tool_name_prefix") or None,
        }
        confirm = list(item.get("requires_confirmation_tools") or [])
        if confirm:
            kwargs["requires_confirmation_tools"] = confirm
        if transport == "stdio":
            if not self.allow_local:  # whatever the entry says about itself
                raise NotBuildable(
                    "stdio_disabled",
                    "Runs commands on the runtime; set AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL=true to allow it.",
                )
            command = str(item.get("command") or "")
            if command not in self.local_commands:
                raise NotBuildable(
                    "stdio_disabled",
                    f"{command!r} isn't in AGNOSTIC_TOOL_CATALOG_LOCAL_COMMANDS ({', '.join(self.local_commands)}).",
                )
            args = [str(arg) for arg in item.get("args") or []]
            kwargs["command"] = shlex.join([command, *args])
            base = {key: value for key, value in self.env.items() if key.upper() in STDIO_BASE_ENV}
            kwargs["env"] = {
                **base,
                **{key: str(self._resolve(value)) for key, value in (item.get("env") or {}).items()},
            }
        elif transport in {"streamable-http", "sse"}:
            kwargs["url"] = str(item["url"])
            headers = {key: str(self._resolve(value)) for key, value in (item.get("headers") or {}).items()}
            if headers:
                kwargs["headers"] = headers
        else:
            raise NotBuildable("failed", f"Unknown transport {transport!r}; update agnostic-bridge.")
        return MCPTools(**kwargs)

    def _toolkit(self, item: Mapping[str, Any]) -> Any:
        key = str(item.get("toolkit") or "")
        spec: ToolkitSpec | None = toolkit_list().get(key)
        if spec is None:
            raise NotBuildable("failed", f"This bridge doesn't know the toolkit {key!r}; update agnostic-bridge.")
        if spec.local and not self.allow_local:
            raise NotBuildable(
                "stdio_disabled",
                "Runs commands on the runtime; set AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL=true to allow it.",
            )
        try:
            cls = load_class(spec)
        except Exception as exc:  # the optional package is missing, or fails to import here
            hint = f" (pip install {spec.extra})" if spec.extra else ""
            raise NotBuildable("failed", f"{spec.label} can't be imported on this runtime{hint}: {exc}") from exc
        kwargs: dict[str, Any] = {}
        for name, value in (item.get("params") or {}).items():
            param = spec.param(name)
            if param is None:
                raise NotBuildable("failed", f"{spec.label} has no parameter {name!r} in this bridge's list.")
            if param.secret and not (isinstance(value, Mapping) and "env" in value):
                raise NotBuildable("failed", f"{spec.label}'s {name} must come from an environment variable.")
            kwargs[name] = self._resolve(value)
        confirm = list(item.get("requires_confirmation_tools") or [])
        if confirm and _accepts(cls, "requires_confirmation_tools"):
            kwargs["requires_confirmation_tools"] = confirm
        try:
            tool = cls(**kwargs)
        except Exception as exc:
            raise NotBuildable("failed", f"{spec.label} didn't start: {exc}") from exc
        tool.name = str(item["name"])  # the level-qualified name keeps two configurations of one toolkit apart
        return tool


def _is_mcp(tool: Any) -> bool:
    return any(cls.__name__ in {"MCPTools", "MultiMCPTools"} for cls in type(tool).__mro__)


def _functions(tool: Any) -> list[str]:
    getter = getattr(tool, "get_functions", None)
    functions = getter() if callable(getter) else getattr(tool, "functions", {})
    return sorted(str(name) for name in (functions or {}))


# ---------------------------------------------------------------- keeping the registry in step


@dataclass
class EntryState:
    name: str
    revision: str
    state: State
    detail: str | None = None
    tool: Any = None
    functions: list[str] = field(default_factory=list)


class ToolCatalogSync:
    """Pulls the manifest, builds what changed, and keeps ``agent_os.registry.tools`` in step with it."""

    def __init__(
        self,
        agent_os: AgentOS,
        config: ToolCatalogConfig,
        *,
        replica_id: str = "",
        builder: Builder | None = None,
        http: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._os = agent_os
        self.config = config
        self.replica_id = replica_id
        self._builder = builder or Builder(config.allow_local, config.local_commands, env_allow=config.env_allow)
        self._http = http or self._client
        self._entries: dict[str, EntryState] = {}
        self._etag: str | None = None
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._closing: set[asyncio.Task[None]] = set()
        self._retired_tools: list[Any] = []
        self._manifest: Mapping[str, Any] | None = None
        self.last_sync_at: datetime | None = None
        self.last_error: str | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=15.0, verify=self.config.ca_bundle or True)

    # ------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        cached = self._read_cache()
        if cached is not None:
            await self.reconcile(cached)
        self._task = asyncio.create_task(self._run(), name="agnostic-tool-catalog")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        for task in list(self._closing):
            task.cancel()
        for tool in self._retired_tools:  # retired ones still in their grace period
            await self._close(tool)
        self._retired_tools.clear()
        for entry in list(self._entries.values()):
            self._unregister(entry.tool)
            await self._close(entry.tool)
        self._entries.clear()

    def wake(self) -> None:
        self._wake.set()

    async def _run(self) -> None:
        delay = 0.0
        failures = 0
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            self._wake.clear()
            try:
                await self.pull()
                failures = 0
                delay = self.config.interval * random.uniform(0.8, 1.2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep pulling: the control plane may be restarting
                failures += 1
                self.last_error = str(exc) or type(exc).__name__
                delay = min(MAX_BACKOFF, self.config.interval * 2 ** min(failures, 6))

    async def pull(self) -> bool:
        """One pull; ``True`` when the manifest changed. Raises when the control plane can't be read."""
        headers = {"Authorization": f"Bearer {self.config.token}", "X-Agnostic-Bridge-Version": _version()}
        if self._etag:
            headers["If-None-Match"] = self._etag
        async with self._http() as client:
            response = await client.get(self.config.manifest_url, headers=headers)
        self.last_sync_at = datetime.now(timezone.utc)
        if response.status_code == 304:
            self.last_error = None
            if self._manifest is not None and any(entry.state == "failed" for entry in self._entries.values()):
                await self.reconcile(self._manifest)  # a server that was down may be back
            return False
        if response.status_code in {401, 403}:
            raise PermissionError(f"The control plane refused the sync token ({response.status_code}).")
        response.raise_for_status()
        manifest = response.json()
        await self.reconcile(manifest)
        self._etag = response.headers.get("etag")
        self._write_cache(manifest)
        self.last_error = None
        return True

    # ------------------------------------------------------------ reconcile

    async def reconcile(self, manifest: Mapping[str, Any]) -> None:
        if int(manifest.get("version") or 0) > MANIFEST_VERSION:
            self.last_error = "The control plane sent a newer catalog format; update agnostic-bridge."
        self._manifest = manifest
        wanted = {str(item["name"]): item for item in manifest.get("entries") or [] if item.get("name")}
        async with self._lock:
            for name in [name for name in self._entries if name not in wanted]:
                self._retire(self._entries.pop(name))
            for name, item in wanted.items():
                current = self._entries.get(name)
                revision = str(item.get("revision") or "")
                if current is not None and current.revision == revision and current.state != "failed":
                    continue
                self._entries[name] = await self._bring_up(name, revision, item, current)

    async def _bring_up(
        self, name: str, revision: str, item: Mapping[str, Any], current: EntryState | None
    ) -> EntryState:
        """Build and connect the new version before taking the old one out, so a bad change keeps the old tool."""
        if self._registered_elsewhere(name, current):
            return EntryState(name, revision, "conflict", f"A tool registered in code is already named {name}.")
        try:
            tool = self._builder.build(item)
        except NotBuildable as exc:
            if current is not None:
                self._retire(current)
            return EntryState(name, revision, exc.state, exc.detail)
        except Exception as exc:  # a missing optional package, a malformed entry: this entry fails, not the rest
            if current is not None and current.tool is not None:
                return EntryState(
                    name, current.revision, "failed", f"Couldn't build: {exc}", current.tool, current.functions
                )
            return EntryState(name, revision, "failed", f"Couldn't build: {exc}")
        if _is_mcp(tool):
            try:
                await asyncio.wait_for(tool.connect(), timeout=float(item.get("timeout_seconds") or 10) + 5)
            except Exception as exc:  # an unreachable server, refused credentials, a crashed command
                await self._close(tool)
                if current is not None and current.tool is not None:
                    return EntryState(
                        name, current.revision, "failed", f"Couldn't connect: {exc}", current.tool, current.functions
                    )
                return EntryState(name, revision, "failed", f"Couldn't connect: {exc}")
        if current is not None:
            self._retire(current)
        registry = self._registry()
        registry.add_tool(tool)
        return EntryState(name, revision, "connected", None, tool, _functions(tool))

    def _registry(self) -> Any:
        registry = getattr(self._os, "registry", None)
        if registry is None:
            from agno.registry import Registry

            registry = Registry()
            self._os.registry = registry
        return registry

    def _registered_elsewhere(self, name: str, current: EntryState | None) -> bool:
        ours = {id(entry.tool) for entry in self._entries.values() if entry.tool is not None}
        if current is not None and current.tool is not None:
            ours.add(id(current.tool))
        tools = getattr(getattr(self._os, "registry", None), "tools", None) or []
        return any(getattr(tool, "name", None) == name and id(tool) not in ours for tool in tools)

    def _unregister(self, tool: Any) -> None:
        registry = getattr(self._os, "registry", None)
        if registry is None or tool is None:
            return
        registry.tools[:] = [item for item in registry.tools if item is not tool]
        registry.__dict__.pop("_entrypoint_lookup", None)  # agno caches the name → function lookup

    def _retire(self, entry: EntryState) -> None:
        if entry.tool is None:
            return
        self._unregister(entry.tool)
        self._retired_tools.append(entry.tool)
        task = asyncio.create_task(self._close_later(entry.tool))
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _close_later(self, tool: Any) -> None:
        await asyncio.sleep(CLOSE_GRACE)
        if tool in self._retired_tools:
            self._retired_tools.remove(tool)
        await self._close(tool)

    @staticmethod
    async def _close(tool: Any) -> None:
        close = getattr(tool, "close", None)
        if close is not None and _is_mcp(tool):
            with contextlib.suppress(Exception):
                await close()

    # ------------------------------------------------------------ cache

    def _read_cache(self) -> dict[str, Any] | None:
        path = self.config.cache_path
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) and data.get("instance_id") == self.config.instance_id else None

    def _write_cache(self, manifest: Mapping[str, Any]) -> None:
        path = self.config.cache_path
        if path is None:
            return
        with contextlib.suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(json.dumps(manifest), encoding="utf-8")
            temp.replace(path)

    # ------------------------------------------------------------ reports

    def report(self) -> CatalogStatus:
        return CatalogStatus(
            enabled=True,
            local_allowed=self.config.allow_local,
            interval_seconds=self.config.interval,
            last_sync_at=self.last_sync_at,
            last_error=self.last_error,
            replica_id=self.replica_id,
            entries=[
                CatalogEntryStatus(name=entry.name, state=entry.state, detail=entry.detail, functions=entry.functions)
                for entry in sorted(self._entries.values(), key=lambda item: item.name)
            ],
        )

    async def probe(self, item: Mapping[str, Any]) -> list[ProbedTool]:
        """Connect to an MCP server once, list its tools, and close it; nothing is registered."""
        if item.get("kind") != "mcp":
            raise NotBuildable("failed", "Only MCP servers can be probed.")
        tool = self._builder.build({**item, "include_tools": [], "exclude_tools": [], "tool_name_prefix": None})
        try:
            await asyncio.wait_for(tool.connect(), timeout=float(item.get("timeout_seconds") or 10) + 5)
            functions = tool.get_functions() if hasattr(tool, "get_functions") else tool.functions
            return [
                ProbedTool(name=str(name), description=getattr(function, "description", None))
                for name, function in sorted((functions or {}).items())
            ]
        finally:
            await self._close(tool)


def _version() -> str:
    from agnostic_bridge._capabilities import __version__

    return __version__


# ---------------------------------------------------------------- routes


class CatalogEntryStatus(BaseModel):
    name: str
    state: State
    detail: str | None = None
    functions: list[str] = Field(default_factory=list)


class CatalogStatus(BaseModel):
    enabled: bool = Field(description="AGNOSTIC_CONTROL_PLANE_URL, AGNOSTIC_INSTANCE_ID and the token are set")
    local_allowed: bool = Field(default=False, description="AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL")
    interval_seconds: int | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None
    replica_id: str | None = None
    entries: list[CatalogEntryStatus] = Field(default_factory=list)


class ProbedTool(BaseModel):
    name: str
    description: str | None = None


class ProbeResult(BaseModel):
    tools: list[ProbedTool]


class SyncResult(BaseModel):
    queued: bool


class ToolkitParamInfo(BaseModel):
    name: str
    type: str
    required: bool
    default: Any = None
    choices: list[Any] = Field(default_factory=list)
    secret: bool = False
    description: str = ""


class ToolkitInfo(BaseModel):
    key: str
    class_path: str
    label: str
    description: str
    category: str
    local: bool
    extra: str | None
    params: list[ToolkitParamInfo]
    importable: bool = Field(description="Its optional package is installed here, so this runtime can build it")


class ToolkitsResponse(BaseModel):
    agno_version: str
    toolkits: list[ToolkitInfo]


def add_catalog_routes(router: APIRouter, holder: CatalogHolder) -> None:
    @router.get(
        STATUS_PATH,
        operation_id="agnostic_bridge_tool_catalog_status",
        summary="Tool catalog status",
        description="What this replica built from the tool catalog, per entry. Needs registry:read.",
        response_model=CatalogStatus,
    )
    async def catalog_status() -> CatalogStatus:
        sync = holder.sync
        return sync.report() if sync is not None else CatalogStatus(enabled=False)

    @router.post(
        SYNC_PATH,
        operation_id="agnostic_bridge_tool_catalog_sync",
        summary="Pull the tool catalog now",
        description="Wakes the puller instead of waiting for the interval. Needs config:write.",
        response_model=SyncResult,
    )
    async def catalog_sync() -> SyncResult:
        if holder.sync is None:
            return SyncResult(queued=False)
        holder.sync.wake()
        return SyncResult(queued=True)

    @router.post(
        PROBE_PATH,
        operation_id="agnostic_bridge_tool_catalog_probe",
        summary="List an MCP server's tools",
        description="Connects to a catalog entry's server once and lists its tools without registering it. "
        "Needs agent_os:admin.",
        response_model=ProbeResult,
    )
    async def catalog_probe(item: dict[str, Any]) -> ProbeResult:
        sync = holder.sync
        builder = sync if sync is not None else ToolCatalogSync(holder.agent_os, _probe_config())
        try:
            return ProbeResult(tools=await builder.probe(item))
        except NotBuildable as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Couldn't connect: {exc}") from exc

    @router.get(
        TOOLKITS_PATH,
        operation_id="agnostic_bridge_list_toolkits",
        summary="Agno toolkits a catalog entry can name",
        description="The toolkits this bridge can build, and whether each one's package is installed. "
        "Needs registry:read.",
        response_model=ToolkitsResponse,
    )
    async def list_toolkits() -> ToolkitsResponse:
        listed = toolkit_list()
        return ToolkitsResponse(
            agno_version=listed.agno_version,
            toolkits=[
                ToolkitInfo(
                    key=spec.key,
                    class_path=spec.class_path,
                    label=spec.label,
                    description=spec.description,
                    category=spec.category,
                    local=spec.local,
                    extra=spec.extra,
                    params=[
                        ToolkitParamInfo(
                            name=param.name,
                            type=param.type,
                            required=param.required,
                            default=param.default,
                            choices=list(param.choices),
                            secret=param.secret,
                            description=param.description,
                        )
                        for param in spec.params
                    ],
                    importable=importable(spec.key),
                )
                for spec in listed.toolkits
            ],
        )


def _probe_config() -> ToolCatalogConfig:
    """Probing works without the catalog being set up; it never pulls."""
    env = os.environ
    return ToolCatalogConfig(
        env_allow=_names(env.get("AGNOSTIC_TOOL_CATALOG_ENV")),
        control_plane_url="",
        instance_id="",
        token="",
        allow_local=_flag(env.get("AGNOSTIC_TOOL_CATALOG_ALLOW_LOCAL")),
        local_commands=tuple(
            item.strip() for item in (env.get("AGNOSTIC_TOOL_CATALOG_LOCAL_COMMANDS") or "npx,uvx").split(",")
        ),
    )


@dataclass
class CatalogHolder:
    """The routes are built before the app starts; the puller exists only while it runs."""

    agent_os: Any
    config: ToolCatalogConfig | None
    replica_id: str
    sync: ToolCatalogSync | None = None

    @contextlib.asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        if self.config is None:
            yield
            return
        self.sync = ToolCatalogSync(self.agent_os, self.config, replica_id=self.replica_id)
        await self.sync.start()
        try:
            yield
        finally:
            await self.sync.stop()
            self.sync = None
