"""Instance lookup, scope checks, AgentOS calls and bridge detection shared by the studio use cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import orjson

from agnostic_agentos_client import AgentOSError
from agnostic_gateway.facade import GatewayFacade, GatewayResponse
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from agnostic_kernel.logging import get_logger
from agnostic_studio.domain.model import StudioRuleError

READ_SCOPE = "components:read"
WRITE_SCOPE = "components:write"
DELETE_SCOPE = "components:delete"
REGISTRY_SCOPE = "registry:read"
PROMOTE_SCOPE = "studio:promote"
OVERRIDE_SCOPE = "evals:gates:override"

BRIDGE_VALIDATE = "POST /agnostic/v1/components/validate"
BRIDGE_NORMALIZE = "POST /agnostic/v1/components/normalize"
BRIDGE_INTROSPECT = "GET /agnostic/v1/introspect/components"
BRIDGE_SOURCE = "GET /agnostic/v1/registry/{resource_type}/{name}/source"
BRIDGE_CEL = "POST /agnostic/v1/cel/evaluate"
BRIDGE_CODING_REFRESH = "POST /agnostic/v1/coding-agents/refresh"
BRIDGE_TTL = 300.0
RETRY_TTL = 30.0
PAGE_LIMIT = 100
MAX_PAGES = 50

NOT_FOUND = 404
FORBIDDEN = 403
CONFLICT = 409
UNPROCESSABLE = 422

log = get_logger(__name__)


class InstanceCallError(AppError):
    status = 502
    code = "instance_error"
    title = "The instance answered with an error"


def rule(exc: StudioRuleError) -> ValidationFailedError:
    return ValidationFailedError(str(exc))


def detail(response: GatewayResponse) -> str:
    body: object = response.body
    if isinstance(body, dict):
        value = cast("dict[str, object]", body).get("detail")
        if isinstance(value, list):
            return "; ".join(str(cast("dict[str, Any]", item).get("msg", item)) for item in cast("list[Any]", value))
        return str(value) if value is not None else f"HTTP {response.status}"
    return str(cast("str", body))[:300] if body else f"HTTP {response.status}"


def page_items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [cast("dict[str, Any]", item) for item in cast("list[Any]", payload) if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = cast("list[Any]", cast("dict[str, Any]", payload).get("data") or [])
        return [cast("dict[str, Any]", item) for item in data if isinstance(item, dict)]
    return []


def total_pages(payload: object) -> int:
    if isinstance(payload, dict):
        meta = cast("dict[str, Any]", cast("dict[str, Any]", payload).get("meta") or {})
        return int(meta.get("total_pages") or 1)
    return 1


class StudioAccess:
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

    @property
    def gateway(self) -> GatewayFacade:
        return self._gateway

    async def instance(self, principal: Principal, ref: str, scope: str = READ_SCOPE) -> Instance:
        instance = await self._gateway.instance(ref)
        _ = await self._authorizer.require(principal, scope, instance_id=instance.id)
        return instance

    async def require(self, principal: Principal, scope: str, instance: Instance) -> None:
        _ = await self._authorizer.require(principal, scope, instance_id=instance.id)

    async def allowed(self, principal: Principal, scope: str, instance: Instance) -> bool:
        return (await self._authorizer.check(principal, scope, instance_id=instance.id)).allowed

    async def instances(self) -> list[Instance]:
        return await self._instances.list()

    async def call(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        body: Any = None,  # noqa: ANN401
    ) -> GatewayResponse:
        if principal.kind == "system":
            return await self._system_call(instance, method, path, params=params, body=body)
        return await self._gateway.call(principal, instance, method, path, params=params, json=body)

    async def _system_call(
        self,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None,
        body: Any,  # noqa: ANN401
    ) -> GatewayResponse:
        """Work the control plane does on its own (drafts pulled from a repository on push), not as a person."""
        try:
            payload = await self._instances.system_call(instance, method, path, params=params, json=body)
        except AgentOSError as exc:
            return GatewayResponse(exc.status or 502, _decoded(exc.body))
        return GatewayResponse(200, payload)

    async def json(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        body: Any = None,  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        """The decoded body of a successful call; AgentOS errors become problems the person can act on."""
        response = await self.call(principal, instance, method, path, params=params, body=body)
        raise_for(instance, response)
        return response.body

    async def pages(
        self,
        principal: Principal,
        instance: Instance,
        path: str,
        params: Mapping[str, str | int] | None = None,
    ) -> list[dict[str, Any]]:
        """Every item of a paginated AgentOS list."""
        items: list[dict[str, Any]] = []
        page = 1
        while page <= MAX_PAGES:
            body = await self.json(
                principal, instance, "GET", path, params={**(params or {}), "page": page, "limit": PAGE_LIMIT}
            )
            items.extend(page_items(body))
            if page >= total_pages(body):
                break
            page += 1
        return items

    async def system_pages(
        self, instance: Instance, path: str, params: Mapping[str, str | int] | None = None
    ) -> list[dict[str, Any]]:
        """Like :meth:`pages`, as the control plane (for the used-by index, which no single person owns)."""
        items: list[dict[str, Any]] = []
        page = 1
        while page <= MAX_PAGES:
            query = {key: str(value) for key, value in {**(params or {}), "page": page, "limit": PAGE_LIMIT}.items()}
            body = await self._instances.system_call(instance, "GET", path, params=query)
            items.extend(page_items(body))
            if page >= total_pages(body):
                break
            page += 1
        return items

    async def system_json(self, instance: Instance, path: str, params: Mapping[str, str] | None = None) -> Any:  # noqa: ANN401
        return await self._instances.system_call(instance, "GET", path, params=params)

    async def bridge(self, instance: Instance) -> frozenset[str]:
        """Bridge endpoints the instance advertises (``"POST /agnostic/v1/…"``); empty without the bridge."""
        key = f"studio:bridge:{instance.id}"
        cached = await self._store.get(key)
        if cached is not None:
            return frozenset(cast("list[str]", orjson.loads(cached)))
        try:
            body = await self._instances.system_call(instance, "GET", "/agnostic/v1/capabilities")
        except AgentOSError as exc:
            endpoints: list[str] = []
            ttl = BRIDGE_TTL if exc.status == NOT_FOUND else RETRY_TTL
        else:
            raw = (
                cast("list[Any]", cast("dict[str, Any]", body).get("endpoints") or []) if isinstance(body, dict) else []
            )
            endpoints = sorted(str(item) for item in raw)
            ttl = BRIDGE_TTL
        await self._store.set(key, orjson.dumps(endpoints), ttl=ttl)
        return frozenset(endpoints)

    async def refresh_coding_agents(self, instance: Instance) -> None:
        """Ask the bridge to pick up published coding agents now. Best effort: a failure is logged, never raised."""
        try:
            if BRIDGE_CODING_REFRESH not in await self.bridge(instance):
                return
            _ = await self._instances.system_call(instance, "POST", BRIDGE_CODING_REFRESH.split(" ", 1)[1])
        except Exception as exc:  # noqa: BLE001  (the publish already succeeded)
            log.warning("studio.coding_refresh_failed", instance_id=instance.id, error=str(exc)[:200])

    async def cached(self, key: str) -> Any:  # noqa: ANN401
        raw = await self._store.get(key)
        return orjson.loads(raw) if raw is not None else None

    async def cache(self, key: str, value: Any, ttl: float) -> None:  # noqa: ANN401
        await self._store.set(key, orjson.dumps(value), ttl=ttl)

    async def forget(self, key: str) -> None:
        await self._store.delete(key)


def _decoded(body: str | None) -> object:
    if not body:
        return None
    try:
        return orjson.loads(body)
    except orjson.JSONDecodeError:
        return body


def raise_for(instance: Instance, response: GatewayResponse) -> None:
    if response.ok:
        return
    message = f"{instance.display_name}: {detail(response)}"
    if response.status == NOT_FOUND:
        raise NotFoundError(message)
    if response.status == FORBIDDEN:
        raise ForbiddenError(message)
    if response.status == CONFLICT:
        raise ConflictError(message)
    if response.status == UNPROCESSABLE:
        raise ValidationFailedError(message)
    raise InstanceCallError(message, extra={"upstream_status": response.status})
