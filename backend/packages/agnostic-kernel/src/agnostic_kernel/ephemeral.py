"""Ephemeral key-value state: web sessions, caches, rate-limit counters, one-time tokens.

Nothing stored here is authoritative: losing it signs people out or costs a cache miss, never data. Redis
(or Valkey/Dragonfly) is the production backend; :class:`MemoryStore` keeps the same semantics inside one process
for SQLite development installs and tests. Only commands all three Redis engines support are used.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Protocol, cast

from redis.asyncio import Redis

ACCESS_GENERATION_KEY = "access:gen"
"""Bumped whenever something that affects effective scopes changes (bindings, org roles, org settings). Scope and
token caches include it in their keys, so a bump invalidates them all on the next request."""


class EphemeralStore(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, *, ttl: float | None = None) -> None: ...
    async def set_if_absent(self, key: str, value: bytes, *, ttl: float) -> bool: ...
    async def pop(self, key: str) -> bytes | None:
        """Read and delete atomically (single-use tokens)."""
        ...

    async def delete(self, *keys: str) -> None: ...
    async def incr(self, key: str, *, ttl: float) -> int:
        """Increment a counter; the TTL is set when the counter is created."""
        ...

    async def expire(self, key: str, ttl: float) -> None: ...


class RedisStore:
    def __init__(self, redis: Redis, prefix: str = "agnostic:") -> None:
        self._redis = redis
        self._prefix = prefix

    def _k(self, key: str) -> str:
        return self._prefix + key

    async def get(self, key: str) -> bytes | None:
        value = await self._redis.get(self._k(key))  # pyright: ignore[reportUnknownMemberType]
        return cast("bytes | None", value)

    async def set(self, key: str, value: bytes, *, ttl: float | None = None) -> None:
        await self._redis.set(self._k(key), value, px=_ms(ttl) if ttl else None)  # pyright: ignore[reportUnknownMemberType]

    async def set_if_absent(self, key: str, value: bytes, *, ttl: float) -> bool:
        return bool(await self._redis.set(self._k(key), value, px=_ms(ttl), nx=True))  # pyright: ignore[reportUnknownMemberType]

    async def pop(self, key: str) -> bytes | None:
        value = await self._redis.execute_command("GETDEL", self._k(key))  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return cast("bytes | None", value)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*(self._k(key) for key in keys))  # pyright: ignore[reportUnknownMemberType]

    async def incr(self, key: str, *, ttl: float) -> int:
        full = self._k(key)
        value = int(await self._redis.incr(full))  # pyright: ignore[reportUnknownMemberType]
        if value == 1:
            await self._redis.pexpire(full, _ms(ttl))  # pyright: ignore[reportUnknownMemberType]
        return value

    async def expire(self, key: str, ttl: float) -> None:
        await self._redis.pexpire(self._k(key), _ms(ttl))  # pyright: ignore[reportUnknownMemberType]


class MemoryStore:
    """In-process store with TTLs. Single process only (SQLite installs, tests)."""

    def __init__(self, clock: _Clock | None = None) -> None:
        self._data: dict[str, tuple[bytes, float | None]] = {}
        self._clock = clock or time.monotonic

    def _live(self, key: str) -> bytes | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires = entry
        if expires is not None and expires <= self._clock():
            del self._data[key]
            return None
        return value

    def _expiry(self, ttl: float | None) -> float | None:
        return self._clock() + ttl if ttl else None

    async def get(self, key: str) -> bytes | None:
        return self._live(key)

    async def set(self, key: str, value: bytes, *, ttl: float | None = None) -> None:
        self._data[key] = (value, self._expiry(ttl))

    async def set_if_absent(self, key: str, value: bytes, *, ttl: float) -> bool:
        if self._live(key) is not None:
            return False
        self._data[key] = (value, self._expiry(ttl))
        return True

    async def pop(self, key: str) -> bytes | None:
        value = self._live(key)
        self._data.pop(key, None)
        return value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(key, None)

    async def incr(self, key: str, *, ttl: float) -> int:
        current = self._live(key)
        if current is None:
            self._data[key] = (b"1", self._expiry(ttl))
            return 1
        value = int(current) + 1
        self._data[key] = (str(value).encode(), self._data[key][1])
        return value

    async def expire(self, key: str, ttl: float) -> None:
        value = self._live(key)
        if value is not None:
            self._data[key] = (value, self._expiry(ttl))

    def keys(self) -> Iterable[str]:
        return [key for key in list(self._data) if self._live(key) is not None]


class _Clock(Protocol):
    def __call__(self) -> float: ...


def _ms(seconds: float) -> int:
    return max(1, int(seconds * 1000))


async def access_generation(store: EphemeralStore) -> str:
    value = await store.get(ACCESS_GENERATION_KEY)
    return value.decode() if value else "0"


async def bump_access_generation(store: EphemeralStore) -> None:
    """Invalidate every cached scope set and minted token (call after access-relevant changes)."""
    _ = await store.incr(ACCESS_GENERATION_KEY, ttl=30 * 24 * 3600)
