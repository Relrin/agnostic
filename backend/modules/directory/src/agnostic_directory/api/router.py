"""HTTP routes: ``/api/v1/directory`` (groups, SCIM tokens and status, mapping rules, settings, Google sync)."""

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, status

from agnostic_directory.api.schemas import (
    DirectorySettingsIn,
    DirectorySettingsOut,
    GoogleSyncIn,
    GoogleSyncOut,
    GoogleTestOut,
    GroupCreate,
    GroupDetailOut,
    GroupMemberIn,
    GroupOut,
    GroupUpdate,
    IssuedScimTokenOut,
    MappingRuleCreate,
    MappingRuleOut,
    ScimStatusOut,
    ScimTokenCreate,
)
from agnostic_directory.application.admin import DirectorySettingsAdmin, MappingRules, ScimAdmin
from agnostic_directory.application.google import GoogleSettings
from agnostic_directory.application.groups import Groups
from agnostic_kernel.auth import Principal

router = APIRouter(route_class=DishkaRoute)


@router.get("/groups", summary="Groups with their member counts and where they come from")
async def list_groups(principal: FromDishka[Principal], groups: FromDishka[Groups]) -> list[GroupOut]:
    return [GroupOut.from_domain(group) for group in await groups.list(principal)]


@router.post("/groups", status_code=status.HTTP_201_CREATED, summary="Create a manual group")
async def create_group(
    body: GroupCreate, principal: FromDishka[Principal], groups: FromDishka[Groups]
) -> GroupDetailOut:
    detail = await groups.create(
        principal,
        name=body.name,
        description=body.description,
        member_ids=body.member_ids,
        owner_ids=body.owner_ids,
    )
    return GroupDetailOut.from_detail(detail)


@router.get("/groups/{group_id}", summary="A group and its members")
async def get_group(group_id: str, principal: FromDishka[Principal], groups: FromDishka[Groups]) -> GroupDetailOut:
    return GroupDetailOut.from_detail(await groups.get(principal, group_id))


@router.patch("/groups/{group_id}", summary="Rename a group or change its description")
async def update_group(
    group_id: str, body: GroupUpdate, principal: FromDishka[Principal], groups: FromDishka[Groups]
) -> GroupDetailOut:
    return GroupDetailOut.from_detail(
        await groups.update(principal, group_id, name=body.name, description=body.description)
    )


@router.delete(
    "/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a group and its role bindings"
)
async def delete_group(group_id: str, principal: FromDishka[Principal], groups: FromDishka[Groups]) -> None:
    await groups.delete(principal, group_id)


@router.put("/groups/{group_id}/members/{user_id}", summary="Add someone to a group (or change their role in it)")
async def add_group_member(
    group_id: str,
    user_id: str,
    body: GroupMemberIn,
    principal: FromDishka[Principal],
    groups: FromDishka[Groups],
) -> GroupDetailOut:
    return GroupDetailOut.from_detail(await groups.add_member(principal, group_id, user_id, role=body.role))


@router.delete("/groups/{group_id}/members/{user_id}", summary="Remove someone from a manual group")
async def remove_group_member(
    group_id: str, user_id: str, principal: FromDishka[Principal], groups: FromDishka[Groups]
) -> GroupDetailOut:
    return GroupDetailOut.from_detail(await groups.remove_member(principal, group_id, user_id))


@router.get("/scim", summary="SCIM endpoint, last sync, counts and the tokens that still work")
async def scim_status(principal: FromDishka[Principal], admin: FromDishka[ScimAdmin]) -> ScimStatusOut:
    return ScimStatusOut.from_status(await admin.status(principal))


@router.post(
    "/scim/tokens", status_code=status.HTTP_201_CREATED, summary="Create the SCIM token (shown only in this response)"
)
async def create_scim_token(
    body: ScimTokenCreate, principal: FromDishka[Principal], admin: FromDishka[ScimAdmin]
) -> IssuedScimTokenOut:
    return IssuedScimTokenOut.from_issued(await admin.create_token(principal, body.label))


