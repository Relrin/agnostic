"""Instance lookup, scope checks and AgentOS calls shared by the evals use cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import orjson

from agnostic_agentos_client import AgentOSError
from agnostic_evals.domain.model import EvalRuleError
from agnostic_gateway.facade import GatewayFacade, GatewayResponse
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError, ValidationFailedError

READ_SCOPE = "evals:read"
WRITE_SCOPE = "evals:write"
BRIDGE_EVALS = "POST /agnostic/v1/evals/run"
BRIDGE_TTL = 300.0
RETRY_TTL = 30.0
NOT_FOUND = 404
FORBIDDEN = 403


class InstanceCallError(AppError):
    status = 502
    code = "instance_error"
    title = "The instance answered with an error"


def rule(exc: EvalRuleError) -> ValidationFailedError:
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


@dataclass(frozen=True, slots=True)
class BridgeSupport:
    installed: bool
    versions: bool
    """The bridge serves version-pinned evals (draft and pinned versions, judge choice)."""
    reason: str | None


class EvalAccess:
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

    async def instance(self, principal: Principal, ref: str, scope: str) -> Instance:
        instance = await self._gateway.instance(ref)
        _ = await self._authorizer.require(principal, scope, instance_id=instance.id)
        return instance

    async def require(self, principal: Principal, scope: str, instance: Instance) -> None:
        _ = await self._authorizer.require(principal, scope, instance_id=instance.id)

    async def by_id(self, instance_id: str) -> Instance | None:
        return await self._instances.get(instance_id)

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
        return await self._gateway.call(principal, instance, method, path, params=params, json=body)

    async def json(
        self,
        principal: Principal,
        instance: Instance,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> Any:  # noqa: ANN401
        response = await self.call(principal, instance, "GET", path, params=params)
        if response.status == NOT_FOUND:
            raise NotFoundError(f"{instance.display_name}: {detail(response)}")
        if response.status == FORBIDDEN:
            raise ForbiddenError(f"{instance.display_name}: {detail(response)}")
        if not response.ok:
            raise InstanceCallError(f"{instance.display_name}: {detail(response)}")
        return response.body

    async def bridge(self, instance: Instance) -> BridgeSupport:
        """Read from the bridge's capabilities document (as the control plane), cached for five minutes."""
        key = f"evals:bridge:{instance.id}"
        cached = await self._store.get(key)
        if cached is not None:
            value = cast("dict[str, Any]", orjson.loads(cached))
            return BridgeSupport(
                installed=bool(value["installed"]), versions=bool(value["versions"]), reason=value.get("reason")
            )
        try:
            body = await self._instances.system_call(instance, "GET", "/agnostic/v1/capabilities")
        except AgentOSError as exc:
            missing = exc.status == NOT_FOUND
            reason = (
                f"agnostic-bridge isn't installed on {instance.display_name}"
                if missing
                else f"{instance.display_name} didn't answer the bridge check ({exc})"
            )
            support = BridgeSupport(
                installed=False,
                versions=False,
                reason=f"{reason}: drafts and pinned versions can't be evaluated, and the judge is the instance "
                "default.",
            )
            ttl = BRIDGE_TTL if missing else RETRY_TTL
        else:
            ttl = BRIDGE_TTL
            endpoints = (
                cast("list[Any]", cast("dict[str, Any]", body).get("endpoints") or []) if isinstance(body, dict) else []
            )
            versions = BRIDGE_EVALS in {str(item) for item in endpoints}
            support = BridgeSupport(
                installed=True,
                versions=versions,
                reason=None
                if versions
                else f"The agnostic-bridge on {instance.display_name} predates version-pinned evals; upgrade it.",
            )
        payload = {"installed": support.installed, "versions": support.versions, "reason": support.reason}
        await self._store.set(key, orjson.dumps(payload), ttl=ttl)
        return support
