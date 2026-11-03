"""HTTP routes: ``/api/v1/access/*`` and ``/api/v1/me/access``."""

from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from agnostic_access.api.schemas import (
    AccessRequestIn,
    AccessRequestOut,
    BindingCreate,
    BindingOut,
    DecisionIn,
    ExplainIn,
    ExplanationOut,
    MyAccessOut,
    ReachOut,
    RoleDuplicate,
    RoleHoldersOut,
    RoleIn,
    RoleOut,
    RolePreviewOut,
    RoleUpdate,
    RoleVersionOut,
    ScopeOut,
    TemporaryGrantIn,
)
from agnostic_access.application.evaluator import ScopeCatalog
from agnostic_access.application.requests import TemporaryAccess
from agnostic_access.application.roles import RoleEditor
from agnostic_access.application.use_cases import (
    CreateBinding,
    DeleteBinding,
    Explain,
    GetMyAccess,
    ListBindings,
    ListRoles,
    ListScopes,
    NewBinding,
    structured_scope,
)
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import ValidationFailedError

router = APIRouter(route_class=DishkaRoute)
me_router = APIRouter(route_class=DishkaRoute)


@router.get("/roles", summary="Access roles (built-in and custom) with their scopes and who holds them")
async def list_roles(principal: FromDishka[Principal], use_case: FromDishka[ListRoles]) -> list[RoleOut]:
    return [RoleOut.from_view(view) for view in await use_case(principal)]


@router.post("/roles", status_code=status.HTTP_201_CREATED, summary="Create a custom access role")
async def create_role(body: RoleIn, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]) -> RoleOut:
    return RoleOut.from_role(await editor.create(principal, body.draft()))


@router.get("/roles/{role_id}", summary="One access role")
async def get_role(role_id: str, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]) -> RoleOut:
    return RoleOut.from_role(await editor.get(principal, role_id))


@router.patch(
    "/roles/{role_id}", summary="Save a role (a new version); holders get the new scopes on their next request"
)
async def update_role(
    role_id: str, body: RoleUpdate, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]
) -> RolePreviewOut:
    return RolePreviewOut.from_preview(await editor.update(principal, role_id, body.draft(), version=body.version))


@router.post("/roles/{role_id}/preview", summary="What saving this draft would change, and for whom")
async def preview_role(
    role_id: str, body: RoleIn, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]
) -> RolePreviewOut:
    return RolePreviewOut.from_preview(await editor.preview(principal, role_id, body.draft()))


@router.post("/roles/{role_id}/duplicate", status_code=status.HTTP_201_CREATED, summary="Copy a role as a custom role")
async def duplicate_role(
    role_id: str, body: RoleDuplicate, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]
) -> RoleOut:
    return RoleOut.from_role(await editor.duplicate(principal, role_id, name=body.name))


@router.post("/roles/{role_id}/reset", summary="Put a built-in role back to its defaults (a new version)")
async def reset_role(role_id: str, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]) -> RolePreviewOut:
    return RolePreviewOut.from_preview(await editor.reset(principal, role_id))


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role (409 with its bindings while it is still bound)",
)
async def delete_role(role_id: str, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]) -> None:
    await editor.delete(principal, role_id)


@router.get("/roles/{role_id}/versions", summary="Saved versions of a role, newest first")
async def role_versions(
    role_id: str, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]
) -> list[RoleVersionOut]:
    return [RoleVersionOut.from_domain(version) for version in await editor.versions(principal, role_id)]


@router.get("/roles/{role_id}/holders", summary="People, groups and service accounts holding a role")
async def role_holders(
    role_id: str, principal: FromDishka[Principal], editor: FromDishka[RoleEditor]
) -> RoleHoldersOut:
    reach, bindings = await editor.reach(principal, role_id)
    return RoleHoldersOut(
        reach=ReachOut.from_reach(reach), bindings=[BindingOut.from_domain(binding) for binding in bindings]
    )


@router.get("/scopes", summary="The scope catalog: AgentOS 3.1 and control-plane scopes")
async def list_scopes(principal: FromDishka[Principal], use_case: FromDishka[ListScopes]) -> list[ScopeOut]:
    return [ScopeOut.from_spec(spec) for spec in await use_case(principal)]


@router.get("/bindings", summary="Role bindings, optionally for one principal, kind, role or instance")
async def list_bindings(
    principal: FromDishka[Principal],
    use_case: FromDishka[ListBindings],
    principal_id: Annotated[str | None, Query(alias="principal", description="usr_…, grp_… or sac_…")] = None,
    principal_kind: Literal["user", "group", "service_account"] | None = None,
    role: Annotated[str | None, Query(description="Access role id")] = None,
    instance: Annotated[str | None, Query(description="Instance id or slug")] = None,
) -> list[BindingOut]:
    bindings = await use_case(
        principal, principal_id=principal_id, instance_ref=instance, principal_kind=principal_kind, role_id=role
    )
    return [BindingOut.from_domain(binding) for binding in bindings]


