"""The only import surface other modules may use: effective scopes and explanations (the gateway's pre-check)."""

from __future__ import annotations

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
