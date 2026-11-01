"""Request and response bodies of the org module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from agnostic_org.application.invitations import InvitationPreview, IssuedInvitation
from agnostic_org.application.members import MemberView
from agnostic_org.application.profile import OnboardingState, OrgView
from agnostic_org.domain.org import Invitation

type OrgRoleName = Literal["owner", "administrator", "member"]


class OrgSettingsOut(BaseModel):
    require_explicit_bindings: bool
    audit_log_all_reads: bool


class OrgOut(BaseModel):
    name: str
    slug: str
    logo_url: str | None
    plan_label: str | None
    seat_limit: int | None
    member_count: int
    pending_invitations: int
    viewer_role: OrgRoleName | None
    settings: OrgSettingsOut
    updated_at: datetime

    @classmethod
    def from_view(cls, view: OrgView) -> OrgOut:
        profile = view.profile
        return cls(
            name=profile.name,
            slug=profile.slug,
            logo_url=profile.logo_url,
            plan_label=profile.plan_label,
            seat_limit=profile.seat_limit,
            member_count=view.member_count,
            pending_invitations=view.pending_invitations,
            viewer_role=view.viewer_role.value if view.viewer_role else None,
            settings=OrgSettingsOut(
                require_explicit_bindings=view.settings.require_explicit_bindings,
                audit_log_all_reads=view.settings.audit_log_all_reads,
            ),
            updated_at=profile.updated_at,
        )


class OrgSettingsUpdate(BaseModel):
    require_explicit_bindings: bool | None = None
    audit_log_all_reads: bool | None = None


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    logo_url: str | None = Field(default=None, max_length=2048, description="Empty string removes the logo")
    seat_limit: int | None = Field(default=None, ge=1, description="Use clear_seat_limit to remove the limit")
    clear_seat_limit: bool = False
    settings: OrgSettingsUpdate | None = None


class MemberOut(BaseModel):
    user_id: str
    email: str
    display_name: str
    avatar_seed: str
    org_role: OrgRoleName
    joined_at: datetime
    joined_via: str
    last_active_at: datetime | None

    @classmethod
    def from_view(cls, view: MemberView) -> MemberOut:
        return cls(
            user_id=view.user.id,
            email=view.user.email,
            display_name=view.user.display_name,
            avatar_seed=view.user.avatar_seed,
            org_role=view.member.org_role.value,
            joined_at=view.member.joined_at,
            joined_via=view.member.joined_via,
            last_active_at=view.user.last_active_at,
        )


class MemberUpdate(BaseModel):
    org_role: OrgRoleName


class InitialBindingIn(BaseModel):
    role_id: str
    instance_id: str | None = Field(default=None, description="null binds the role on all instances")


class InvitationCreate(BaseModel):
    email: str = Field(max_length=320)
    org_role: OrgRoleName = "member"
    bindings: list[InitialBindingIn] = Field(default_factory=list[InitialBindingIn], max_length=50)
    access_ends_at: AwareDatetime | None = None


class InitialBindingOut(BaseModel):
    role_id: str
    instance_id: str | None


class InvitationOut(BaseModel):
    id: str
    email: str
    org_role: OrgRoleName
    bindings: list[InitialBindingOut]
    access_ends_at: datetime | None
    invited_by: str
    expires_at: datetime
    status: Literal["pending", "accepted", "revoked"]
    created_at: datetime

    @classmethod
    def from_domain(cls, invitation: Invitation) -> InvitationOut:
        return cls(
            id=invitation.id,
            email=invitation.email,
            org_role=invitation.org_role.value,
            bindings=[InitialBindingOut(role_id=b.role_id, instance_id=b.instance_id) for b in invitation.bindings],
            access_ends_at=invitation.access_ends_at,
            invited_by=invitation.invited_by,
            expires_at=invitation.expires_at,
            status=invitation.status.value,
            created_at=invitation.created_at,
        )


class IssuedInvitationOut(BaseModel):
    invitation: InvitationOut
    accept_url: str = Field(description="Shown once; share it yourself when email isn't configured")

    @classmethod
    def from_issued(cls, issued: IssuedInvitation) -> IssuedInvitationOut:
        return cls(invitation=InvitationOut.from_domain(issued.invitation), accept_url=issued.accept_url)


class InvitationPreviewOut(BaseModel):
    org_name: str
    email: str
    org_role: OrgRoleName
    invited_by: str
    expires_at: datetime
    has_account: bool

    @classmethod
    def from_preview(cls, preview: InvitationPreview) -> InvitationPreviewOut:
        return cls(
            org_name=preview.org_name,
            email=preview.email,
            org_role=preview.org_role.value,
            invited_by=preview.invited_by,
            expires_at=preview.expires_at,
            has_account=preview.has_account,
        )


class InvitationAccept(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    password: str = Field(max_length=1024)


class Joined(BaseModel):
    user_id: str
    csrf_token: str


class OnboardingStatusOut(BaseModel):
    org_exists: bool
    owner_exists: bool
    org_name: str | None

    @classmethod
    def from_state(cls, state: OnboardingState) -> OnboardingStatusOut:
        return cls(org_exists=state.org_exists, owner_exists=state.owner_exists, org_name=state.org_name)


class OnboardingComplete(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    org_name: str | None = Field(default=None, max_length=80)
    email: str = Field(max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(max_length=1024)
