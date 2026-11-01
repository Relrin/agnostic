"""The only import surface other modules may use: typed, audited calls that act as Instance admin.

Passthrough calls (``/instances/{instance}/os/...``) never elevate; only typed control-plane actions (approval
decisions) call :class:`GatewayFacade`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from agnostic_gateway.application.elevation import ElevatedResponse, Elevation, ElevationDisabledError
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal

__all__ = ["ElevatedResponse", "ElevationDisabledError", "GatewayFacade", "GatewayFacadeImpl"]


class GatewayFacade(Protocol):
    async def instance(self, ref: str) -> Instance:
        """By id or slug; raises when it doesn't exist or is disabled."""
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


class GatewayFacadeImpl:
    def __init__(self, elevation: Elevation) -> None:
        self._elevation = elevation

    async def instance(self, ref: str) -> Instance:
        return await self._elevation.instance(ref)

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
