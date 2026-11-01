"""How the client authenticates to a runtime: nothing, an ``OS_SECURITY_KEY``, or a (minted) bearer token."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol


class Auth(Protocol):
    async def headers(self) -> dict[str, str]: ...


class NoAuth:
    """``auth_mode=none`` (development only)."""

    async def headers(self) -> dict[str, str]:
        return {}


class SecurityKeyAuth:
    """``auth_mode=security_key``: a static key sent as a bearer token."""

    def __init__(self, key: str) -> None:
        self._key = key

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"}


class StaticBearerAuth:
    """A token minted once for a short task (connection tests, capability probes)."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


class BearerAuth:
    """``auth_mode=jwt``: asks ``token_provider`` for a token per request (the gateway caches minted JWTs)."""

    def __init__(self, token_provider: Callable[[], Awaitable[str]]) -> None:
        self._token_provider = token_provider

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._token_provider()}"}
