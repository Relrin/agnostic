"""HTTP routes: ``/api/v1/org``, ``/members``, ``/invitations`` and the first-run ``/onboarding``."""

# No `from __future__ import annotations`: dishka wraps endpoints and FastAPI resolves annotations here.

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse

from agnostic_identity.facade import SessionCookies
from agnostic_kernel.auth import Principal
from agnostic_org.api.schemas import (
    BulkOutcomeOut,
    InvitationAccept,
    InvitationCreate,
    InvitationOut,
    InvitationPreviewOut,
    IssuedInvitationOut,
    Joined,
    MemberOut,
    MembersBulk,
    MemberUpdate,
    OnboardingComplete,
    OnboardingStatusOut,
    OrgOut,
    OrgUpdate,
)
from agnostic_org.application.invitations import (
    AcceptInvitation,
    InvitePerson,
    ListInvitations,
    PreviewInvitation,
    ResendInvitation,
    RevokeInvitation,
)
from agnostic_org.application.members import (
    BulkMembers,
    ChangeOrgRole,
    ExportMembers,
    GetMember,
    ListMembers,
    RemoveMember,
)
from agnostic_org.application.profile import (
    CompleteOnboarding,
    GetOrg,
    OnboardingStatus,
    ProfileChanges,
    UpdateOrg,
)
from agnostic_org.domain.org import InitialBinding, OrgRole

org_router = APIRouter(route_class=DishkaRoute)
members_router = APIRouter(route_class=DishkaRoute)
invitations_router = APIRouter(route_class=DishkaRoute)
onboarding_router = APIRouter(route_class=DishkaRoute)


@org_router.get("", summary="The org: profile, seats, settings and your org role")
async def get_org(principal: FromDishka[Principal], use_case: FromDishka[GetOrg]) -> OrgOut:
    return OrgOut.from_view(await use_case(principal))


@org_router.patch("", summary="Change the org profile or org settings")
async def update_org(body: OrgUpdate, principal: FromDishka[Principal], use_case: FromDishka[UpdateOrg]) -> OrgOut:
    changes = ProfileChanges(
        name=body.name,
        logo_url=body.logo_url,
        seat_limit=body.seat_limit,
        clear_seat_limit=body.clear_seat_limit,
        settings=body.settings.model_dump(exclude_none=True) if body.settings else None,
    )
    return OrgOut.from_view(await use_case(principal, changes))


@members_router.get("", summary="Members of the org with their org roles")
async def list_members(principal: FromDishka[Principal], use_case: FromDishka[ListMembers]) -> list[MemberOut]:
    return [MemberOut.from_view(view) for view in await use_case(principal)]


@members_router.get(
    "/export.csv",
    response_class=PlainTextResponse,
    summary="Members as CSV: email, name, org role, groups, joined, last active",
)
async def export_members(principal: FromDishka[Principal], use_case: FromDishka[ExportMembers]) -> PlainTextResponse:
    return PlainTextResponse(
        await use_case(principal),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="members.csv"'},
    )


@members_router.post("/bulk", summary="Change the org role of, add to a group, or remove several members")
async def bulk_members(
    body: MembersBulk, principal: FromDishka[Principal], use_case: FromDishka[BulkMembers]
) -> list[BulkOutcomeOut]:
    outcomes = await use_case(
        principal,
        body.user_ids,
        body.operation,
        org_role=OrgRole(body.org_role) if body.org_role else None,
        group_id=body.group_id,
    )
    return [BulkOutcomeOut(user_id=item.user_id, ok=item.ok, error=item.error) for item in outcomes]


@members_router.get("/{user_id}", summary="One member")
async def get_member(user_id: str, principal: FromDishka[Principal], use_case: FromDishka[GetMember]) -> MemberOut:
    return MemberOut.from_view(await use_case(principal, user_id))


@members_router.patch("/{user_id}", summary="Change a member's org role")
async def update_member(
    user_id: str, body: MemberUpdate, principal: FromDishka[Principal], use_case: FromDishka[ChangeOrgRole]
) -> MemberOut:
    return MemberOut.from_view(await use_case(principal, user_id, OrgRole(body.org_role)))


@members_router.delete(
    "/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove someone from the org (signs them out)"
)
async def remove_member(user_id: str, principal: FromDishka[Principal], use_case: FromDishka[RemoveMember]) -> None:
    await use_case(principal, user_id)


@invitations_router.get("", summary="Pending invitations")
async def list_invitations(
    principal: FromDishka[Principal], use_case: FromDishka[ListInvitations]
) -> list[InvitationOut]:
    return [InvitationOut.from_domain(item) for item in await use_case(principal)]


@invitations_router.post("", status_code=status.HTTP_201_CREATED, summary="Invite someone by email")
async def create_invitation(
    body: InvitationCreate, principal: FromDishka[Principal], use_case: FromDishka[InvitePerson]
) -> IssuedInvitationOut:
    issued = await use_case(
        principal,
        body.email,
        OrgRole(body.org_role),
        [InitialBinding(role_id=b.role_id, instance_id=b.instance_id) for b in body.bindings],
        body.access_ends_at,
        body.group_ids,
    )
    return IssuedInvitationOut.from_issued(issued)


@invitations_router.post("/{invitation_id}/resend", summary="Send the invitation again with a fresh link")
async def resend_invitation(
    invitation_id: str, principal: FromDishka[Principal], use_case: FromDishka[ResendInvitation]
) -> IssuedInvitationOut:
    return IssuedInvitationOut.from_issued(await use_case(principal, invitation_id))


@invitations_router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke an invitation")
async def revoke_invitation(
    invitation_id: str, principal: FromDishka[Principal], use_case: FromDishka[RevokeInvitation]
) -> None:
    await use_case(principal, invitation_id)


@invitations_router.get("/{token}/preview", summary="What an invitation link is for (no sign-in needed)")
async def preview_invitation(token: str, use_case: FromDishka[PreviewInvitation]) -> InvitationPreviewOut:
    return InvitationPreviewOut.from_preview(await use_case(token))


@invitations_router.post("/{token}/accept", summary="Accept an invitation with a password; signs you in")
async def accept_invitation(
    token: str,
    body: InvitationAccept,
    response: Response,
    use_case: FromDishka[AcceptInvitation],
    cookies: FromDishka[SessionCookies],
) -> Joined:
    user, issued = await use_case(token, body.display_name, body.password)
    cookies.set(response, issued)
    return Joined(user_id=user.id, csrf_token=issued.csrf_token)


@onboarding_router.get("/status", summary="Whether the installation still needs its first Owner")
async def onboarding_status(use_case: FromDishka[OnboardingStatus]) -> OnboardingStatusOut:
    return OnboardingStatusOut.from_state(await use_case())


@onboarding_router.post("/complete", summary="Create the first Owner with the setup link from `agnostic bootstrap`")
async def complete_onboarding(
    body: OnboardingComplete,
    response: Response,
    use_case: FromDishka[CompleteOnboarding],
    cookies: FromDishka[SessionCookies],
) -> Joined:
    user, issued = await use_case(
        body.token, org_name=body.org_name, email=body.email, display_name=body.display_name, password=body.password
    )
    cookies.set(response, issued)
    return Joined(user_id=user.id, csrf_token=issued.csrf_token)
