"""HTTP routes: ``/api/v1/access/*`` and ``/api/v1/me/access``."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, status

from agnostic_access.api.schemas import (
    BindingCreate,
    BindingOut,
    ExplainIn,
    ExplanationOut,
    MyAccessOut,
    RoleOut,
    ScopeOut,
)
from agnostic_access.application.use_cases import (
    CreateBinding,
    DeleteBinding,
    Explain,
    GetMyAccess,
    ListBindings,
    ListRoles,
    ListScopes,
    NewBinding,
)
from agnostic_kernel.auth import Principal

router = APIRouter(route_class=DishkaRoute)
me_router = APIRouter(route_class=DishkaRoute)


@router.get("/roles", summary="Access roles (built-in in this phase) with their scopes")
async def list_roles(principal: FromDishka[Principal], use_case: FromDishka[ListRoles]) -> list[RoleOut]:
    return [RoleOut.from_view(view) for view in await use_case(principal)]


@router.get("/scopes", summary="The scope catalog: AgentOS 3.1 and control-plane scopes")
async def list_scopes(principal: FromDishka[Principal], use_case: FromDishka[ListScopes]) -> list[ScopeOut]:
    return [ScopeOut.from_spec(spec) for spec in await use_case(principal)]


@router.get("/bindings", summary="Role bindings, optionally for one person or one instance")
async def list_bindings(
    principal: FromDishka[Principal],
    use_case: FromDishka[ListBindings],
    principal_id: Annotated[str | None, Query(alias="principal", description="usr_…")] = None,
    instance: Annotated[str | None, Query(description="Instance id or slug")] = None,
) -> list[BindingOut]:
    bindings = await use_case(principal, principal_id=principal_id, instance_ref=instance)
    return [BindingOut.from_domain(binding) for binding in bindings]


@router.post("/bindings", status_code=status.HTTP_201_CREATED, summary="Give someone a role (or scopes) on an instance")
async def create_binding(
    body: BindingCreate, principal: FromDishka[Principal], use_case: FromDishka[CreateBinding]
) -> BindingOut:
    binding = await use_case(
        principal,
        NewBinding(
            user_id=body.user_id,
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
async def explain(body: ExplainIn, principal: FromDishka[Principal], use_case: FromDishka[Explain]) -> ExplanationOut:
    explanation = await use_case(
        principal, user_id=body.user_id, scope=body.scope, instance_ref=body.instance, action=body.action
    )
    return ExplanationOut.from_domain(explanation)


@me_router.get("/access", summary="Your effective access, on an instance or org-wide")
async def my_access(
    principal: FromDishka[Principal],
    use_case: FromDishka[GetMyAccess],
    instance: Annotated[str | None, Query(description="Instance id or slug")] = None,
) -> MyAccessOut:
    return MyAccessOut.from_access(await use_case(principal, instance))
