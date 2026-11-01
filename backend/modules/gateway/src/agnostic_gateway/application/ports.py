"""Ports of the gateway module."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol

import httpx

from agnostic_gateway.domain.policies import RoutePolicy
from agnostic_instances.facade import Instance


class RoutePolicyRepository(Protocol):
    async def overrides(self) -> list[RoutePolicy]: ...


class Upstream(Protocol):
    """Pooled HTTP clients per instance; returns responses unread (the caller closes them)."""

    async def send(
        self,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: list[tuple[str, str]],
        headers: Mapping[str, str],
        body: AsyncIterator[bytes] | None,
    ) -> httpx.Response: ...

    async def aclose(self) -> None: ...
