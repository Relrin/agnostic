"""Inviting people: email link with an org role and optional initial access-role bindings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import CreatedVia, IdentityFacade, IssuedSession, User, normalize_email
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.crypto import hash_token, new_token
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.mail import Email, Mailer
from agnostic_org.application.members import WRITE_SCOPE, actor_role
from agnostic_org.application.ports import (
    InitialBindingsApplier,
    InvitationRepository,
    MemberRepository,
    OrgRepository,
)
from agnostic_org.domain.org import (
    INVITATION_ID_PREFIX,
    InitialBinding,
    Invitation,
    InvitationStatus,
    OrgRole,
    OrgRuleError,
    check_invite_role,
    seats_left,
)

INVITATION_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation: Invitation
    accept_url: str
    """Shown once to the inviter too, so invitations work without SMTP (copy the link)."""


@dataclass(frozen=True, slots=True)
class InvitationPreview:
    org_name: str
    email: str
    org_role: OrgRole
    invited_by: str
    expires_at: datetime
    has_account: bool


@dataclass(frozen=True, slots=True)
class InvitationContext:
    invitations: InvitationRepository
    members: MemberRepository
    org: OrgRepository
    identity: IdentityFacade
    bindings: InitialBindingsApplier
    authorizer: Authorizer
    audit: AuditLog
    mailer: Mailer
    store: EphemeralStore
    public_url: str


class _Invitations:
    def __init__(self, context: InvitationContext) -> None:
        self._invitations = context.invitations
        self._members = context.members
        self._org = context.org
        self._identity = context.identity
        self._bindings = context.bindings
        self._authorizer = context.authorizer
        self._audit = context.audit
        self._mailer = context.mailer
        self._store = context.store
        self._public_url = context.public_url

    def _accept_url(self, token: str) -> str:
        return f"{self._public_url}/invite/{token}"

    async def _send(self, invitation: Invitation, token: str, inviter: str) -> None:
        profile = await self._org.get()
        org_name = profile.name if profile else "Agnostic"
        await self._mailer.send(
            Email(
                to=invitation.email,
                subject=f"{inviter} invited you to {org_name} on Agnostic",
                text=(
                    f"{inviter} invited you to join {org_name} as {invitation.org_role.value}.\n\n"
                    f"Accept the invitation (valid until {invitation.expires_at:%d %b %Y}):\n\n"
                    f"{self._accept_url(token)}\n"
                ),
            )
        )


class InvitePerson(_Invitations):
    async def __call__(
        self,
        principal: Principal,
        email: str,
        role: OrgRole,
        bindings: Sequence[InitialBinding],
        access_ends_at: datetime | None,
    ) -> IssuedInvitation:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        try:
            normalized = normalize_email(email)
            check_invite_role(actor=await actor_role(self._members, principal), role=role)
        except (ValueError, OrgRuleError) as exc:
            raise ValidationFailedError(str(exc)) from exc
        existing = await self._identity.find_user_by_email(normalized)
        if existing is not None:
            member = await self._members.get(existing.id)
            if member is not None and member.active:
                raise ConflictError(f"{normalized} is already a member.")
        if await self._invitations.pending_for(normalized) is not None:
            raise ConflictError(f"{normalized} already has a pending invitation. Resend it instead.")
        now = utcnow()
        profile = await self._org.get()
        used = await self._members.count_active() + await self._invitations.count_pending(now)
        if profile is not None and seats_left(profile.seat_limit, used) == 0:
            raise ConflictError(f"All {profile.seat_limit} seats are taken. Remove someone or raise the limit.")
        if access_ends_at is not None and access_ends_at <= now:
            raise ValidationFailedError("The access end date must be in the future.")
        await self._bindings.validate(bindings)

        token = new_token(32)
        invitation = Invitation(
            id=new_id(INVITATION_ID_PREFIX),
            email=normalized,
            org_role=role,
            bindings=tuple(bindings),
            access_ends_at=access_ends_at,
            invited_by=principal.id,
            expires_at=now + INVITATION_TTL,
            status=InvitationStatus.PENDING,
            created_at=now,
        )
        await self._invitations.add(invitation, hash_token(token))
        _ = await self._audit.record(
            AuditEntry(
                action="invitations.create",
                actor=actor_of(principal),
                resource_kind="invitation",
                resource_id=invitation.id,
                resource_display=normalized,
                fields={"email": normalized, "role": role.value},
                diff={"bindings": [{"role_id": b.role_id, "instance_id": b.instance_id} for b in bindings]},
            )
        )
        await self._org.commit()
        await self._send(invitation, token, principal.display_name)
        return IssuedInvitation(invitation, self._accept_url(token))


class ResendInvitation(_Invitations):
    async def __call__(self, principal: Principal, invitation_id: str) -> IssuedInvitation:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        invitation = await self._invitations.get(invitation_id)
        if invitation is None or invitation.status is not InvitationStatus.PENDING:
            raise NotFoundError(f"Invitation {invitation_id} isn't pending.")
        token = new_token(32)
        renewed = await self._invitations.renew(invitation.id, hash_token(token), utcnow() + INVITATION_TTL)
        _ = await self._audit.record(
            AuditEntry(
                action="invitations.resend",
                actor=actor_of(principal),
                resource_kind="invitation",
                resource_id=invitation.id,
                resource_display=invitation.email,
                fields={"email": invitation.email},
            )
        )
        await self._org.commit()
        await self._send(renewed, token, principal.display_name)
        return IssuedInvitation(renewed, self._accept_url(token))


class RevokeInvitation(_Invitations):
    async def __call__(self, principal: Principal, invitation_id: str) -> None:
        _ = await self._authorizer.require(principal, WRITE_SCOPE)
        invitation = await self._invitations.get(invitation_id)
        if invitation is None or invitation.status is not InvitationStatus.PENDING:
            raise NotFoundError(f"Invitation {invitation_id} isn't pending.")
        await self._invitations.set_status(invitation.id, InvitationStatus.REVOKED)
        _ = await self._audit.record(
            AuditEntry(
                action="invitations.revoke",
                actor=actor_of(principal),
                resource_kind="invitation",
                resource_id=invitation.id,
                resource_display=invitation.email,
                fields={"email": invitation.email},
            )
        )
        await self._org.commit()


class ListInvitations(_Invitations):
    async def __call__(self, principal: Principal) -> list[Invitation]:
        _ = await self._authorizer.require(principal, "org:members:read")
        return await self._invitations.list_pending()


class PreviewInvitation(_Invitations):
    async def __call__(self, token: str) -> InvitationPreview:
        invitation = await self._usable(token)
        profile = await self._org.get()
        inviter = await self._identity.get_user(invitation.invited_by)
        return InvitationPreview(
            org_name=profile.name if profile else "Agnostic",
            email=invitation.email,
            org_role=invitation.org_role,
            invited_by=inviter.display_name if inviter else "An administrator",
            expires_at=invitation.expires_at,
            has_account=await self._identity.find_user_by_email(invitation.email) is not None,
        )

    async def _usable(self, token: str) -> Invitation:
        invitation = await self._invitations.by_token(hash_token(token))
        if invitation is None or not invitation.usable(utcnow()):
            raise NotFoundError("This invitation expired, was revoked or was already used. Ask for a new one.")
        return invitation


class AcceptInvitation(PreviewInvitation):
    """Accept with a local password (people joining through SSO are matched by email at sign-in instead)."""

    async def __call__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, token: str, display_name: str | None, password: str
    ) -> tuple[User, IssuedSession]:
        invitation = await self._usable(token)
        user = await self._identity.create_local_account(invitation.email, display_name, password, CreatedVia.INVITE)
        _ = await self._members.upsert(user.id, invitation.org_role, joined_via="invite")
        await self._bindings.apply(
            user.id,
            invitation.bindings,
            expires_at=invitation.access_ends_at,
            granted_by=invitation.invited_by,
        )
        await self._invitations.set_status(invitation.id, InvitationStatus.ACCEPTED)
        _ = await self._audit.record(
            AuditEntry(
                action="invitations.accept",
                actor=actor_of(Principal(kind="user", id=user.id, display_name=user.display_name)),
                resource_kind="member",
                resource_id=user.id,
                resource_display=user.display_name,
                fields={"role": invitation.org_role.value},
            )
        )
        issued = await self._identity.issue_session(user, method="password")
        await self._org.commit()
        await bump_access_generation(self._store)
        return user, issued
