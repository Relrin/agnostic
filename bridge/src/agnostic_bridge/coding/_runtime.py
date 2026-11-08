"""Process-wide state of coding agents: run grants, the sandbox pool and where sandboxes call back.

One :class:`CodingRuntime` per AgentOS process. ``install(agent_os, coding=CodingConfig(...))`` configures it; agents
built before that find it through :func:`coding_runtime` when their first turn starts.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agno.utils.log import log_info, log_warning

from agnostic_bridge.coding._grants import GrantStore
from agnostic_bridge.coding._providers import SandboxLease, SandboxProvider, make_provider
from agnostic_bridge.coding._spec import SandboxSpec


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class CodingConfig:
    callback_url: str | None = None
    """Base URL a sandbox reaches this AgentOS on, such as ``http://host.docker.internal:7777``."""
    materialize: bool = True
    """Turn Studio agents marked as coding agents into runnable coding agents on this runtime."""
    sync_interval: float = 10.0
    reap_interval: float = 60.0

    @classmethod
    def from_env(cls) -> CodingConfig:
        interval = os.environ.get("AGNOSTIC_CODING_SYNC_INTERVAL")
        return cls(
            callback_url=os.environ.get("AGNOSTIC_CODING_CALLBACK_URL") or None,
            materialize=_flag(os.environ.get("AGNOSTIC_CODING_MATERIALIZE"), True),
            sync_interval=float(interval) if interval else 10.0,
        )


@dataclass
class _Entry:
    lease: SandboxLease
    spec: SandboxSpec
    provider: SandboxProvider
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    paused: bool = False


class SandboxPool:
    """The live sandboxes of this process, one per (agent, session), paused when idle and destroyed after their TTL."""

    def __init__(self) -> None:
        self._providers: dict[str, SandboxProvider] = {}
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def provider(self, kind: str) -> SandboxProvider:
        if kind not in self._providers:
            self._providers[kind] = make_provider(kind)
        return self._providers[kind]

    def set_provider(self, provider: SandboxProvider) -> None:
        """Use ``provider`` for its kind (tests, or a provider configured differently)."""
        self._providers[provider.kind] = provider

    def live(self, agent_id: str, session_id: str) -> tuple[SandboxProvider, SandboxLease] | None:
        entry = self._entries.get((agent_id, session_id))
        return (entry.provider, entry.lease) if entry is not None else None

    @contextlib.asynccontextmanager
    async def lease(self, agent_id: str, session_id: str, spec: SandboxSpec) -> AsyncIterator[SandboxLease]:
        key = (agent_id, session_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            provider = self.provider(spec.provider)
            entry = self._entries.get(key)
            if entry is not None and entry.spec != spec:
                # The agent's sandbox settings changed (a new published version): start a new computer.
                await self._destroy(key, entry)
                entry = None
            lease = await provider.ensure(agent_id=agent_id, session_id=session_id, spec=spec)
            if entry is not None and entry.lease.ref == lease.ref:
                lease.fresh = False
            self._entries[key] = _Entry(lease=lease, spec=spec, provider=provider)
            try:
                yield lease
            finally:
                lease.last_used = time.monotonic()

    async def _destroy(self, key: tuple[str, str], entry: _Entry) -> None:
        self._entries.pop(key, None)
        try:
            await entry.provider.destroy(entry.lease)
        except Exception as error:
            log_warning(f"Coding sandbox: could not destroy {entry.lease.ref[:12]}: {error}")

    async def reap(self) -> None:
        """Pause sandboxes idle past their ``idle_pause_s`` and destroy those idle past their ``ttl_s``."""
        now = time.monotonic()
        for key, entry in list(self._entries.items()):
            lock = self._locks.get(key)
            if lock is not None and lock.locked():
                continue
            idle = now - entry.lease.last_used
            if idle >= entry.spec.ttl_s:
                log_info(f"Coding sandbox: destroying idle sandbox of session {entry.lease.session_id}")
                await self._destroy(key, entry)
            elif idle >= entry.spec.idle_pause_s and not entry.paused:
                try:
                    await entry.provider.pause(entry.lease)
                    entry.paused = True
                except Exception as error:
                    log_warning(f"Coding sandbox: could not pause {entry.lease.ref[:12]}: {error}")

    async def destroy_all(self) -> None:
        for key, entry in list(self._entries.items()):
            await self._destroy(key, entry)

    async def destroy_session(self, agent_id: str, session_id: str) -> bool:
        entry = self._entries.get((agent_id, session_id))
        if entry is None:
            return False
        await self._destroy((agent_id, session_id), entry)
        return True

    def __len__(self) -> int:
        return len(self._entries)


class CodingRuntime:
    def __init__(self, config: CodingConfig | None = None) -> None:
        self.config = config or CodingConfig.from_env()
        self.grants = GrantStore()
        self.pool = SandboxPool()
        self._reaper: asyncio.Task[None] | None = None

    @property
    def callback_url(self) -> str:
        url = self.config.callback_url
        if not url:
            raise RuntimeError(
                "Coding agents need a callback URL their sandboxes can reach this AgentOS on: set "
                "AGNOSTIC_CODING_CALLBACK_URL or pass CodingConfig(callback_url=...) to install()"
            )
        return url.rstrip("/")

    def configure(self, config: CodingConfig) -> None:
        self.config = config

    async def start(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.ensure_future(self._reap_forever())

    async def stop(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
            self._reaper = None

    async def _reap_forever(self) -> None:
        while True:
            await asyncio.sleep(self.config.reap_interval)
            try:
                await self.pool.reap()
            except Exception as error:
                log_warning(f"Coding sandbox: reaping failed: {error}")


_runtime: CodingRuntime | None = None


def coding_runtime() -> CodingRuntime:
    """This process's coding runtime, created from the environment on first use."""
    global _runtime
    if _runtime is None:
        _runtime = CodingRuntime()
    return _runtime


def configure_coding(config: CodingConfig) -> CodingRuntime:
    runtime = coding_runtime()
    runtime.configure(config)
    return runtime
