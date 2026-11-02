"""AgentOS calls made by the context endpoints.

They run as the signed-in person through the gateway (their scopes, their user isolation), except the bridge check,
which reads the bridge's capabilities as the control plane.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import orjson

from agnostic_agentos_client import AgentOSError
from agnostic_gateway.facade import GatewayFacade, GatewayResponse
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError, ValidationFailedError

NOT_FOUND = 404
FORBIDDEN = 403
UNPROCESSABLE = 422
BRIDGE_TTL = 300.0
RETRY_TTL = 30.0


class InstanceCallError(AppError):
    status = 502
    code = "instance_error"
    title = "The instance answered with an error"


def detail(response: GatewayResponse) -> str:
    body: object = response.body
    if isinstance(body, dict):
        value = cast("dict[str, object]", body).get("detail")
        if isinstance(value, list):
            return "; ".join(str(cast("dict[str, Any]", item).get("msg", item)) for item in cast("list[Any]", value))
        return str(value) if value is not None else f"HTTP {response.status}"
    return str(cast("str", body))[:300] if body else f"HTTP {response.status}"


def page_items(payload: object) -> tuple[list[dict[str, Any]], int | None]:
    """AgentOS lists come as ``{data, meta}`` or plain arrays: the items and ``meta.total_count``."""
    if isinstance(payload, list):
        items = cast("list[Any]", payload)
        return [cast("dict[str, Any]", item) for item in items if isinstance(item, dict)], len(items)
    if isinstance(payload, dict):
        body = cast("dict[str, Any]", payload)
        data = cast("list[Any]", body.get("data") or [])
        total = cast("dict[str, Any]", body.get("meta") or {}).get("total_count")
        rows = [cast("dict[str, Any]", item) for item in data if isinstance(item, dict)]
        return rows, int(total) if isinstance(total, int | float) else None
    return [], None


def without_none(params: Mapping[str, str | int | None]) -> dict[str, str | int]:
    return {key: value for key, value in params.items() if value is not None and value != ""}


class ContextCalls:
    def __init__(
        self,
        gateway: GatewayFacade,
        instances: InstancesFacade,
        authorizer: Authorizer,
        store: EphemeralStore,
    ) -> None:
        self._gateway = gateway
        self._instances = instances
        self._authorizer = authorizer
        self._store = store

    async def instance(self, ref: str) -> Instance:
        return await self._gateway.instance(ref)

    async def require(self, principal: Principal, scope: str, instance: Instance) -> None:
        _ = await self._authorizer.require(principal, scope, instance_id=instance.id)

    async def allowed(self, principal: Principal, scope: str, instance: Instance) -> bool:
        return (await self._authorizer.check(principal, scope, instance_id=instance.id)).allowed

    async def call(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int | None] | None = None,
        body: Any = None,  # noqa: ANN401
    ) -> GatewayResponse:
        return await self._gateway.call(principal, instance, method, path, params=without_none(params or {}), json=body)

    async def json(
        self,
        principal: Principal,
        instance: Instance,
        path: str,
        *,
        method: str = "GET",
        params: Mapping[str, str | int | None] | None = None,
        body: Any = None,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """The response body; AgentOS errors become problems (404, 403, 422, otherwise 502)."""
        return checked(instance, await self.call(principal, instance, method, path, params=params, body=body))

    async def bridge_serves(self, instance: Instance, endpoint: str) -> bool:
        """Whether agnostic-bridge on the instance serves ``endpoint`` ("GET /agnostic/v1/…"), cached for minutes."""
        key = f"context:bridge:{instance.id}"
        cached = await self._store.get(key)
        if cached is not None:
            return endpoint in cast("list[str]", orjson.loads(cached))
        try:
            body = await self._instances.system_call(instance, "GET", "/agnostic/v1/capabilities")
        except AgentOSError as exc:
            await self._store.set(key, b"[]", ttl=BRIDGE_TTL if exc.status == NOT_FOUND else RETRY_TTL)
            return False
        endpoints = (
            [str(item) for item in cast("list[Any]", cast("dict[str, Any]", body).get("endpoints") or [])]
            if isinstance(body, dict)
            else []
        )
        await self._store.set(key, orjson.dumps(endpoints), ttl=BRIDGE_TTL)
        return endpoint in endpoints


def checked(instance: Instance, response: GatewayResponse) -> Any:  # noqa: ANN401
    if response.status == NOT_FOUND:
        raise NotFoundError(f"{instance.display_name}: {detail(response)}")
    if response.status == FORBIDDEN:
        raise ForbiddenError(f"{instance.display_name}: {detail(response)}")
    if response.status == UNPROCESSABLE:
        raise ValidationFailedError(f"{instance.display_name}: {detail(response)}")
    if not response.ok:
        raise InstanceCallError(
            f"{instance.display_name}: {detail(response)}", extra={"upstream_status": response.status}
        )
    return response.body