@router.post(
    "/scim/tokens/{token_id}/rotate",
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new SCIM token; the old one keeps working for 24 hours or until revoked",
)
async def rotate_scim_token(
    token_id: str, principal: FromDishka[Principal], admin: FromDishka[ScimAdmin]
) -> IssuedScimTokenOut:
    return IssuedScimTokenOut.from_issued(await admin.rotate(principal, token_id))


@router.delete("/scim/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Revoke a SCIM token")
async def revoke_scim_token(token_id: str, principal: FromDishka[Principal], admin: FromDishka[ScimAdmin]) -> None:
    await admin.revoke(principal, token_id)


@router.get("/mapping-rules", summary="IdP group → Agnostic group mapping rules")
async def list_mapping_rules(principal: FromDishka[Principal], rules: FromDishka[MappingRules]) -> list[MappingRuleOut]:
    return [MappingRuleOut.from_view(view) for view in await rules.list(principal)]


@router.post(
    "/mapping-rules",
    status_code=status.HTTP_201_CREATED,
    summary="Add the members of an IdP group to a manual group (applied at once)",
)
async def create_mapping_rule(
    body: MappingRuleCreate, principal: FromDishka[Principal], rules: FromDishka[MappingRules]
) -> MappingRuleOut:
    view = await rules.create(
        principal, source=body.source, idp_group=body.idp_group, group_id=body.group_id, provider_id=body.provider_id
    )
    return MappingRuleOut.from_view(view)


@router.delete(
    "/mapping-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a mapping rule and the memberships it made",
)
async def delete_mapping_rule(rule_id: str, principal: FromDishka[Principal], rules: FromDishka[MappingRules]) -> None:
    await rules.delete(principal, rule_id)


@router.get("/settings", summary="Directory sync settings (deprovisioning behaviour)")
async def get_directory_settings(
    principal: FromDishka[Principal], settings: FromDishka[DirectorySettingsAdmin]
) -> DirectorySettingsOut:
    return DirectorySettingsOut(deprovision=(await settings.get(principal)).deprovision)


@router.put("/settings", summary="Change the deprovisioning behaviour")
async def update_directory_settings(
    body: DirectorySettingsIn, principal: FromDishka[Principal], settings: FromDishka[DirectorySettingsAdmin]
) -> DirectorySettingsOut:
    return DirectorySettingsOut(
        deprovision=(await settings.update(principal, deprovision=body.deprovision)).deprovision
    )


@router.get("/google", summary="Google Workspace sync: config (without the key) and the last run")
async def get_google_sync(principal: FromDishka[Principal], google: FromDishka[GoogleSettings]) -> GoogleSyncOut:
    return GoogleSyncOut.from_view(await google.get(principal))


@router.put("/google", summary="Configure Google Workspace sync (omitted fields stay as they are)")
async def update_google_sync(
    body: GoogleSyncIn, principal: FromDishka[Principal], google: FromDishka[GoogleSettings]
) -> GoogleSyncOut:
    view = await google.update(
        principal,
        service_account_json=body.service_account_json,
        admin_subject=body.admin_subject,
        customer_id=body.customer_id,
        group_filter=body.group_filter,
        enabled=body.enabled,
    )
    return GoogleSyncOut.from_view(view)


@router.post("/google/test", summary="Check that the service account can read the directory")
async def test_google_sync(principal: FromDishka[Principal], google: FromDishka[GoogleSettings]) -> GoogleTestOut:
    result = await google.test(principal)
    return GoogleTestOut(ok=result.ok, detail=result.detail)


@router.post("/google/sync", summary="Run the Google Workspace sync now")
async def run_google_sync(principal: FromDishka[Principal], google: FromDishka[GoogleSettings]) -> GoogleSyncOut:
    return GoogleSyncOut.from_view(await google.sync_now(principal))
