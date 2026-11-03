"""The only import surface other modules may use: effective scopes, explanations, and service-account grants."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol

from agnostic_access.application.evaluator import AccessEvaluator
from agnostic_access.application.ports import BindingRepository
from agnostic_access.application.use_cases import CreateBinding, NewBinding
from agnostic_access.domain.effective import EffectiveAccess, Explanation, Grant
from agnostic_access.domain.roles import AccessRole, Binding, PrincipalKind
from agnostic_access.domain.scopes import ADMIN_SCOPE, compress, satisfies, split
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Principal
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation

__all__ = [
    "ADMIN_SCOPE",
    "AccessFacade",
    "AccessFacadeImpl",
    "AccessRole",
    "Binding",
    "EffectiveAccess",
    "Explanation",
    "Grant",
    "PrincipalKind",
    "compress",
    "satisfies",
    "split",
]


class AccessFacade(Protocol):
    async def access(self, user_id: str, instance_id: str | None) -> EffectiveAccess: ...
    async def access_for(self, kind: PrincipalKind, principal_id: str, instance_id: str | None) -> EffectiveAccess:
        """A person's or a service account's effective access (``kind`` "user" or "service_account")."""
        ...

    async def explain(
        self, principal: Principal, scope: str, instance: Instance | None, *, action_label: str | None
    ) -> Explanation: ...
    def is_control_plane(self, scope: str) -> bool: ...
    def is_privileged(self, scope: str) -> bool:
        """Write/delete scopes, ``agent_os:admin`` and ``service_accounts:*`` (they need a confirmation)."""
        ...

    def known_scope(self, scope: str) -> bool: ...
    async def holders(
        self, instance_id: str | None, *, scope: str | None = None, role_ids: Iterable[str] = ()
    ) -> list[str]:
        """User ids of active members holding ``scope`` (or one of ``role_ids``) on the instance."""
        ...

    async def role_names(self) -> dict[str, str]:
        """Access role id → name (built-in and custom)."""
        ...

    async def role(self, role_id: str) -> AccessRole | None: ...
    async def bindings_of(self, kind: PrincipalKind, principal_id: str) -> list[Binding]: ...
    async def bind_service_account(
        self,
        principal: Principal,
        service_account_id: str,
        *,
        instance_id: str | None,
        role_id: str | None,
        scopes: Sequence[str],
        expires_at: datetime | None,
    ) -> Binding:
        """Bind a service account (audited; joins the caller's transaction). The caller checks who may."""
        ...

    async def unbind_principal(self, kind: PrincipalKind, principal_id: str) -> int:
        """Remove every binding of a principal without auditing each one (the caller audits the cause)."""
        ...


class AccessFacadeImpl:
    def __init__(
        self,
        evaluator: AccessEvaluator,
        bindings: BindingRepository,
        create: CreateBinding,
        store: EphemeralStore,
    ) -> None:
        self._evaluator = evaluator
        self._bindings = bindings
        self._create = create
        self._store = store

    async def access(self, user_id: str, instance_id: str | None) -> EffectiveAccess:
        return await self._evaluator.access(user_id, instance_id)

    async def access_for(self, kind: PrincipalKind, principal_id: str, instance_id: str | None) -> EffectiveAccess:
        return await self._evaluator.access_for(kind, principal_id, instance_id)

    async def explain(
        self, principal: Principal, scope: str, instance: Instance | None, *, action_label: str | None
    ) -> Explanation:
        return await self._evaluator.explain(principal, scope, instance, action_label=action_label)

    def is_control_plane(self, scope: str) -> bool:
        return self._evaluator.catalog.is_control_plane(scope)

    def is_privileged(self, scope: str) -> bool:
        resource, _, action = split(scope)
        return scope == ADMIN_SCOPE or resource == "service_accounts" or action in {"write", "delete"}

    def known_scope(self, scope: str) -> bool:
        return self._evaluator.catalog.known(scope)

    async def holders(
        self, instance_id: str | None, *, scope: str | None = None, role_ids: Iterable[str] = ()
    ) -> list[str]:
        return await self._evaluator.holders(instance_id, scope=scope, role_ids=role_ids)

    async def role_names(self) -> dict[str, str]:
        return {role.id: role.name for role in await self._evaluator.roles()}

    async def role(self, role_id: str) -> AccessRole | None:
        return next((role for role in await self._evaluator.roles() if role.id in {role_id, f"rol_{role_id}"}), None)

    async def bindings_of(self, kind: PrincipalKind, principal_id: str) -> list[Binding]:
        return await self._bindings.for_principals([(kind, principal_id)])

    async def bind_service_account(
        self,
        principal: Principal,
        service_account_id: str,
        *,
        instance_id: str | None,
        role_id: str | None,
        scopes: Sequence[str],
        expires_at: datetime | None,
    ) -> Binding:
        binding = await self._create.build(
            NewBinding(
                user_id=service_account_id,
                principal_kind="service_account",
                instance_ref=instance_id,
                role_id=role_id,
                scopes=tuple(scopes),
                expires_at=expires_at,
                reason="service account",
            ),
            created_by=principal.id,
        )
        await self._bindings.add(binding)
        await bump_access_generation(self._store)
        return binding

    async def unbind_principal(self, kind: PrincipalKind, principal_id: str) -> int:
        bindings = await self._bindings.for_principals([(kind, principal_id)])
        for binding in bindings:
            await self._bindings.delete(binding.id)
        if bindings:
            await bump_access_generation(self._store)
        return len(bindings)
