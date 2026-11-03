"""Editing access roles: create, change (versioned), duplicate, delete, reset built-ins, and "what happens if I save".

A save changes what every holder's next request carries: the access generation is bumped, the scope cache and the
gateway's token cache turn over, and nothing is redeployed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from agnostic_access.application.use_cases import WRITE, AccessUseCase, RoleReach, role_reach
from agnostic_access.domain.roles import (
    BUILT_IN_BY_ID,
    ROLE_ID_PREFIX,
    AccessRole,
    Binding,
    InvalidRoleError,
    RoleDraft,
    RoleVersion,
    ScopeDiff,
    apply_draft,
    check_draft,
    compare_versions,
    role_slug,
    role_snapshot,
    scope_diff,
)
from agnostic_access.domain.scopes import split
from agnostic_audit.facade import AuditEntry, actor_of
from agnostic_kernel.auth import Principal
from agnostic_kernel.ephemeral import bump_access_generation
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError, VersionConflictError
from agnostic_kernel.ids import new_id

READ = "org:roles:read"
DELETE = "org:roles:delete"


@dataclass(frozen=True, slots=True)
class RolePreview:
    role: AccessRole
    """The role as it would be saved."""
    diff: ScopeDiff
    reach: RoleReach
    warnings: tuple[str, ...]


def _reach_sentence(reach: RoleReach) -> str:
    people = len(reach.people)
    parts = [f"{people} {'person' if people == 1 else 'people'}"]
    if reach.groups:
        names = ", ".join(name for _, name in reach.groups)
        parts.append(f"{len(reach.groups)} group{'s' if len(reach.groups) != 1 else ''} ({names})")
    if reach.service_accounts:
        count = len(reach.service_accounts)
        parts.append(f"{count} service account{'s' if count != 1 else ''}")
    return " and ".join(parts)


class RoleEditor(AccessUseCase):
    async def get(self, principal: Principal, role_id: str) -> AccessRole:
        _ = await self.c.authorizer.require(principal, READ)
        return await self._existing(role_id)

    async def versions(self, principal: Principal, role_id: str) -> list[RoleVersion]:
        _ = await self.c.authorizer.require(principal, READ)
        role = await self._existing(role_id)
        return await self.c.roles.versions(role.id)

    async def reach(self, principal: Principal, role_id: str) -> tuple[RoleReach, list[Binding]]:
        _ = await self.c.authorizer.require(principal, READ)
        role = await self._existing(role_id)
        bindings = [b for b in await self.c.bindings.list() if b.role_id == role.id]
        return await role_reach(self.c, role.id, bindings), bindings

    async def preview(self, principal: Principal, role_id: str, draft: RoleDraft) -> RolePreview:
        _ = await self.c.authorizer.require(principal, READ)
        role = await self._existing(role_id)
        after = apply_draft(role, self._check(draft))
        return RolePreview(
            role=after,
            diff=scope_diff(role.scopes(), after.scopes()),
            reach=await role_reach(self.c, role.id),
            warnings=await self._warnings(after),
        )

    async def create(self, principal: Principal, draft: RoleDraft) -> AccessRole:
        _ = await self.c.authorizer.require(principal, WRITE)
        checked = self._check(draft)
        slug = await self._free_slug(role_slug(checked.name))
        role = apply_draft(
            AccessRole(
                id=new_id(ROLE_ID_PREFIX),
                slug=slug,
                name=checked.name,
                description="",
                color=checked.color,
                kind="custom",
                permissions={},
            ),
            checked,
        )
        await self.c.roles.add(role)
        await self._version(principal, role)
        await self._audit(
            principal,
            "roles.create",
            role,
            ScopeDiff(added=tuple(sorted(role.scopes())), removed=()),
            note=f"{len(role.scopes())} token scopes.",
        )
        await self.c.roles.commit()
        return role

    async def duplicate(self, principal: Principal, role_id: str, *, name: str | None = None) -> AccessRole:
        source = await self._existing(role_id)
        draft = RoleDraft(
            name=name or f"{source.name} copy",
            description=source.description,
            color=source.color,
            permissions=source.permissions,
            run_scope=source.run_scope,
            bindable_instance_ids=source.bindable_instance_ids,
        )
        return await self.create(principal, draft)

    async def update(self, principal: Principal, role_id: str, draft: RoleDraft, *, version: int) -> RolePreview:
        _ = await self.c.authorizer.require(principal, WRITE)
        role = await self._existing(role_id)
        if role.version != version:
            raise VersionConflictError(
                f"{role.name} changed since you opened it (version {role.version}); reload to see the changes."
            )
        checked = self._check(draft)
        after = replace(apply_draft(role, checked), version=role.version + 1)
        if after.name != role.name and role.kind == "custom":
            after = replace(after, slug=await self._free_slug(role_slug(after.name), except_id=role.id))
        diff = scope_diff(role.scopes(), after.scopes())
        reach = await role_reach(self.c, role.id)
        await self.c.roles.save(after)
        await self._version(principal, after)
        note = f"{_reach_sentence(reach)} get the new scopes on their next request. No redeploy."
        await self._audit(principal, "roles.update", after, diff, note=note, before=role)
        await self.c.roles.commit()
        await bump_access_generation(self.c.store)
        return RolePreview(role=after, diff=diff, reach=reach, warnings=await self._warnings(after))

    async def reset(self, principal: Principal, role_id: str) -> RolePreview:
        role = await self._existing(role_id)
        original = BUILT_IN_BY_ID.get(role.id)
        if original is None:
            raise ValidationFailedError("Only built-in roles can be reset to their defaults.")
        draft = RoleDraft(
            name=original.name,
            description=original.description,
            color=original.color,
            permissions=original.permissions,
            run_scope=original.run_scope,
            bindable_instance_ids=original.bindable_instance_ids,
        )
        return await self.update(principal, role.id, draft, version=role.version)

    async def delete(self, principal: Principal, role_id: str) -> None:
        _ = await self.c.authorizer.require(principal, DELETE)
        role = await self._existing(role_id)
        if role.kind == "built_in":
            raise ValidationFailedError(f"{role.name} is built in; you can change it, but not delete it.")
        bindings = [b for b in await self.c.bindings.list() if b.role_id == role.id]
        if bindings:
            raise ConflictError(
                f"{role.name} is still bound {len(bindings)} time{'s' if len(bindings) != 1 else ''}; "
                "remove those bindings first.",
                extra={
                    "bindings": [
                        {
                            "id": b.id,
                            "principal_kind": b.principal_kind,
                            "principal_id": b.principal_id,
                            "principal_name": await self.principal_label(b.principal_kind, b.principal_id),
                            "instance_id": b.instance_id,
                        }
                        for b in bindings
                    ]
                },
            )
        await self.c.roles.delete(role.id)
        await self._audit(
            principal, "roles.delete", role, ScopeDiff(added=(), removed=tuple(sorted(role.scopes()))), note=None
        )
        await self.c.roles.commit()
        await bump_access_generation(self.c.store)

    async def _existing(self, role_id: str) -> AccessRole:
        role = await self.c.roles.get(role_id) or await self.c.roles.get(f"{ROLE_ID_PREFIX}_{role_id}")
        if role is None:
            raise NotFoundError(f"There is no access role {role_id!r}.")
        return role

    def _check(self, draft: RoleDraft) -> RoleDraft:
        try:
            return check_draft(draft, catalogued=self.c.evaluator.catalog.cell)
        except InvalidRoleError as exc:
            raise ValidationFailedError(str(exc)) from exc

    async def _free_slug(self, slug: str, *, except_id: str | None = None) -> str:
        candidate, counter = slug, 2
        while await self.c.roles.slug_taken(candidate, except_id=except_id):
            candidate = f"{slug}-{counter}"
            counter += 1
        return candidate

    async def _warnings(self, role: AccessRole) -> tuple[str, ...]:
        warnings: list[str] = []
        for instance in await self.c.instances.list():
            if not role.bindable_on(instance.id):
                continue
            installed = instance.agno_version
            for scope in sorted(role.scopes()):
                resource, _, action = split(scope)
                spec = self.c.evaluator.catalog.spec(f"{resource}:{action}")
                if spec is not None and not compare_versions(installed, spec.agentos_min_version):
                    warnings.append(
                        f"`{scope}` needs AgentOS {spec.agentos_min_version}; "
                        f"{instance.display_name} runs {installed}, so it will ignore it."
                    )
        return tuple(warnings)

    async def _version(self, principal: Principal, role: AccessRole) -> None:
        await self.c.roles.add_version(
            role.id,
            role.version,
            role_snapshot(role),
            changed_by=principal.id,
            changed_by_name=principal.display_name,
        )

    async def _audit(
        self,
        principal: Principal,
        action: str,
        role: AccessRole,
        diff: ScopeDiff,
        *,
        note: str | None,
        before: AccessRole | None = None,
    ) -> None:
        changes: list[str] = []
        if before is not None:
            if before.name != role.name:
                changes.append(f"renamed from {before.name}")
            if before.bindable_instance_ids != role.bindable_instance_ids:
                changes.append("instances it can be bound on")
            if before.run_scope != role.run_scope:
                changes.append("what it can run")
        summary_bits = [*(f"+{scope}" for scope in diff.added), *(f"−{scope}" for scope in diff.removed), *changes]
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="role",
                resource_id=role.id,
                resource_display=role.name,
                fields={"role": role.name, "change": ", ".join(summary_bits) or "no scope changes"},
                diff={"title": "Token scopes", "lines": diff.lines(), "note": note, "version": role.version},
                links={"role": f"/access/roles?role={role.id}"},
            )
        )
