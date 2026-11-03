"""Use cases of the access module: roles, scopes, bindings, "what can I do here?" and explain."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from agnostic_access.application.evaluator import AccessEvaluator
from agnostic_access.application.ports import BindingRepository, CatalogRepository, RoleRepository
from agnostic_access.domain.effective import EffectiveAccess, Explanation
from agnostic_access.domain.roles import BINDING_ID_PREFIX, BUILT_IN_ROLES, AccessRole, Binding
from agnostic_access.domain.scopes import ADMIN_SCOPE, ScopeSpec, compress
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_org.facade import InitialBinding, OrgFacade

READ = "org:roles:read"
WRITE = "org:roles:write"
PRIVILEGED_GRANT = "access.privileged_grant"
"""Domain event: a binding grants ``agent_os:admin`` or a privileged control-plane scope."""


@dataclass(frozen=True, slots=True)
class AccessContext:
    evaluator: AccessEvaluator
    roles: RoleRepository
    bindings: BindingRepository
    org: OrgFacade
    identity: IdentityFacade
    instances: InstancesFacade
    authorizer: Authorizer
    audit: AuditLog
    store: EphemeralStore
    events: DomainEvents


class _UseCase:
    def __init__(self, context: AccessContext) -> None:
        self.c = context

    async def _instance(self, ref: str) -> Instance:
        instance = await self.c.instances.get(ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {ref!r}.")
        return instance

    async def role(self, role_id: str) -> AccessRole:
        role = next((role for role in await self.c.evaluator.roles() if role.id in {role_id, f"rol_{role_id}"}), None)
        if role is None:
            raise ValidationFailedError(f"There is no access role {role_id!r}.")
        return role


@dataclass(frozen=True, slots=True)
class RoleView:
    role: AccessRole
    people: int


class ListRoles(_UseCase):
    async def __call__(self, principal: Principal) -> list[RoleView]:
        _ = await self.c.authorizer.require(principal, READ)
        bindings = await self.c.bindings.list()
        return [
            RoleView(role, len({b.principal_id for b in bindings if b.role_id == role.id}))
            for role in await self.c.evaluator.roles()
        ]


class ListScopes(_UseCase):
    async def __call__(self, principal: Principal) -> list[ScopeSpec]:
        _ = await self.c.authorizer.require(principal, READ)
        return self.c.evaluator.catalog.specs()


class ListBindings(_UseCase):
    async def __call__(
        self, principal: Principal, *, principal_id: str | None, instance_ref: str | None
    ) -> list[Binding]:
        if principal_id != principal.id:
            _ = await self.c.authorizer.require(principal, READ)
        instance_id = (await self._instance(instance_ref)).id if instance_ref else None
        return await self.c.bindings.list(principal_id=principal_id, instance_id=instance_id)


@dataclass(frozen=True, slots=True)
class NewBinding:
    user_id: str
    instance_ref: str | None
    role_id: str | None
    scopes: tuple[str, ...] = ()
    expires_at: datetime | None = None
    reason: str | None = None


class CreateBinding(_UseCase):
    async def __call__(self, principal: Principal, request: NewBinding) -> Binding:
        _ = await self.c.authorizer.require(principal, WRITE)
        binding = await self.build(request, created_by=principal.id)
        existing = await self.c.bindings.list(principal_id=request.user_id, instance_id=binding.instance_id)
        if any(b.instance_id == binding.instance_id and b.role_id == binding.role_id and b.role_id for b in existing):
            raise ConflictError("That person already has this role there.")
        await self.c.bindings.add(binding)
        await self.audit_binding(principal, "bindings.create", binding)
        await self.c.bindings.commit()
        await bump_access_generation(self.c.store)
        await self.announce_privileged(principal, binding)
        return binding

    async def announce_privileged(self, principal: Principal, binding: Binding) -> None:
        role = await self.role(binding.role_id) if binding.role_id else None
        granted: set[str] = set(binding.scopes) | (set(role.scopes()) if role else set())
        privileged = sorted(
            spec.scope
            for spec in self.c.evaluator.catalog.specs()
            if spec.scope in granted
            and (spec.scope == ADMIN_SCOPE or (spec.privileged and spec.source == "control_plane"))
        )
        if not privileged:
            return
        await self.c.events.publish(
            PRIVILEGED_GRANT,
            {
                "binding_id": binding.id,
                "user_id": binding.principal_id,
                "instance_id": binding.instance_id,
                "role_name": role.name if role else None,
                "scopes": privileged,
                "granted_by": principal.id,
                "granted_by_name": principal.display_name,
                "expires_at": binding.expires_at.isoformat() if binding.expires_at else None,
            },
        )

    async def build(self, request: NewBinding, *, created_by: str) -> Binding:
        member = await self.c.org.member(request.user_id)
        if member is None:
            raise ValidationFailedError(f"{request.user_id} isn't a member of the org.")
        if request.role_id is None and not request.scopes:
            raise ValidationFailedError("A binding needs a role or at least one scope.")
        instance = await self._instance(request.instance_ref) if request.instance_ref else None
        role = await self.role(request.role_id) if request.role_id else None
        if role is not None and instance is not None and not role.bindable_on(instance.id):
            raise ValidationFailedError(f"{role.name} can't be bound on {instance.display_name}.")
        unknown = [scope for scope in request.scopes if not self.c.evaluator.catalog.known(scope)]
        if unknown:
            raise ValidationFailedError(f"Unknown scopes: {', '.join(unknown)}.")
        if request.expires_at is not None and request.expires_at <= utcnow():
            raise ValidationFailedError("The expiry must be in the future.")
        return Binding(
            id=new_id(BINDING_ID_PREFIX),
            principal_kind="user",
            principal_id=request.user_id,
            instance_id=instance.id if instance else None,
            role_id=role.id if role else None,
            scopes=tuple(sorted(set(request.scopes))),
            expires_at=request.expires_at,
            reason=request.reason,
            created_by=created_by,
            created_at=utcnow(),
        )

    async def audit_binding(self, principal: Principal, action: str, binding: Binding) -> None:
        user = await self.c.identity.get_user(binding.principal_id)
        instance = await self.c.instances.get(binding.instance_id) if binding.instance_id else None
        role = await self.role(binding.role_id) if binding.role_id else None
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="binding",
                resource_id=binding.id,
                resource_display=f"{user.display_name if user else binding.principal_id} on "
                + (instance.display_name if instance else "all instances"),
                instance_id=binding.instance_id,
                fields={
                    "person": user.display_name if user else binding.principal_id,
                    "grant": role.name if role else ", ".join(binding.scopes),
                    "where": instance.display_name if instance else "all instances",
                },
                diff={"role_id": binding.role_id, "scopes": list(binding.scopes)},
            )
        )


class DeleteBinding(CreateBinding):
    async def __call__(self, principal: Principal, binding_id: str) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        _ = await self.c.authorizer.require(principal, WRITE)
        binding = await self.c.bindings.get(binding_id)
        if binding is None:
            raise NotFoundError(f"Binding {binding_id} doesn't exist.")
        await self.c.bindings.delete(binding_id)
        await self.audit_binding(principal, "bindings.delete", binding)
        await self.c.bindings.commit()
        await bump_access_generation(self.c.store)


@dataclass(frozen=True, slots=True)
class MyAccess:
    instance: Instance | None
    access: EffectiveAccess
    token_scopes: list[str]


class GetMyAccess(_UseCase):
    """``/me/access?instance=``: what the signed-in person may do there (drives ``useCan`` and ``PermissionGate``)."""

    async def __call__(self, principal: Principal, instance_ref: str | None) -> MyAccess:
        instance = await self._instance(instance_ref) if instance_ref else None
        access = await self.c.evaluator.access(principal.id, instance.id if instance else None)
        return MyAccess(instance=instance, access=access, token_scopes=compress(access.runtime_scopes()))


class Explain(_UseCase):
    async def __call__(
        self, principal: Principal, *, user_id: str, scope: str, instance_ref: str | None, action: str | None
    ) -> Explanation:
        if user_id != principal.id:
            _ = await self.c.authorizer.require(principal, READ)
        user = await self.c.identity.get_user(user_id)
        if user is None:
            raise NotFoundError(f"There is no person {user_id}.")
        subject = Principal(kind="user", id=user.id, display_name=user.display_name, email=user.email)
        instance = await self._instance(instance_ref) if instance_ref else None
        return await self.c.evaluator.explain(
            subject, scope, instance, action_label=action, others=await self.c.instances.list()
        )


class SyncCatalog:
    """At start-up: write the scope catalog and built-in roles to their tables (for listing and P06 editing)."""

    def __init__(self, catalog: CatalogRepository, roles: RoleRepository, evaluator: AccessEvaluator) -> None:
        self._catalog = catalog
        self._roles = roles
        self._evaluator = evaluator

    async def __call__(self) -> None:
        await self._catalog.sync(self._evaluator.catalog.specs())
        await self._roles.sync_built_ins(BUILT_IN_ROLES)


class InvitationBindings:
    """Org's ``InitialBindingsApplier``: bindings carried by invitations."""

    def __init__(self, create: CreateBinding, bindings: BindingRepository, store: EphemeralStore) -> None:
        self._create = create
        self._bindings = bindings
        self._store = store

    async def validate(self, bindings: Sequence[InitialBinding]) -> None:
        for binding in bindings:
            if binding.instance_id is not None and await self._create.c.instances.get(binding.instance_id) is None:
                raise ValidationFailedError(f"There is no instance {binding.instance_id!r}.")
            _ = await self._create.role(binding.role_id)

    async def apply(
        self, user_id: str, bindings: Sequence[InitialBinding], *, expires_at: datetime | None, granted_by: str
    ) -> None:
        for item in bindings:
            binding = await self._create.build(
                NewBinding(
                    user_id=user_id,
                    instance_ref=item.instance_id,
                    role_id=item.role_id,
                    expires_at=expires_at if expires_at and expires_at > utcnow() else None,
                    reason="invitation",
                ),
                created_by=granted_by,
            )
            await self._bindings.add(binding)
            inviter = await self._create.c.identity.get_user(granted_by)
            actor = Principal(kind="user", id=granted_by, display_name=inviter.display_name if inviter else granted_by)
            await self._create.audit_binding(actor, "bindings.create", binding)
        if bindings:
            await bump_access_generation(self._store)
