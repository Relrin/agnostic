"""The only import surface other modules (and the ``agnostic tokens`` CLI) may use."""

from __future__ import annotations

from typing import Protocol

from agnostic_kernel.auth import Principal
from agnostic_service_accounts.application.accounts import (
    PRIVILEGED_CREATED,
    AccountView,
    Created,
    IssuedToken,
    NewServiceAccount,
    ServiceAccounts,
)
from agnostic_service_accounts.domain.accounts import TokenKind

__all__ = [
    "PRIVILEGED_CREATED",
    "AccountView",
    "Created",
    "IssuedToken",
    "NewServiceAccount",
    "ServiceAccountsFacade",
    "ServiceAccountsFacadeImpl",
    "TokenKind",
]


class ServiceAccountsFacade(Protocol):
    async def create(self, principal: Principal, request: NewServiceAccount) -> Created:
        """Create the account, its bindings and tokens; the tokens are in the result, once."""
        ...

    async def list(self, principal: Principal) -> list[AccountView]: ...
    async def revoke(self, principal: Principal, ref: str, *, token: str | None = None) -> None:
        """Revoke one token (by id or prefix), or the whole account (every token, its bindings) without one."""
        ...


class ServiceAccountsFacadeImpl:
    def __init__(self, accounts: ServiceAccounts) -> None:
        self._accounts = accounts

    async def create(self, principal: Principal, request: NewServiceAccount) -> Created:
        return await self._accounts.create(principal, request)

    async def list(self, principal: Principal) -> list[AccountView]:
        return await self._accounts.list(principal)

    async def revoke(self, principal: Principal, ref: str, *, token: str | None = None) -> None:
        if token:
            _ = await self._accounts.revoke_token(principal, ref, token)
        else:
            await self._accounts.delete(principal, ref)
