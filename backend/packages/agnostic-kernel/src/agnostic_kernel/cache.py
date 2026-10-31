"""Redis client. Also compatible with Valkey and DragonflyDB.

Only commands all three engines support are used: strings, hashes, sets, sorted sets, streams, pub/sub and Lua with
declared keys. :func:`probe_commands` exercises exactly that subset, so ``agnostic config check --connect`` can tell
an operator whether their cache will work.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from redis.asyncio import Redis
from redis.asyncio.sentinel import Sentinel
from redis.exceptions import RedisError

from agnostic_kernel.settings import RedisSettings

type CacheKind = Literal["redis", "valkey", "dragonfly", "unknown"]


def create_redis(settings: RedisSettings) -> Redis:
    url = settings.url.get_secret_value()
    tls = settings.tls
    ssl_kwargs: dict[str, str] = {}
    if tls.ca_file:
        ssl_kwargs["ssl_ca_certs"] = str(tls.ca_file)
    if tls.cert_file:
        ssl_kwargs["ssl_certfile"] = str(tls.cert_file)
    if tls.key_file:
        ssl_kwargs["ssl_keyfile"] = str(tls.key_file)

    if settings.sentinels:
        if not settings.sentinel_master:
            msg = "AGNOSTIC_REDIS__SENTINEL_MASTER is required when sentinels are configured"
            raise ValueError(msg)
        hosts = [_host_port(item) for item in settings.sentinels]
        sentinel = Sentinel(hosts, socket_timeout=settings.socket_timeout, **ssl_kwargs)  # pyright: ignore[reportArgumentType]
        return sentinel.master_for(settings.sentinel_master, redis_class=Redis)  # pyright: ignore[reportUnknownMemberType]

    kwargs = ssl_kwargs if url.startswith("rediss://") else {}
    return Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        url,
        socket_timeout=settings.socket_timeout,
        socket_connect_timeout=settings.socket_timeout,
        health_check_interval=30,
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


def _host_port(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator:
        return (value, 26379)
    return (host, int(port))


@dataclass(frozen=True, slots=True)
class CacheServerInfo:
    kind: CacheKind
    version: str


@dataclass(slots=True)
class CommandProbe:
    ok: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def classify_server(info: dict[str, object]) -> CacheServerInfo:
    """Tell Redis, Valkey and Dragonfly apart from ``INFO server`` output."""
    if "dragonfly_version" in info:
        return CacheServerInfo("dragonfly", str(info["dragonfly_version"]))
    if "valkey_version" in info or str(info.get("server_name", "")).lower() == "valkey":
        return CacheServerInfo("valkey", str(info.get("valkey_version", info.get("redis_version", ""))))
    if "redis_version" in info:
        return CacheServerInfo("redis", str(info["redis_version"]))
    return CacheServerInfo("unknown", "")


async def detect_server(redis: Redis) -> CacheServerInfo:
    info: dict[str, object] = await redis.info("server")  # pyright: ignore[reportUnknownMemberType]
    return classify_server(info)


async def probe_commands(redis: Redis) -> CommandProbe:
    """Run each command family the control plane relies on against throwaway keys."""
    prefix = f"agnostic:probe:{uuid.uuid4().hex}"
    probe = CommandProbe()

    async def attempt(name: str, *command: str | int) -> None:
        try:
            await redis.execute_command(*command)  # pyright: ignore[reportUnknownMemberType]
        except RedisError as exc:
            probe.failed[name] = str(exc)
        else:
            probe.ok.append(name)

    await attempt("SET/EX", "SET", f"{prefix}:s", "1", "EX", 30)
    await attempt("GET", "GET", f"{prefix}:s")
    await attempt("HSET", "HSET", f"{prefix}:h", "f", "v")
    await attempt("SADD", "SADD", f"{prefix}:set", "m")
    await attempt("ZADD", "ZADD", f"{prefix}:z", 1, "m")
    await attempt("XADD/MAXLEN", "XADD", f"{prefix}:x", "MAXLEN", "~", 10, "*", "f", "v")
    await attempt("XRANGE", "XRANGE", f"{prefix}:x", "-", "+")
    await attempt("PUBLISH", "PUBLISH", f"{prefix}:chan", "ping")
    await attempt("EVAL", "EVAL", "return redis.call('GET', KEYS[1])", 1, f"{prefix}:s")
    await attempt("PEXPIRE", "PEXPIRE", f"{prefix}:h", 30_000)
    await attempt(
        "DEL",
        "DEL",
        f"{prefix}:s",
        f"{prefix}:h",
        f"{prefix}:set",
        f"{prefix}:z",
        f"{prefix}:x",
    )
    return probe
