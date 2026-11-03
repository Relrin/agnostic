"""HTTP routes: ``/api/v1/service-accounts``."""

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Response, status

from agnostic_kernel.auth import Principal
from agnostic_service_accounts.api.schemas import (
    CreatedOut,
    ServiceAccountDetailOut,
    ServiceAccountIn,
    ServiceAccountOut,
    ServiceAccountPreviewOut,
    TokenIn,
    TokenIssuedOut,
)
from agnostic_service_accounts.application.accounts import ServiceAccounts

router = APIRouter(route_class=DishkaRoute)


@router.get("", summary="Service accounts: scopes, instances, who created them, last use, expiry")
async def list_accounts(
    principal: FromDishka[Principal], accounts: FromDishka[ServiceAccounts]
) -> list[ServiceAccountOut]:
    return [ServiceAccountOut.from_view(view) for view in await accounts.list(principal)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a service account, its grants and tokens (each token is returned once)",
)
async def create_account(
    body: ServiceAccountIn, principal: FromDishka[Principal], accounts: FromDishka[ServiceAccounts]
) -> CreatedOut:
    return CreatedOut.from_created(await accounts.create(principal, body.request()))


@router.post("/preview", summary="The principal, privileged scopes and CLI command of a create form, without creating")
async def preview_account(
    body: ServiceAccountIn, principal: FromDishka[Principal], accounts: FromDishka[ServiceAccounts]
) -> ServiceAccountPreviewOut:
    return ServiceAccountPreviewOut.from_preview(await accounts.preview(principal, body.request()))


@router.get("/{account}", summary="One service account (id, name or sa:<name>) with its scopes and tokens")
async def get_account(
    account: str, principal: FromDishka[Principal], accounts: FromDishka[ServiceAccounts]
) -> ServiceAccountDetailOut:
    return ServiceAccountDetailOut.from_view(await accounts.get(principal, account))


@router.delete(
    "/{account}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a service account: revoke every token (natively on each instance) and remove its grants",
)
async def delete_account(
    account: str, principal: FromDishka[Principal], accounts: FromDishka[ServiceAccounts]
) -> Response:
    await accounts.delete(principal, account)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{account}/tokens",
    status_code=status.HTTP_201_CREATED,
    summary="Issue a token, or rotate the current one (gateway: 24 h grace; native: revoke and recreate)",
)
async def issue_token(
    account: str, body: TokenIn, principal: FromDishka[Principal], accounts: FromDishka[ServiceAccounts]
) -> TokenIssuedOut:
    return TokenIssuedOut.from_issued(await accounts.issue_token(principal, account, body.kind, body.instance))


@router.delete("/{account}/tokens/{token}", summary="Revoke a token now (by id or prefix)")
async def revoke_token(
    account: str, token: str, principal: FromDishka[Principal], accounts: FromDishka[ServiceAccounts]
) -> ServiceAccountDetailOut:
    return ServiceAccountDetailOut.from_view(await accounts.revoke_token(principal, account, token))
