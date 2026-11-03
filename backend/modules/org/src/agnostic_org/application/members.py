"""Members and their org roles, bulk changes, the CSV export; the membership directory identity asks at sign-in."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import Admission, IdentityFacade, Membership, User
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import AppError, ConflictError, NotFoundError, ValidationFailedError
from agnostic_org.application.ports import (
    GroupDirectory,
    InitialBindingsApplier,
    InvitationRepository,
    MemberRepository,
    OrgRepository,
)
from agnostic_org.domain.org import (
    InvitationStatus,
    Member,
    OrgRole,
    OrgRuleError,
    check_removal,
    check_role_change,
    seats_left,
)

READ_SCOPE = "org:members:read"
WRITE_SCOPE = "org:members:write"


@dataclass(frozen=True, slots=True)
class MemberView:
    member: Member
    user: User
    groups: tuple[tuple[str, str], ...] = ()
    """``(group id, name)`` of the groups they are in."""


async def actor_role(members: MemberRepository, principal: Principal) -> OrgRole:
    member = await members.get(principal.id)
    if member is None or not member.active:
        raise ConflictError("You're not a member of this org.")
    return member.org_role


class ListMembers:
    def __init__(
        self, members: MemberRepository, identity: IdentityFacade, authorizer: Authorizer, groups: GroupDirectory
    ) -> None:
        self._members = members
        self._identity = identity
        self._authorizer = authorizer
        self._groups = groups

    async def __call__(self, principal: Principal) -> list[MemberView]:
        _ = await self._authorizer.require(principal, READ_SCOPE)
        members = await self._members.list()
        users = {user.id: user for user in await self._identity.get_users([m.user_id for m in members])}
        groups = await self._groups.memberships([m.user_id for m in members])
        views = [
            MemberView(m, users[m.user_id], tuple(sorted(groups.get(m.user_id, []), key=lambda g: g[1].lower())))
            for m in members
            if m.user_id in users
        ]
        rank = {OrgRole.OWNER: 0, OrgRole.ADMINISTRATOR: 1, OrgRole.MEMBER: 2}
        return sorted(views, key=lambda view: (rank[view.member.org_role], view.user.display_name.lower()))


class ExportMembers:
    """``members.csv``: who is in the org, with their org role, groups and when they were last active."""

    def __init__(self, list_members: ListMembers) -> None:
        self._list = list_members

    async def __call__(self, principal: Principal) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["email", "name", "org_role", "groups", "joined_at", "joined_via", "last_active_at"])
        for view in await self._list(principal):
            writer.writerow(
                [
                    view.user.email,
                    view.user.display_name,
                    view.member.org_role.value,
                    "; ".join(name for _, name in view.groups),
                    view.member.joined_at.isoformat(),
                    view.member.joined_via,
                    view.user.last_active_at.isoformat() if view.user.last_active_at else "",
                ]
            )
        return buffer.getvalue()


type BulkOperation = Literal["change_role", "add_to_group", "remove"]


@dataclass(frozen=True, slots=True)
class BulkOutcome:
    user_id: str
    ok: bool
    error: str | None = None


class BulkMembers:
    """Members table bulk actions: each person is changed on their own, so one refusal doesn't stop the rest."""

    def __init__(
        self,
        change_role: ChangeOrgRole,
        remove: RemoveMember,
        groups: GroupDirectory,
        members: MemberRepository,
        org: OrgRepository,
        authorizer: Authorizer,
        audit: AuditLog,
        store: EphemeralStore,
    ) -> None:
        self._change_role = change_role
        self._remove = remove
        self._groups = groups
        self._members = members
        self._org = org
        self._authorizer = authorizer
        self._audit = audit
        self._store = store

    async def __call__(
        self,
        principal: Principal,
        user_ids: Sequence[str],
        operation: BulkOperation,
        *,
        org_role: OrgRole | None = None,
        group_id: str | None = None,
    ) -> list[BulkOutcome]:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        if operation == "change_role" and org_role is None:
            raise ValidationFailedError("Pick the org role to give them.")
        if operation == "add_to_group":
            if group_id is None:
                raise ValidationFailedError("Pick the group to add them to.")
            await self._groups.validate([group_id])
        outcomes: list[BulkOutcome] = []
        for user_id in dict.fromkeys(user_ids):
            try:
                if operation == "change_role":
                    assert org_role is not None
                    _ = await self._change_role(principal, user_id, org_role)
                elif operation == "remove":
                    await self._remove(principal, user_id)
                else:
                    assert group_id is not None
                    if await self._members.get(user_id) is None:
                        raise NotFoundError(f"{user_id} isn't a member of this org.")
                    _ = await self._groups.add(user_id, [group_id])
                outcomes.append(BulkOutcome(user_id, ok=True))
            except AppError as exc:
                outcomes.append(BulkOutcome(user_id, ok=False, error=exc.detail or exc.title))
        if operation == "add_to_group":
            added = [outcome.user_id for outcome in outcomes if outcome.ok]
            _ = await self._audit.record(
                AuditEntry(
                    action="members.bulk_add_to_group",
                    actor=actor_of(principal),
                    resource_kind="group",
                    resource_id=group_id,
                    resource_display=group_id,
                    fields={"count": str(len(added))},
                    diff={"title": "Members", "lines": [{"op": "add", "text": user_id} for user_id in added]},
                )
            )
            await self._org.commit()
            await bump_access_generation(self._store)
        return outcomes


