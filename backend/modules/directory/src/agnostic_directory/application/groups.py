"""Use cases for groups: list, create, change, delete, and who is in them.

Every change that can move access (membership, deletion) bumps the access generation, so the next request of each
affected person is evaluated with the new groups.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_directory.application.ports import AccessRevoker, GroupRepository
from agnostic_directory.domain.groups import (
    GROUP_ID_PREFIX,
    Group,
    GroupMember,
    GroupSource,
    InvalidGroupError,
    MemberRole,
    affects,
    clean_group_name,
)
from agnostic_identity.facade import IdentityFacade, User
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_org.facade import OrgFacade

READ = "org:members:read"
WRITE = "org:members:write"


@dataclass(frozen=True, slots=True)
class GroupsContext:
    groups: GroupRepository
    identity: IdentityFacade
    org: OrgFacade
    authorizer: Authorizer
    audit: AuditLog
    store: EphemeralStore
    revoker: AccessRevoker


@dataclass(frozen=True, slots=True)
class MemberView:
    user_id: str
    display_name: str
    email: str
    role: MemberRole
    source: GroupSource


@dataclass(frozen=True, slots=True)
class GroupDetail:
    group: Group
    members: list[MemberView]


class Groups:
    def __init__(self, context: GroupsContext) -> None:
        self.c = context

    async def list(self, principal: Principal) -> list[Group]:
        _ = await self.c.authorizer.require(principal, READ)
        return await self.c.groups.list()

    async def get(self, principal: Principal, group_id: str) -> GroupDetail:
        _ = await self.c.authorizer.require(principal, READ)
        group = await self._group(group_id)
        return GroupDetail(group=group, members=await self._members(group.id))

    async def create(
        self,
        principal: Principal,
        *,
        name: str,
        description: str = "",
        member_ids: Sequence[str] = (),
        owner_ids: Sequence[str] = (),
    ) -> GroupDetail:
        _ = await self.c.authorizer.require(principal, WRITE)
        cleaned = self._name(name)
        if await self.c.groups.find_by_name(cleaned) is not None:
            raise ConflictError(f"There already is a group called {cleaned}.")
        now = utcnow()
        group = Group(
            id=new_id(GROUP_ID_PREFIX),
            name=cleaned,
            description=description.strip(),
            source="manual",
            external_id=None,
            external_name=None,
            created_at=now,
            updated_at=now,
        )
        await self.c.groups.add(group)
        people = [*dict.fromkeys([*owner_ids, *member_ids])]
        for user_id in people:
            await self._check_member(user_id)
            _ = await self.c.groups.add_member(
                GroupMember(
                    group_id=group.id,
                    user_id=user_id,
                    role="owner" if user_id in owner_ids else "member",
                    source="manual",
                    added_at=now,
                )
            )
        await self._audit(principal, "groups.create", group, fields={"count": str(len(people))})
        await self.c.groups.commit()
        await bump_access_generation(self.c.store)
        return await self.get(principal, group.id)

    async def update(
        self, principal: Principal, group_id: str, *, name: str | None = None, description: str | None = None
    ) -> GroupDetail:
        _ = await self.c.authorizer.require(principal, WRITE)
        group = await self._group(group_id)
        changes: dict[str, str] = {}
        if name is not None and self._name(name) != group.name:
            if group.synced:
                raise ValidationFailedError(f"{group.name} is synced from the IdP; rename it there.")
            other = await self.c.groups.find_by_name(self._name(name))
            if other is not None and other.id != group.id:
                raise ConflictError(f"There already is a group called {self._name(name)}.")
            changes["name"] = self._name(name)
        if description is not None and description.strip() != group.description:
            changes["description"] = description.strip()
        if not changes:
            return await self.get(principal, group_id)
        updated = await self.c.groups.update(group_id, **changes)
        await self._audit(
            principal,
            "groups.update",
            updated,
            fields={"change": ", ".join(sorted(changes))},
            diff={
                "title": "Group",
                "lines": [{"op": "change", "text": f"{key}: {value}"} for key, value in sorted(changes.items())],
                "note": None,
            },
        )
        await self.c.groups.commit()
        return await self.get(principal, group_id)

    async def delete(self, principal: Principal, group_id: str) -> None:
        _ = await self.c.authorizer.require(principal, WRITE)
        group = await self._group(group_id)
        members = await self.c.groups.members(group.id)
        removed = await self.c.revoker.revoke_principal("group", group.id, actor=principal, reason="group deleted")
        await self.c.groups.delete(group.id)
        await self._audit(
            principal,
            "groups.delete",
            group,
            fields={"count": str(len(members))},
            diff={
                "title": "Group deleted",
                "lines": [{"op": "remove", "text": f"{removed} role binding{'s' if removed != 1 else ''}"}],
                "note": affects(len(members)) + f" of {group.name}.",
            },
        )
        await self.c.groups.commit()
        await bump_access_generation(self.c.store)

    async def add_member(
        self, principal: Principal, group_id: str, user_id: str, *, role: MemberRole = "member"
    ) -> GroupDetail:
        _ = await self.c.authorizer.require(principal, WRITE)
        group = await self._group(group_id)
        if group.synced and role == "member":
            raise ValidationFailedError(f"{group.name} is synced from the IdP; add people there.")
        user = await self._check_member(user_id)
        existing = {member.user_id: member for member in await self.c.groups.members(group.id)}
        if user_id in existing and group.synced:
            # Owners of synced groups are chosen here; membership itself stays with the IdP.
            await self.c.groups.set_role(group.id, user_id, role)
        else:
            _ = await self.c.groups.add_member(
                GroupMember(group_id=group.id, user_id=user_id, role=role, source="manual", added_at=utcnow())
            )
        await self._audit(
            principal,
            "groups.members.add",
            group,
            fields={"person": user.display_name, "role": role},
            diff={"title": "Members", "lines": [{"op": "add", "text": f"{user.display_name} ({role})"}], "note": None},
        )
        await self.c.groups.commit()
        await bump_access_generation(self.c.store)
        return await self.get(principal, group_id)

    async def remove_member(self, principal: Principal, group_id: str, user_id: str) -> GroupDetail:
        _ = await self.c.authorizer.require(principal, WRITE)
        group = await self._group(group_id)
        if group.synced:
            raise ValidationFailedError(f"{group.name} is synced from the IdP; remove people there.")
        if not await self.c.groups.remove_member(group.id, user_id):
            raise NotFoundError(f"{user_id} isn't in {group.name}.")
        user = await self.c.identity.get_user(user_id)
        name = user.display_name if user else user_id
        await self._audit(
            principal,
            "groups.members.remove",
            group,
            fields={"person": name},
            diff={"title": "Members", "lines": [{"op": "remove", "text": name}], "note": None},
        )
        await self.c.groups.commit()
        await bump_access_generation(self.c.store)
        return await self.get(principal, group_id)

    async def _group(self, group_id: str) -> Group:
        group = await self.c.groups.get(group_id)
        if group is None:
            raise NotFoundError(f"There is no group {group_id}.")
        return group

    async def _members(self, group_id: str) -> list[MemberView]:
        members = await self.c.groups.members(group_id)
        users = {user.id: user for user in await self.c.identity.get_users([m.user_id for m in members])}
        views = [
            MemberView(
                user_id=member.user_id,
                display_name=users[member.user_id].display_name if member.user_id in users else member.user_id,
                email=users[member.user_id].email if member.user_id in users else "",
                role=member.role,
                source=member.source,
            )
            for member in members
        ]
        return sorted(views, key=lambda view: (view.role != "owner", view.display_name.lower()))

    async def _check_member(self, user_id: str) -> User:
        if await self.c.org.member(user_id) is None:
            raise ValidationFailedError(f"{user_id} isn't a member of the org.")
        user = await self.c.identity.get_user(user_id)
        if user is None:
            raise ValidationFailedError(f"There is no person {user_id}.")
        return user

    @staticmethod
    def _name(name: str) -> str:
        try:
            return clean_group_name(name)
        except InvalidGroupError as exc:
            raise ValidationFailedError(str(exc)) from exc

    async def _audit(
        self,
        principal: Principal,
        action: str,
        group: Group,
        *,
        fields: dict[str, str] | None = None,
        diff: dict[str, object] | None = None,
    ) -> None:
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="group",
                resource_id=group.id,
                resource_display=group.name,
                fields={"group": group.name, **(fields or {})},
                diff=diff,
                links={"group": f"/access/people?tab=groups&group={group.id}"},
            )
        )
