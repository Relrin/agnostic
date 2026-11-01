"""The org profile and settings, and first-run bootstrap."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import CreatedVia, IdentityFacade, IssuedSession, User
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.bootstrap import BootstrapResult, OwnerAccount
from agnostic_kernel.crypto import hash_token, new_token, tokens_equal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, NotFoundError, ValidationFailedError
from agnostic_org.application.ports import InvitationRepository, MemberRepository, OrgRepository
from agnostic_org.domain.org import OrgProfile, OrgRole, OrgRuleError, clean_org_name, slugify
from agnostic_settings.facade import OrgSettings, OrgSettingsFacade

BOOTSTRAP_TTL = timedelta(hours=24)
SYSTEM_ACTOR = Principal(kind="system", id="system", display_name="agnostic bootstrap", via="cli")


@dataclass(frozen=True, slots=True)
class OrgView:
    profile: OrgProfile
    settings: OrgSettings
    member_count: int
    pending_invitations: int
    viewer_role: OrgRole | None


@dataclass(frozen=True, slots=True)
class ProfileChanges:
    name: str | None = None
    logo_url: str | None = None
    seat_limit: int | None = None
    clear_seat_limit: bool = False
    settings: Mapping[str, Any] | None = None


class GetOrg:
    def __init__(
        self,
        org: OrgRepository,
        members: MemberRepository,
        invitations: InvitationRepository,
        settings: OrgSettingsFacade,
        authorizer: Authorizer,
    ) -> None:
        self._org = org
        self._members = members
        self._invitations = invitations
        self._settings = settings
        self._authorizer = authorizer

    async def __call__(self, principal: Principal) -> OrgView:
        _ = await self._authorizer.require(principal, "org:read")
        profile = await self._org.get()
        if profile is None:
            raise NotFoundError("The org isn't set up yet. Run `agnostic bootstrap`.")
        viewer = await self._members.get(principal.id)
        return OrgView(
            profile=profile,
            settings=await self._settings.get(),
            member_count=await self._members.count_active(),
            pending_invitations=await self._invitations.count_pending(utcnow()),
            viewer_role=viewer.org_role if viewer and viewer.active else None,
        )


class UpdateOrg:
    def __init__(
        self,
        org: OrgRepository,
        settings: OrgSettingsFacade,
        authorizer: Authorizer,
        audit: AuditLog,
        get_org: GetOrg,
    ) -> None:
        self._org = org
        self._settings = settings
        self._authorizer = authorizer
        self._audit = audit
        self._get_org = get_org

    async def __call__(self, principal: Principal, changes: ProfileChanges) -> OrgView:
        _ = await self._authorizer.require(principal, "org:write")
        profile = await self._org.get()
        if profile is None:
            raise NotFoundError("The org isn't set up yet.")
        updated = profile
        try:
            if changes.name is not None:
                name = clean_org_name(changes.name)
                updated = replace(updated, name=name, slug=slugify(name))
        except OrgRuleError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if changes.logo_url is not None:
            updated = replace(updated, logo_url=changes.logo_url or None)
        if changes.clear_seat_limit:
            updated = replace(updated, seat_limit=None)
        elif changes.seat_limit is not None:
            updated = replace(updated, seat_limit=changes.seat_limit)
        if updated != profile:
            await self._org.save(replace(updated, updated_at=utcnow()))
            diff = {
                key: {"before": getattr(profile, key), "after": getattr(updated, key)}
                for key in ("name", "logo_url", "seat_limit")
                if getattr(profile, key) != getattr(updated, key)
            }
            _ = await self._audit.record(
                AuditEntry(
                    action="org.update",
                    actor=actor_of(principal),
                    resource_kind="org",
                    resource_display=updated.name,
                    fields={"keys": ", ".join(diff)},
                    diff=diff,
                )
            )
        if changes.settings:
            _ = await self._settings.update(principal, changes.settings, commit=False)
        await self._org.commit()
        return await self._get_org(principal)


@dataclass(frozen=True, slots=True)
class OnboardingState:
    org_exists: bool
    owner_exists: bool
    org_name: str | None


class OnboardingStatus:
    def __init__(self, org: OrgRepository, members: MemberRepository) -> None:
        self._org = org
        self._members = members

    async def __call__(self) -> OnboardingState:
        profile = await self._org.get()
        return OnboardingState(
            org_exists=profile is not None,
            owner_exists=await self._members.count_active(OrgRole.OWNER) > 0,
            org_name=profile.name if profile else None,
        )


class Bootstrap:
    """``agnostic bootstrap``: create the org and either the Owner (with a password) or a one-time setup link."""

    def __init__(
        self,
        org: OrgRepository,
        members: MemberRepository,
        identity: IdentityFacade,
        audit: AuditLog,
        public_url: str,
    ) -> None:
        self._org = org
        self._members = members
        self._identity = identity
        self._audit = audit
        self._public_url = public_url

    async def bootstrap(self, org_name: str, owner: OwnerAccount | None) -> BootstrapResult:
        try:
            name = clean_org_name(org_name)
        except OrgRuleError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if await self._members.count_active(OrgRole.OWNER) > 0:
            raise ConflictError("This installation already has an Owner; sign in and invite people instead.")
        profile = await self._org.get()
        now = utcnow()
        await self._org.save(
            replace(profile, name=name, slug=slugify(name), updated_at=now)
            if profile
            else OrgProfile(
                name=name, slug=slugify(name), logo_url=None, plan_label=None, seat_limit=None, updated_at=now
            )
        )
        _ = await self._audit.record(
            AuditEntry(
                action="org.bootstrap",
                actor=actor_of(SYSTEM_ACTOR),
                resource_kind="org",
                resource_display=name,
                fields={"name": name},
                via="cli",
            )
        )
        if owner is not None:
            user = await self._identity.create_local_account(
                owner.email, owner.display_name, owner.password, CreatedVia.BOOTSTRAP
            )
            await self._make_owner(user, via="bootstrap")
            await self._org.set_bootstrap_token(None, None)
            await self._org.commit()
            return BootstrapResult(org_name=name, owner_email=user.email, setup_url=None)

        token = new_token(32)
        await self._org.set_bootstrap_token(hash_token(token), now + BOOTSTRAP_TTL)
        await self._org.commit()
        return BootstrapResult(
            org_name=name, owner_email=None, setup_url=f"{self._public_url}/onboarding?token={token}"
        )

    async def _make_owner(self, user: User, *, via: str) -> None:
        _ = await self._members.upsert(user.id, OrgRole.OWNER, joined_via=via)
        _ = await self._audit.record(
            AuditEntry(
                action="members.join",
                actor=actor_of(Principal(kind="user", id=user.id, display_name=user.display_name)),
                resource_kind="member",
                resource_id=user.id,
                resource_display=user.display_name,
                fields={"via": "first Owner"},
            )
        )


class CompleteOnboarding(Bootstrap):
    """The first-run page: the setup link's token creates the first Owner (and may rename the org)."""

    async def __call__(
        self, token: str, *, org_name: str | None, email: str, display_name: str, password: str
    ) -> tuple[User, IssuedSession]:
        saved = await self._org.bootstrap_token()
        now = utcnow()
        if saved is None or saved[1] <= now or not tokens_equal(saved[0], hash_token(token)):
            raise NotFoundError("This setup link expired or was already used. Run `agnostic bootstrap` again.")
        if await self._members.count_active(OrgRole.OWNER) > 0:
            raise ConflictError("This installation already has an Owner.")
        profile = await self._org.get()
        assert profile is not None
        if org_name:
            try:
                name = clean_org_name(org_name)
            except OrgRuleError as exc:
                raise ValidationFailedError(str(exc)) from exc
            await self._org.save(replace(profile, name=name, slug=slugify(name), updated_at=now))
        user = await self._identity.create_local_account(email, display_name, password, CreatedVia.BOOTSTRAP)
        await self._make_owner(user, via="onboarding")
        await self._org.set_bootstrap_token(None, None)
        issued = await self._identity.issue_session(user, method="password")
        await self._org.commit()
        return user, issued
