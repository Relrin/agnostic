"""Use cases of the access module: roles, scopes, bindings, "what can I do here?" and explain."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agnostic_access.application.evaluator import AccessEvaluator
from agnostic_access.application.ports import BindingRepository, CatalogRepository, RequestRepository, RoleRepository
from agnostic_access.domain.effective import EffectiveAccess, Explanation
from agnostic_access.domain.roles import BINDING_ID_PREFIX, BUILT_IN_ROLES, AccessRole, Binding, PrincipalKind
from agnostic_access.domain.scopes import ADMIN_SCOPE, PER_COMPONENT, ScopeSpec, compress
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_directory.facade import DirectoryFacade
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_org.facade import InitialBinding, OrgFacade
from agnostic_settings.facade import OrgSettingsReader

READ = "org:roles:read"
WRITE = "org:roles:write"
PRIVILEGED_GRANT = "access.privileged_grant"
"""Domain event: a binding grants ``agent_os:admin`` or a privileged control-plane scope."""


@dataclass(frozen=True, slots=True)
class AccessContext:
    evaluator: AccessEvaluator
    roles: RoleRepository
    bindings: BindingRepository
    requests: RequestRepository
    org: OrgFacade
    identity: IdentityFacade
    instances: InstancesFacade
    directory: DirectoryFacade
    settings: OrgSettingsReader
    authorizer: Authorizer
    audit: AuditLog
    store: EphemeralStore
    events: DomainEvents


class AccessUseCase:
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

    async def principal_label(self, kind: PrincipalKind, principal_id: str) -> str:
        if kind == "user":
            user = await self.c.identity.get_user(principal_id)
            return user.display_name if user else principal_id
        if kind == "group":
            group = await self.c.directory.group(principal_id)
            return f"the group {group.name}" if group else principal_id
        return principal_id


@dataclass(frozen=True, slots=True)
class RoleReach:
    """Who holds a role: people (directly or through groups), groups and service accounts."""

    people: frozenset[str]
    direct: frozenset[str]
    groups: tuple[tuple[str, str], ...]
    """``(group id, name)`` of groups bound to the role."""
    service_accounts: frozenset[str]


async def role_reach(context: AccessContext, role_id: str, bindings: Sequence[Binding] | None = None) -> RoleReach:
    bound = [b for b in (bindings if bindings is not None else await context.bindings.list()) if b.role_id == role_id]
    direct = frozenset(b.principal_id for b in bound if b.principal_kind == "user")
    group_ids = list(dict.fromkeys(b.principal_id for b in bound if b.principal_kind == "group"))
    people = set(direct)
    groups: list[tuple[str, str]] = []
    for group_id in group_ids:
        group = await context.directory.group(group_id)
        if group is None:
            continue
        groups.append((group.id, group.name))
        people.update(await context.directory.members_of(group.id))
    return RoleReach(
        people=frozenset(people),
        direct=direct,
        groups=tuple(groups),
        service_accounts=frozenset(b.principal_id for b in bound if b.principal_kind == "service_account"),
    )


@dataclass(frozen=True, slots=True)
class RoleView:
    role: AccessRole
    people: int
    groups: int = 0
    service_accounts: int = 0


class ListRoles(AccessUseCase):
    async def __call__(self, principal: Principal) -> list[RoleView]:
        _ = await self.c.authorizer.require(principal, READ)
        bindings = await self.c.bindings.list()
        views: list[RoleView] = []
        for role in await self.c.evaluator.roles():
            reach = await role_reach(self.c, role.id, bindings)
            views.append(RoleView(role, len(reach.people), len(reach.groups), len(reach.service_accounts)))
        return views


class ListScopes(AccessUseCase):
    async def __call__(self, principal: Principal) -> list[ScopeSpec]:
        _ = await self.c.authorizer.require(principal, READ)
        return self.c.evaluator.catalog.specs()


class ListBindings(AccessUseCase):
    async def __call__(
        self,
        principal: Principal,
        *,
        principal_id: str | None,
        instance_ref: str | None,
        principal_kind: PrincipalKind | None = None,
        role_id: str | None = None,
    ) -> list[Binding]:
        if principal_id != principal.id:
            _ = await self.c.authorizer.require(principal, READ)
        instance_id = (await self._instance(instance_ref)).id if instance_ref else None
        return await self.c.bindings.list(
            principal_id=principal_id, instance_id=instance_id, principal_kind=principal_kind, role_id=role_id
        )


@dataclass(frozen=True, slots=True)
class NewBinding:
    user_id: str
    """The principal's id; a person unless ``principal_kind`` says otherwise."""
    instance_ref: str | None
    role_id: str | None
    scopes: tuple[str, ...] = ()
    expires_at: datetime | None = None
    reason: str | None = None
    principal_kind: PrincipalKind = "user"


