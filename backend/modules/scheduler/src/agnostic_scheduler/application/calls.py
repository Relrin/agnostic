"""AgentOS calls of the scheduler: as the person through the gateway, and the bridge's view of the scheduler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import orjson

from agnostic_agentos_client import AgentOSError
from agnostic_gateway.facade import GatewayFacade, GatewayResponse
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Principal
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationFailedError

NOT_FOUND = 404
FORBIDDEN = 403
CONFLICT = 409
UNPROCESSABLE = 422
BRIDGE_TTL = 30.0


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


def checked(instance: Instance, response: GatewayResponse) -> Any:  # noqa: ANN401
    if response.status == NOT_FOUND:
        raise NotFoundError(f"{instance.display_name}: {detail(response)}")
    if response.status == FORBIDDEN:
        raise ForbiddenError(f"{instance.display_name}: {detail(response)}")
    if response.status == CONFLICT:
        raise ConflictError(f"{instance.display_name}: {detail(response)}")
    if response.status == UNPROCESSABLE:
        raise ValidationFailedError(f"{instance.display_name}: {detail(response)}")
    if not response.ok:
        raise InstanceCallError(
            f"{instance.display_name}: {detail(response)}", extra={"upstream_status": response.status}
        )
    return response.body


class SchedulerCalls:
    def __init__(self, gateway: GatewayFacade, instances: InstancesFacade, store: EphemeralStore) -> None:
        self._gateway = gateway
        self._instances = instances
        self._store = store

    async def instance(self, ref: str) -> Instance:
        return await self._gateway.instance(ref)

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
        clean = {key: value for key, value in (params or {}).items() if value is not None and value != ""}
        response = await self._gateway.call(principal, instance, method, path, params=clean, json=body)
        return checked(instance, response)

    async def bridge_workers(self, instance: Instance) -> dict[str, Any] | None:
        """``GET /agnostic/v1/workers`` as the control plane (cached briefly); ``None`` without the bridge."""
        key = f"sch:bridge-workers:{instance.id}"
        cached = await self._store.get(key)
        if cached is not None:
            value = orjson.loads(cached)
            return cast("dict[str, Any]", value) if isinstance(value, dict) else None
        try:
            body = await self._instances.system_call(instance, "GET", "/agnostic/v1/workers")
        except AgentOSError:
            await self._store.set(key, b"null", ttl=BRIDGE_TTL)
            return None
        value = cast("dict[str, Any]", body) if isinstance(body, dict) else None
        await self._store.set(key, orjson.dumps(value), ttl=BRIDGE_TTL)
        return value

    async def openapi_paths(self, instance: Instance) -> set[str] | None:
        """The instance's OpenAPI paths (``None`` when it doesn't publish its document)."""
        key = f"sch:openapi:{instance.id}"
        cached = await self._store.get(key)
        if cached is not None:
            value = orjson.loads(cached)
            return set(cast("list[str]", value)) if isinstance(value, list) else None
        try:
            body = await self._instances.system_call(instance, "GET", "/openapi.json")
        except AgentOSError:
            await self._store.set(key, b"null", ttl=300)
            return None
        document = cast("dict[str, Any]", body) if isinstance(body, dict) else None
        paths = sorted(cast("dict[str, Any]", document.get("paths") or {})) if document is not None else None
        await self._store.set(key, orjson.dumps(paths), ttl=300)
        return set(paths) if paths is not None else None
