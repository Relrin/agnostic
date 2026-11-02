"""AgentOS calls made by the typed observe endpoints, and the list envelope they return."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from agnostic_gateway.facade import GatewayFacade, GatewayResponse
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError

NOT_FOUND = 404
FORBIDDEN = 403


class InstanceCallError(AppError):
    status = 502
    code = "instance_error"
    title = "The instance answered with an error"


def page_items(payload: object) -> tuple[list[dict[str, Any]], int | None]:
    """AgentOS lists come as ``{data, meta}`` or plain arrays."""
    if isinstance(payload, list):
        items = cast("list[Any]", payload)
        return [cast("dict[str, Any]", i) for i in items if isinstance(i, dict)], len(items)
    if isinstance(payload, dict):
        body = cast("dict[str, Any]", payload)
        data = cast("list[Any]", body.get("data") or [])
        meta = cast("dict[str, Any]", body.get("meta") or {})
        total = meta.get("total_count")
        return [cast("dict[str, Any]", i) for i in data if isinstance(i, dict)], int(
            total
        ) if total is not None else None
    return [], None


def detail(response: GatewayResponse) -> str:
    body: object = response.body
    if isinstance(body, dict):
        value = cast("dict[str, object]", body).get("detail")
        return str(value) if value is not None else f"HTTP {response.status}"
    return str(cast("str", body))[:300] if body else f"HTTP {response.status}"


class PersonCalls:
    """Calls AgentOS as the signed-in person through the gateway and turns error statuses into problems."""

    def __init__(self, gateway: GatewayFacade) -> None:
        self._gateway = gateway

    async def instance(self, ref: str) -> Instance:
        return await self._gateway.instance(ref)

    async def json(
        self,
        principal: Principal,
        instance: Instance,
        path: str,
        *,
        method: str = "GET",
        params: Mapping[str, str | int] | None = None,
        body: Any = None,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        response = await self._gateway.call(principal, instance, method, path, params=params, json=body)
        if response.status == NOT_FOUND:
            raise NotFoundError(f"{instance.display_name}: {detail(response)}")
        if response.status == FORBIDDEN:
            raise ForbiddenError(f"{instance.display_name}: {detail(response)}")
        if not response.ok:
            raise InstanceCallError(
                f"{instance.display_name}: {detail(response)}", extra={"upstream_status": response.status}
            )
        return response.body