class GetMember:
    def __init__(self, members: MemberRepository, identity: IdentityFacade, authorizer: Authorizer) -> None:
        self._members = members
        self._identity = identity
        self._authorizer = authorizer

    async def __call__(self, principal: Principal, user_id: str) -> MemberView:
        if principal.id != user_id:
            _ = await self._authorizer.require(principal, READ_SCOPE)
        member = await self._members.get(user_id)
        user = await self._identity.get_user(user_id)
        if member is None or user is None or not member.active:
            raise NotFoundError(f"{user_id} isn't a member of this org.")
        return MemberView(member, user)


class ChangeOrgRole:
    def __init__(
        self,
        members: MemberRepository,
        org: OrgRepository,
        identity: IdentityFacade,
        authorizer: Authorizer,
        audit: AuditLog,
        store: EphemeralStore,
    ) -> None:
        self._members = members
        self._org = org
        self._identity = identity
        self._authorizer = authorizer
        self._audit = audit
        self._store = store

    async def __call__(self, principal: Principal, user_id: str, role: OrgRole) -> MemberView:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        target = await self._members.get(user_id)
        user = await self._identity.get_user(user_id)
        if target is None or user is None or not target.active:
            raise NotFoundError(f"{user_id} isn't a member of this org.")
        if target.org_role is role:
            return MemberView(target, user)
        try:
            check_role_change(
                actor=await actor_role(self._members, principal),
                current=target.org_role,
                new=role,
                owners=await self._members.count_active(OrgRole.OWNER),
            )
        except OrgRuleError as exc:
            raise ConflictError(str(exc)) from exc
        updated = await self._members.set_role(user_id, role)
        _ = await self._audit.record(
            AuditEntry(
                action="members.update",
                actor=actor_of(principal),
                resource_kind="member",
                resource_id=user_id,
                resource_display=user.display_name,
                fields={"before": target.org_role.value, "after": role.value},
                diff={"org_role": {"before": target.org_role.value, "after": role.value}},
            )
        )
        await self._org.commit()
        await bump_access_generation(self._store)
        return MemberView(updated, user)


class RemoveMember:
    def __init__(
        self,
        members: MemberRepository,
        org: OrgRepository,
        identity: IdentityFacade,
        authorizer: Authorizer,
        audit: AuditLog,
        store: EphemeralStore,
    ) -> None:
        self._members = members
        self._org = org
        self._identity = identity
        self._authorizer = authorizer
        self._audit = audit
        self._store = store

    async def __call__(self, principal: Principal, user_id: str) -> None:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        target = await self._members.get(user_id)
        user = await self._identity.get_user(user_id)
        if target is None or user is None or not target.active:
            raise NotFoundError(f"{user_id} isn't a member of this org.")
        try:
            check_removal(
                actor=await actor_role(self._members, principal),
                target=target.org_role,
                owners=await self._members.count_active(OrgRole.OWNER),
                self_removal=principal.id == user_id,
            )
        except OrgRuleError as exc:
            raise ConflictError(str(exc)) from exc
        await self._members.remove(user_id)
        await self._identity.revoke_sessions(user_id)
        _ = await self._audit.record(
            AuditEntry(
                action="members.remove",
                actor=actor_of(principal),
                resource_kind="member",
                resource_id=user_id,
                resource_display=user.display_name,
            )
        )
        await self._org.commit()
        await bump_access_generation(self._store)


class OrgMembershipDirectory:
    """Identity's port: who may sign in, and who may join through SSO."""

    def __init__(
        self,
        members: MemberRepository,
        invitations: InvitationRepository,
        org: OrgRepository,
        bindings: InitialBindingsApplier,
        audit: AuditLog,
        groups: GroupDirectory,
    ) -> None:
        self._members = members
        self._invitations = invitations
        self._org = org
        self._bindings = bindings
        self._audit = audit
        self._groups = groups

    async def membership(self, user_id: str) -> Membership | None:
        member = await self._members.get(user_id)
        return Membership(org_role=member.org_role.value, active=member.active) if member else None

    async def admit(self, email: str, *, jit_allowed: bool) -> Admission:
        invitation = await self._invitations.pending_for(email)
        if invitation is not None and invitation.usable(utcnow()):
            return Admission(allowed=True)
        if not jit_allowed:
            return Admission(allowed=False, reason="not_invited")
        profile = await self._org.get()
        used = await self._members.count_active() + await self._invitations.count_pending(utcnow())
        if profile is not None and seats_left(profile.seat_limit, used) == 0:
            return Admission(allowed=False, reason="seats_full")
        return Admission(allowed=True)

    async def join(self, user: User, *, via: str) -> None:
        invitation = await self._invitations.pending_for(user.email)
        if invitation is not None and invitation.usable(utcnow()):
            _ = await self._members.upsert(user.id, invitation.org_role, joined_via=via)
            await self._bindings.apply(
                user.id,
                invitation.bindings,
                expires_at=invitation.access_ends_at,
                granted_by=invitation.invited_by,
            )
            _ = await self._groups.add(user.id, invitation.group_ids)
            await self._invitations.set_status(invitation.id, InvitationStatus.ACCEPTED)
            action, fields = "invitations.accept", {"role": invitation.org_role.value}
        else:
            _ = await self._members.upsert(user.id, OrgRole.MEMBER, joined_via=via)
            action, fields = "members.join", {"via": via}
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(Principal(kind="user", id=user.id, display_name=user.display_name)),
                resource_kind="member",
                resource_id=user.id,
                resource_display=user.display_name,
                fields=fields,
            )
        )
