"""The only import surface other modules may use: effective scopes and explanations (the gateway's pre-check)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from agnostic_access.application.evaluator import AccessEvaluator
from agnostic_access.domain.effective import EffectiveAccess, Explanation, Grant
from agnostic_access.domain.scopes import ADMIN_SCOPE, compress, satisfies, split
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal

__all__ = [
    "ADMIN_SCOPE",
    "AccessFacade",
    "AccessFacadeImpl",
    "EffectiveAccess",
    "Explanation",
    "Grant",
    "compress",
    "satisfies",
    "split",
]


class AccessFacade(Protocol):
    async def access(self, user_id: str, instance_id: str | None) -> EffectiveAccess: ...
    async def explain(
        self, principal: Principal, scope: str, instance: Instance | None, *, action_label: str | None
    ) -> Explanation: ...
    def is_control_plane(self, scope: str) -> bool: ...
    async def holders(
        self, instance_id: str | None, *, scope: str | None = None, role_ids: Iterable[str] = ()
    ) -> list[str]:
        """User ids of active members holding ``scope`` (or one of ``role_ids``) on the instance."""
        ...

    async def role_names(self) -> dict[str, str]:
        """Access role id → name (built-in and custom)."""
        ...


class AccessFacadeImpl:
    def __init__(self, evaluator: AccessEvaluator) -> None:
        self._evaluator = evaluator

    async def access(self, user_id: str, instance_id: str | None) -> EffectiveAccess:
        return await self._evaluator.access(user_id, instance_id)

    async def explain(
        self, principal: Principal, scope: str, instance: Instance | None, *, action_label: str | None
    ) -> Explanation:
        return await self._evaluator.explain(principal, scope, instance, action_label=action_label)

    def is_control_plane(self, scope: str) -> bool:
        return self._evaluator.catalog.is_control_plane(scope)

    async def holders(
        self, instance_id: str | None, *, scope: str | None = None, role_ids: Iterable[str] = ()
    ) -> list[str]:
        return await self._evaluator.holders(instance_id, scope=scope, role_ids=role_ids)

    async def role_names(self) -> dict[str, str]:
        return {role.id: role.name for role in await self._evaluator.roles()}