class CreateBinding(AccessUseCase):
    async def __call__(self, principal: Principal, request: NewBinding) -> Binding:
        _ = await self.c.authorizer.require(principal, WRITE)
        if request.principal_kind == "service_account":
            raise ValidationFailedError("Service account scopes are managed on the service account.")
        return await self.grant(principal, request)

    async def grant(self, principal: Principal, request: NewBinding) -> Binding:
        """Create, audit and announce a binding (the caller has checked who may)."""
        binding = await self.build(request, created_by=principal.id)
        existing = await self.c.bindings.list(principal_id=binding.principal_id, instance_id=binding.instance_id)
        if any(
            b.instance_id == binding.instance_id
            and b.principal_kind == binding.principal_kind
            and b.role_id == binding.role_id
            and (b.role_id is not None or set(b.scopes) == set(binding.scopes))
            for b in existing
        ):
            raise ConflictError("That role (or those scopes) is already bound there.")
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
                "principal_kind": binding.principal_kind,
                "principal_name": await self.principal_label(binding.principal_kind, binding.principal_id),
                "instance_id": binding.instance_id,
                "role_name": role.name if role else None,
                "scopes": privileged,
                "granted_by": principal.id,
                "granted_by_name": principal.display_name,
                "expires_at": binding.expires_at.isoformat() if binding.expires_at else None,
            },
        )

    async def build(self, request: NewBinding, *, created_by: str) -> Binding:
        if request.principal_kind == "user":
            if await self.c.org.member(request.user_id) is None:
                raise ValidationFailedError(f"{request.user_id} isn't a member of the org.")
        elif request.principal_kind == "group" and await self.c.directory.group(request.user_id) is None:
            raise ValidationFailedError(f"There is no group {request.user_id}.")
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
            principal_kind=request.principal_kind,
            principal_id=request.user_id,
            instance_id=instance.id if instance else None,
            role_id=role.id if role else None,
            scopes=tuple(sorted(set(request.scopes))),
            expires_at=request.expires_at,
            reason=request.reason,
            created_by=created_by,
            created_at=utcnow(),
        )

    async def audit_binding(
        self, principal: Principal, action: str, binding: Binding, *, note: str | None = None
    ) -> None:
        who = await self.principal_label(binding.principal_kind, binding.principal_id)
        instance = await self.c.instances.get(binding.instance_id) if binding.instance_id else None
        role = await self.role(binding.role_id) if binding.role_id else None
        grant = role.name if role else ", ".join(binding.scopes)
        if role is not None and binding.scopes:
            grant += " + " + ", ".join(binding.scopes)
        where = instance.display_name if instance else "all instances"
        lines = [{"op": "add" if action == "bindings.create" else "remove", "text": f"{grant} on {where}"}]
        if binding.expires_at is not None:
            lines.append({"op": "note", "text": f"Expires {binding.expires_at.isoformat(timespec='minutes')}"})
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="binding",
                resource_id=binding.id,
                resource_display=f"{who} on {where}",
                instance_id=binding.instance_id,
                fields={"person": who, "grant": grant, "where": where},
                diff={
                    "title": "Role binding",
                    "lines": lines,
                    "note": note or binding.reason,
                    "role_id": binding.role_id,
                    "scopes": list(binding.scopes),
                },
            )
        )