@router.post(
    "/bindings", status_code=status.HTTP_201_CREATED, summary="Give a person or group a role (or scopes) on an instance"
)
async def create_binding(
    body: BindingCreate, principal: FromDishka[Principal], use_case: FromDishka[CreateBinding]
) -> BindingOut:
    principal_id = body.principal()
    if not principal_id:
        raise ValidationFailedError("Say who gets the binding (principal_id).")
    binding = await use_case(
        principal,
        NewBinding(
            user_id=principal_id,
            principal_kind=body.principal_kind,
            instance_ref=body.instance,
            role_id=body.role_id,
            scopes=tuple(body.scopes),
            expires_at=body.expires_at,
            reason=body.reason,
        ),
    )
    return BindingOut.from_domain(binding)


@router.delete("/bindings/{binding_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a binding")
async def delete_binding(
    binding_id: str, principal: FromDishka[Principal], use_case: FromDishka[DeleteBinding]
) -> None:
    await use_case(principal, binding_id)


@router.post("/explain", summary="Why someone can or can't do something, and what would grant it")
async def explain(
    body: ExplainIn, principal: FromDishka[Principal], use_case: FromDishka[Explain], catalog: FromDishka[ScopeCatalog]
) -> ExplanationOut:
    scope = body.scope
    if scope is None:
        if not body.resource or not body.verb:
            raise ValidationFailedError("Give a scope, or a resource and a verb.")
        scope = structured_scope(body.resource, body.verb, body.component)
    explanation = await use_case(
        principal,
        user_id=body.user_id,
        scope=scope,
        instance_ref=body.instance,
        action=body.action,
        principal_kind=body.principal_kind,
        display_name=body.display_name,
    )
    return ExplanationOut.from_domain(explanation, control_plane=catalog.is_control_plane(scope))


@router.get("/requests", summary="Temporary access requests: yours, or the ones you can decide")
async def list_requests(
    principal: FromDishka[Principal],
    access: FromDishka[TemporaryAccess],
    state: Annotated[
        Literal["pending", "approved", "denied", "cancelled", "expired"] | None, Query(alias="status")
    ] = None,
    mine: bool = False,
) -> list[AccessRequestOut]:
    return [AccessRequestOut.from_view(view) for view in await access.list(principal, status=state, mine=mine)]


@router.post("/requests", status_code=status.HTTP_201_CREATED, summary="Ask for temporary access")
async def create_request(
    body: AccessRequestIn, principal: FromDishka[Principal], access: FromDishka[TemporaryAccess]
) -> AccessRequestOut:
    request = await access.request(
        principal,
        instance_ref=body.instance,
        role_id=body.role_id,
        scopes=tuple(body.scopes),
        reason=body.reason,
        duration_hours=body.duration_hours,
    )
    return AccessRequestOut.from_domain(request)


@router.post("/requests/{request_id}/approve", summary="Approve a request: creates a binding that expires")
async def approve_request(
    request_id: str, body: DecisionIn, principal: FromDishka[Principal], access: FromDishka[TemporaryAccess]
) -> AccessRequestOut:
    return AccessRequestOut.from_domain(await access.approve(principal, request_id, note=body.note))


@router.post("/requests/{request_id}/deny", summary="Deny a request")
async def deny_request(
    request_id: str, body: DecisionIn, principal: FromDishka[Principal], access: FromDishka[TemporaryAccess]
) -> AccessRequestOut:
    return AccessRequestOut.from_domain(await access.deny(principal, request_id, note=body.note))


@router.post("/requests/{request_id}/cancel", summary="Withdraw your own request")
async def cancel_request(
    request_id: str, principal: FromDishka[Principal], access: FromDishka[TemporaryAccess]
) -> AccessRequestOut:
    return AccessRequestOut.from_domain(await access.cancel(principal, request_id))


@router.post(
    "/temporary",
    status_code=status.HTTP_201_CREATED,
    summary="Grant temporary access directly (Owners, Administrators)",
)
async def grant_temporary(
    body: TemporaryGrantIn, principal: FromDishka[Principal], access: FromDishka[TemporaryAccess]
) -> BindingOut:
    binding = await access.grant_temporary(
        principal,
        NewBinding(
            user_id=body.principal_id,
            principal_kind=body.principal_kind,
            instance_ref=body.instance,
            role_id=body.role_id,
            scopes=tuple(body.scopes),
            reason=body.reason,
        ),
        duration_hours=body.duration_hours,
    )
    return BindingOut.from_domain(binding)


@me_router.get("/access", summary="Your effective access, on an instance or org-wide")
async def my_access(
    principal: FromDishka[Principal],
    use_case: FromDishka[GetMyAccess],
    instance: Annotated[str | None, Query(description="Instance id or slug")] = None,
) -> MyAccessOut:
    return MyAccessOut.from_access(await use_case(principal, instance))
