"""Effective scopes with a short cache, the kernel ``Authorizer``, and explanations.

Effective access is cached per (principal, instance) for 60 s under the current access generation; anything
that changes access (bindings, roles, group membership) bumps the generation
(``agnostic_kernel.ephemeral.bump_access_generation``), so changes apply on the next request.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import datetime

import orjson

from agnostic_access.application.ports import BindingRepository, RoleRepository
from agnostic_access.domain.effective import EffectiveAccess, Explanation, Grant, compute_access, explain
from agnostic_access.domain.roles import BUILT_IN_ROLES, AccessRole, PrincipalKind
from agnostic_access.domain.scopes import AGENTOS_SCOPES, CONTROL_PLANE_EXTRA, ScopeSpec, split
from agnostic_directory.facade import DirectoryFacade
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Decision, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, access_generation
from agnostic_kernel.errors import ScopeMissingError
from agnostic_kernel.modules import LoadedModules
from agnostic_org.facade import OrgFacade
from agnostic_settings.facade import OrgSettingsReader

CACHE_TTL = 60.0


class ScopeCatalog:
    """AgentOS 3.1 scopes plus every control-plane scope the enabled modules declare."""

    def __init__(self, modules: LoadedModules) -> None:
        declared = {decl.name: decl.description for module in modules.enabled for decl in module.scopes()}
        for name, description in CONTROL_PLANE_EXTRA:
            declared.setdefault(name, description)
        agentos_names = {spec.scope for spec in AGENTOS_SCOPES}
        self._control_plane = frozenset(name for name in declared if name not in agentos_names)
        self._specs: list[ScopeSpec] = [*AGENTOS_SCOPES]
        for name in sorted(self._control_plane):
            family, _, action = name.rpartition(":")
            self._specs.append(
                ScopeSpec(
                    scope=name,
                    family=family,
                    action=action,
                    source="control_plane",
                    description=declared[name],
                    privileged=action in {"write", "delete", "manage", "rotate", "operate", "promote", "override"},
                )
            )

    def is_control_plane(self, scope: str) -> bool:
        return scope in self._control_plane

    def control_plane_scopes(self) -> frozenset[str]:
        return self._control_plane

    def specs(self) -> list[ScopeSpec]:
        return list(self._specs)

    def spec(self, scope: str) -> ScopeSpec | None:
        return next((spec for spec in self._specs if spec.scope == scope), None)

    def cell(self, scope: str) -> bool:
        """A role-matrix cell (``resource:action``) the catalog knows, AgentOS or control-plane."""
        return scope in self._control_plane or any(spec.scope == scope for spec in AGENTOS_SCOPES)

    def known(self, scope: str) -> bool:
        """Catalogued as-is, or a per-component form (``agents:<id>:run``) of a catalogued scope."""
        if scope in self._control_plane or any(spec.scope == scope for spec in AGENTOS_SCOPES):
            return True
        resource, component, action = split(scope)
        return component is not None and any(spec.scope == f"{resource}:{action}" for spec in AGENTOS_SCOPES)


def _grant_dict(grant: Grant) -> dict[str, object]:
    data = asdict(grant)
    data["expires_at"] = grant.expires_at.isoformat() if grant.expires_at else None
    return data


def _dump(access: EffectiveAccess) -> bytes:
    return orjson.dumps(
        {
            "user_id": access.user_id,
            "principal_kind": access.principal_kind,
            "org_role": access.org_role,
            "instance_id": access.instance_id,
            "implicit_full": access.implicit_full,
            "grants": [_grant_dict(grant) for grant in access.grants],
        }
    )


def _load(raw: bytes, control_plane: frozenset[str]) -> EffectiveAccess:
    data = orjson.loads(raw)
    grants = tuple(
        Grant(
            scope=item["scope"],
            source=item["source"],
            role_id=item["role_id"],
            role_name=item["role_name"],
            binding_id=item["binding_id"],
            instance_id=item["instance_id"],
            expires_at=datetime.fromisoformat(item["expires_at"]) if item["expires_at"] else None,
            via_group_id=item.get("via_group_id"),
            via_group_name=item.get("via_group_name"),
        )
        for item in data["grants"]
    )
    return EffectiveAccess(
        user_id=data["user_id"],
        principal_kind=data.get("principal_kind", "user"),
        org_role=data["org_role"],
        instance_id=data["instance_id"],
        implicit_full=data["implicit_full"],
        grants=grants,
        control_plane=control_plane,
    )


class AccessEvaluator:
    def __init__(
        self,
        org: OrgFacade,
        instances: InstancesFacade,
        settings: OrgSettingsReader,
        roles: RoleRepository,
        bindings: BindingRepository,
        store: EphemeralStore,
        catalog: ScopeCatalog,
        directory: DirectoryFacade,
    ) -> None:
        self._directory = directory
        self._org = org
        self._instances = instances
        self._settings = settings
        self._roles = roles
        self._bindings = bindings
        self._store = store
        self.catalog = catalog

    async def roles(self) -> list[AccessRole]:
        # Built-ins are seeded at start-up; before that (an unmigrated database) the code copies stand in.
        return await self._roles.all() or list(BUILT_IN_ROLES)

    async def access(self, user_id: str, instance_id: str | None) -> EffectiveAccess:
        return await self.access_for("user", user_id, instance_id)

    async def access_for(self, kind: PrincipalKind, principal_id: str, instance_id: str | None) -> EffectiveAccess:
        """A person's access (own bindings, their groups', org role) or a service account's (its bindings only)."""
        key = f"scopes:{await access_generation(self._store)}:{kind}:{principal_id}:{instance_id or '-'}"
        cached = await self._store.get(key)
        if cached is not None:
            return _load(cached, self.catalog.control_plane_scopes())
        roles = {role.id: role for role in await self.roles()}
        if kind == "service_account":
            access = compute_access(
                user_id=principal_id,
                org_role=None,
                instance_id=instance_id,
                bindings=await self._bindings.for_principals([("service_account", principal_id)]),
                roles=roles,
                require_explicit_bindings=True,
                control_plane_scopes=self.catalog.control_plane_scopes(),
                now=utcnow(),
                principal_kind="service_account",
            )
        else:
            member = await self._org.member(principal_id)
            settings = await self._settings.get()
            groups = {group.id: group.name for group in await self._directory.groups_of(principal_id)} if member else {}
            principals: list[tuple[PrincipalKind, str]] = [("user", principal_id)]
            principals.extend(("group", group_id) for group_id in groups)
            access = compute_access(
                user_id=principal_id,
                org_role=member.org_role.value if member else None,
                instance_id=instance_id,
                bindings=await self._bindings.for_principals(principals) if member else [],
                roles=roles,
                require_explicit_bindings=settings.require_explicit_bindings,
                control_plane_scopes=self.catalog.control_plane_scopes(),
                now=utcnow(),
                groups=groups,
            )
        await self._store.set(key, _dump(access), ttl=CACHE_TTL)
        return access

    async def holders(
        self, instance_id: str | None, *, scope: str | None = None, role_ids: Iterable[str] = ()
    ) -> list[str]:
        """Active members who hold ``scope`` on the instance, or any of ``role_ids`` there (user ids, sorted)."""
        roles = frozenset(role_ids)
        control_plane = scope is not None and self.catalog.is_control_plane(scope)
        found: list[str] = []
        for member in await self._org.members():
            if not member.active:
                continue
            access = await self.access(member.user_id, instance_id)
            if (scope is not None and access.find(scope, control_plane=control_plane)) or any(
                grant.role_id in roles for grant in access.grants
            ):
                found.append(member.user_id)
        return sorted(found)

    async def explain(
        self,
        principal: Principal,
        scope: str,
        instance: Instance | None,
        *,
        action_label: str | None = None,
        others: Iterable[Instance] = (),
    ) -> Explanation:
        kind: PrincipalKind = "service_account" if principal.kind == "service_account" else "user"
        access = await self.access_for(kind, principal.id, instance.id if instance else None)
        elsewhere: Mapping[str, EffectiveAccess] = {
            other.display_name: await self.access_for(kind, principal.id, other.id)
            for other in others
            if instance is None or other.id != instance.id
        }
        return explain(
            scope,
            access,
            who=principal.display_name,
            instance_label=instance.display_name if instance else None,
            action_label=action_label,
            roles=await self.roles(),
            elsewhere=elsewhere,
            is_control_plane=self.catalog.is_control_plane,
        )