class DeleteBinding(CreateBinding):
    async def __call__(self, principal: Principal, binding_id: str) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        _ = await self.c.authorizer.require(principal, WRITE)
        binding = await self.c.bindings.get(binding_id)
        if binding is None:
            raise NotFoundError(f"Binding {binding_id} doesn't exist.")
        if binding.principal_kind == "service_account":
            raise ValidationFailedError("Service account scopes are managed on the service account.")
        await self.c.bindings.delete(binding_id)
        await self.audit_binding(principal, "bindings.delete", binding)
        await self.c.bindings.commit()
        await bump_access_generation(self.c.store)


class RevokePrincipal(CreateBinding):
    """Directory's ``AccessRevoker``: everything bound to a deleted group or a deprovisioned person goes."""

    async def revoke_principal(
        self, kind: Literal["user", "group"], principal_id: str, *, actor: Principal, reason: str
    ) -> int:
        bindings = await self.c.bindings.for_principals([(kind, principal_id)])
        for binding in bindings:
            await self.c.bindings.delete(binding.id)
            await self.audit_binding(actor, "bindings.delete", binding, note=reason)
        if bindings:
            await bump_access_generation(self.c.store)
        return len(bindings)


@dataclass(frozen=True, slots=True)
class MyAccess:
    instance: Instance | None
    access: EffectiveAccess
    token_scopes: list[str]


class GetMyAccess(AccessUseCase):
    """``/me/access?instance=``: what the signed-in person may do there (drives ``useCan`` and ``PermissionGate``)."""

    async def __call__(self, principal: Principal, instance_ref: str | None) -> MyAccess:
        instance = await self._instance(instance_ref) if instance_ref else None
        kind: PrincipalKind = "service_account" if principal.kind == "service_account" else "user"
        access = await self.c.evaluator.access_for(kind, principal.id, instance.id if instance else None)
        return MyAccess(instance=instance, access=access, token_scopes=compress(access.runtime_scopes()))


def structured_scope(resource: str, action: str, component: str | None) -> str:
    """``agents`` + ``run`` + ``billing-agent`` → ``agents:billing-agent:run``; the picker of "Check a permission"."""
    if component and resource in PER_COMPONENT:
        return f"{resource}:{component}:{action}"
    return f"{resource}:{action}"


class Explain(AccessUseCase):
    async def __call__(
        self,
        principal: Principal,
        *,
        user_id: str,
        scope: str,
        instance_ref: str | None,
        action: str | None,
        principal_kind: Literal["user", "service_account"] = "user",
        display_name: str | None = None,
    ) -> Explanation:
        if user_id != principal.id:
            _ = await self.c.authorizer.require(principal, READ)
        if principal_kind == "service_account":
            subject = Principal(kind="service_account", id=user_id, display_name=display_name or user_id)
        else:
            user = await self.c.identity.get_user(user_id)
            if user is None:
                raise NotFoundError(f"There is no person {user_id}.")
            subject = Principal(kind="user", id=user.id, display_name=user.display_name, email=user.email)
        instance = await self._instance(instance_ref) if instance_ref else None
        return await self.c.evaluator.explain(
            subject, scope, instance, action_label=action, others=await self.c.instances.list()
        )


class SyncCatalog:
    """At start-up: write the scope catalog to its table and seed built-in roles that aren't there yet."""

    def __init__(self, catalog: CatalogRepository, roles: RoleRepository, evaluator: AccessEvaluator) -> None:
        self._catalog = catalog
        self._roles = roles
        self._evaluator = evaluator

    async def __call__(self) -> None:
        await self._catalog.sync(self._evaluator.catalog.specs())
        await self._roles.seed_built_ins(BUILT_IN_ROLES)


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
