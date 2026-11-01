"""The kernel's :class:`PrincipalResolver`, backed by web sessions."""

from __future__ import annotations

from fastapi import Request

from agnostic_identity.application.sessions import ResolvePrincipal
from agnostic_identity.facade import CSRF_HEADER, SESSION_COOKIE
from agnostic_kernel.auth import Principal


class SessionPrincipalResolver:
    def __init__(self, resolve: ResolvePrincipal) -> None:
        self._resolve = resolve

    async def resolve(self, request: Request) -> Principal | None:
        return await self._resolve(
            request.cookies.get(SESSION_COOKIE), request.headers.get(CSRF_HEADER), request.method
        )
