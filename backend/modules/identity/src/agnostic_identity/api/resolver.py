"""The kernel's :class:`PrincipalResolver`: gateway tokens (``Authorization: Bearer``) first, then web sessions."""

from __future__ import annotations

from fastapi import Request

from agnostic_identity.application.ports import BearerPrincipalResolver
from agnostic_identity.application.sessions import ResolvePrincipal
from agnostic_identity.facade import CSRF_HEADER, SESSION_COOKIE
from agnostic_kernel.auth import Principal

BEARER = "bearer "


class SessionPrincipalResolver:
    def __init__(self, resolve: ResolvePrincipal, bearer: BearerPrincipalResolver) -> None:
        self._resolve = resolve
        self._bearer = bearer

    async def resolve(self, request: Request) -> Principal | None:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith(BEARER):
            # A bearer token is not sent by browsers on their own, so it needs no CSRF check.
            ip = request.client.host if request.client else None
            return await self._bearer.resolve(authorization[len(BEARER) :].strip(), ip=ip)
        return await self._resolve(
            request.cookies.get(SESSION_COOKIE), request.headers.get(CSRF_HEADER), request.method
        )
