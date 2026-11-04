"""Ephemeral key-value state: web sessions, caches, rate-limit counters, one-time tokens.

Nothing stored here is authoritative: losing it signs people out or costs a cache miss, never data, and an
unreachable cache degrades (:class:`DegradingStore`) instead of failing requests. Redis
(or Valkey/Dragonfly) is the production backend; :class:`MemoryStore` keeps the same semantics inside one process
for SQLite development installs and tests. Only commands all three Redis engines support are used.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from agnostic_kernel import metrics
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

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
        value = cast("bytes | None", await self._redis.get(self._k(key)))  # pyright: ignore[reportUnknownMemberType]
        metrics.cache_lookups.labels("miss" if value is None else "hit").inc()
        return value

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


class DegradingStore:
    """An :class:`EphemeralStore` that treats an unreachable cache as empty instead of failing requests.

    Reads miss, writes are dropped, counters stay at zero (rate limits fail open), ``set_if_absent`` answers
    ``False`` (single-use tokens and locks stay closed). After a failure the cache is skipped for ``cooldown``
    seconds, so a frozen cache costs one socket timeout per window, not one per call.
    """

    def __init__(self, inner: EphemeralStore, *, cooldown: float = 5.0) -> None:
        self._inner = inner
        self._cooldown = cooldown
        self._skip_until = 0.0

    @property
    def degraded(self) -> bool:
        return time.monotonic() < self._skip_until

    async def _call[T](self, call: Callable[[], Awaitable[T]], fallback: T) -> T:
        if self.degraded:
            return fallback
        try:
            return await call()
        except (RedisError, OSError, TimeoutError) as exc:
            self._skip_until = time.monotonic() + self._cooldown
            metrics.cache_lookups.labels("unavailable").inc()
            log.warning("cache.degraded", error=str(exc) or type(exc).__name__, retry_in=self._cooldown)
            return fallback

    async def get(self, key: str) -> bytes | None:
        return await self._call(lambda: self._inner.get(key), None)

    async def set(self, key: str, value: bytes, *, ttl: float | None = None) -> None:
        await self._call(lambda: self._inner.set(key, value, ttl=ttl), None)

    async def set_if_absent(self, key: str, value: bytes, *, ttl: float) -> bool:
        return await self._call(lambda: self._inner.set_if_absent(key, value, ttl=ttl), fallback=False)

    async def pop(self, key: str) -> bytes | None:
        return await self._call(lambda: self._inner.pop(key), None)

    async def delete(self, *keys: str) -> None:
        await self._call(lambda: self._inner.delete(*keys), None)

    async def incr(self, key: str, *, ttl: float) -> int:
        return await self._call(lambda: self._inner.incr(key, ttl=ttl), 0)

    async def expire(self, key: str, ttl: float) -> None:
        await self._call(lambda: self._inner.expire(key, ttl), None)


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
        value = self._live(key)
        metrics.cache_lookups.labels("miss" if value is None else "hit").inc()
        return value

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