class AccessAuthorizer(Authorizer):
    """The kernel's ``Authorizer``: every ``require(...)`` in every module lands here."""

    def __init__(self, evaluator: AccessEvaluator, instances: InstancesFacade) -> None:
        self._evaluator = evaluator
        self._instances = instances

    async def check(self, principal: Principal, scope: str, *, instance_id: str | None = None) -> Decision:
        if principal.kind == "system":
            return Decision(allowed=True, scope=scope, instance_id=instance_id, explanation="System principal.")
        instance = await self._instances.get(instance_id) if instance_id else None
        kind: PrincipalKind = "service_account" if principal.kind == "service_account" else "user"
        access = await self._evaluator.access_for(kind, principal.id, instance.id if instance else None)
        granted = access.find(scope, control_plane=self._evaluator.catalog.is_control_plane(scope))
        if granted:
            return Decision(
                allowed=True,
                scope=scope,
                instance_id=access.instance_id,
                held_via=tuple(grant.role_name for grant in granted),
            )
        # Denied: the explanation also looks at the person's access on other instances (slower, rare).
        others = await self._instances.list() if instance is not None else []
        explanation = await self._evaluator.explain(principal, scope, instance, others=others)
        return Decision(
            allowed=explanation.allowed,
            scope=scope,
            instance_id=instance.id if instance else instance_id,
            missing_scopes=explanation.missing_scopes,
            explanation=explanation.text,
            held_via=tuple(grant.role_name for grant in explanation.granted_by),
        )

    async def require(self, principal: Principal, scope: str, *, instance_id: str | None = None) -> Decision:
        decision = await self.check(principal, scope, instance_id=instance_id)
        if not decision.allowed:
            raise ScopeMissingError(
                decision.explanation,
                extra={
                    "required_scopes": [scope],
                    "missing_scopes": list(decision.missing_scopes),
                    "explanation": decision.explanation,
                    "instance_id": decision.instance_id,
                },
            )
        return decision
