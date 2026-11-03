"""Who may do what with code sources, and the instance a source belongs to."""

from __future__ import annotations

from agnostic_gateway.facade import GatewayFacade
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import NotFoundError, ValidationFailedError
from agnostic_sources.domain.model import Source, SourceRuleError

SOURCES_READ = "studio:sources:read"
"""See connections and webhook deliveries."""
SOURCES_WRITE = "studio:sources:write"
"""Connect and configure sources (the repositories Studio syncs with)."""
SOURCES_DELETE = "studio:sources:delete"
COMPONENTS_READ = "components:read"
"""See sources, their changes and conflicts: everyone who sees the components."""
COMPONENTS_WRITE = "components:write"
"""Fetch, pull as drafts, commit and resolve conflicts: everyone who edits the components."""


def rule(exc: SourceRuleError) -> ValidationFailedError:
    return ValidationFailedError(str(exc))


class SourcesAccess:
    def __init__(self, gateway: GatewayFacade, instances: InstancesFacade, authorizer: Authorizer) -> None:
        self._gateway = gateway
        self._instances = instances
        self._authorizer = authorizer

    async def instance(self, principal: Principal, ref: str, scope: str) -> Instance:
        instance = await self._gateway.instance(ref)
        _ = await self._authorizer.require(principal, scope, instance_id=instance.id)
        return instance

    async def require(self, principal: Principal, scope: str, instance_id: str | None = None) -> None:
        _ = await self._authorizer.require(principal, scope, instance_id=instance_id)

    async def allowed(self, principal: Principal, scope: str, instance_id: str | None = None) -> bool:
        return (await self._authorizer.check(principal, scope, instance_id=instance_id)).allowed

    async def of(self, source: Source) -> Instance:
        """The source's instance, for work the control plane does on its own (jobs, webhooks)."""
        instance = await self._instances.get(source.instance_id)
        if instance is None:
            raise NotFoundError("The source's instance isn't connected any more.")
        return instance

    def owned(self, source: Source | None, instance: Instance) -> Source:
        if source is None or source.instance_id != instance.id:
            raise NotFoundError(f"There is no such source on {instance.display_name}.")
        return source
