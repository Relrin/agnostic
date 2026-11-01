"""Members and their org roles; the membership directory identity asks during sign-in."""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import Admission, IdentityFacade, Membership, User
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import ConflictError, NotFoundError
from agnostic_org.application.ports import (
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


async def actor_role(members: MemberRepository, principal: Principal) -> OrgRole:
    member = await members.get(principal.id)
    if member is None or not member.active:
        raise ConflictError("You're not a member of this org.")
    return member.org_role


class ListMembers:
    def __init__(self, members: MemberRepository, identity: IdentityFacade, authorizer: Authorizer) -> None:
        self._members = members
        self._identity = identity
        self._authorizer = authorizer

    async def __call__(self, principal: Principal) -> list[MemberView]:
        _ = await self._authorizer.require(principal, READ_SCOPE)
        members = await self._members.list()
        users = {user.id: user for user in await self._identity.get_users([m.user_id for m in members])}
        views = [MemberView(m, users[m.user_id]) for m in members if m.user_id in users]
        rank = {OrgRole.OWNER: 0, OrgRole.ADMINISTRATOR: 1, OrgRole.MEMBER: 2}
        return sorted(views, key=lambda view: (rank[view.member.org_role], view.user.display_name.lower()))


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
    ) -> None:
        self._members = members
        self._invitations = invitations
        self._org = org
        self._bindings = bindings
        self._audit = audit

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
