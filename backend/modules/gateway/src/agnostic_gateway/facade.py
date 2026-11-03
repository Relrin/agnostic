"""The only import surface other modules may use: typed calls to AgentOS, as the person or as Instance admin.

:meth:`GatewayFacade.call` runs the passthrough pipeline (route policy, scope pre-check, scoped JWT, audit), so a
typed control-plane endpoint sees exactly what the person would see in the browser. Only typed control-plane actions
that the control plane has authorized itself (approval decisions, draft test runs) use :meth:`GatewayFacade.elevated`
or :meth:`GatewayFacade.elevated_stream`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol
from urllib.parse import urlencode

import orjson

from agnostic_gateway.application.elevation import (
    ElevatedResponse,
    ElevatedStream,
    Elevation,
    ElevationDisabledError,
    GatewayResponse,
    decode_body,
)
from agnostic_gateway.application.proxy import Gateway, ProxyRequest
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal

__all__ = [
    "ElevatedResponse",
    "ElevatedStream",
    "ElevationDisabledError",
    "GatewayFacade",
    "GatewayFacadeImpl",
    "GatewayResponse",
]


class GatewayFacade(Protocol):
    async def instance(self, ref: str) -> Instance:
        """By id or slug; raises when it doesn't exist or is disabled."""
        ...

    async def call(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> GatewayResponse:
        """One AgentOS call as ``principal`` (their scopes, their isolation), audited like the passthrough.

        Missing scopes raise the gateway's 403 problem; AgentOS statuses are returned as they are.
        """
        ...

    async def elevated(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        justification: str,
        action_label: str,
        params: Mapping[str, str] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> ElevatedResponse: ...

    async def invalidate(self, instance: Instance) -> None:
        """Forget the gateway's cached responses for the instance (e.g. after the registry changed)."""
        ...

    async def elevated_stream(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        justification: str,
        action_label: str,
        params: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> ElevatedStream:
        """One elevated request whose body is relayed as it arrives (a streamed run of a draft version)."""
        ...


class GatewayFacadeImpl:
    def __init__(self, elevation: Elevation, gateway: Gateway) -> None:
        self._elevation = elevation
        self._gateway = gateway

    async def instance(self, ref: str) -> Instance:
        return await self._elevation.instance(ref)

    async def call(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> GatewayResponse:
        headers = [("accept", "application/json")]
        body: AsyncIterator[bytes] | None = None
        if json is not None:
            headers.append(("content-type", "application/json"))
            body = _once(orjson.dumps(json))
        elif form is not None:
            headers.append(("content-type", "application/x-www-form-urlencoded"))
            body = _once(urlencode(dict(form)).encode())
        response = await self._gateway.handle(
            principal,
            instance.id,
            ProxyRequest(
                method=method.upper(),
                path=path,
                params=[(key, str(value)) for key, value in (params or {}).items()],
                headers=headers,
                body=body,
                scheme="https",
                host=None,
            ),
        )
        try:
            raw = b"".join([chunk async for chunk in response.body])
        finally:
            await response.close()
        return GatewayResponse(response.status, decode_body(raw))

    async def elevated(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        justification: str,
        action_label: str,
        params: Mapping[str, str] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> ElevatedResponse:
        return await self._elevation.send(
            principal,
            instance,
            method,
            path,
            justification=justification,
            action_label=action_label,
            params=params,
            json=json,
            form=form,
        )

    async def invalidate(self, instance: Instance) -> None:
        await self._gateway.invalidate(instance.id)

    async def elevated_stream(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        justification: str,
        action_label: str,
        params: Mapping[str, str] | None = None,
        form: Mapping[str, str] | None = None,
    ) -> ElevatedStream:
        return await self._elevation.stream(
            principal,
            instance,
            method,
            path,
            justification=justification,
            action_label=action_label,
            params=params,
            form=form,
        )


async def _once(content: bytes) -> AsyncIterator[bytes]:
    yield content
