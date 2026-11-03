"""Who is calling, and may they do this.

The kernel only defines the contracts; modules provide them: ``identity`` resolves the :class:`Principal` from the
web session (:class:`PrincipalResolver`), ``access`` decides scopes (:class:`Authorizer`). Routes depend on
``FromDishka[Principal]`` (401 when nobody is signed in) and use cases call ``authorizer.require(...)`` — never
ad-hoc role checks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)
from fastapi import Request

from agnostic_kernel.errors import UnauthenticatedError

type PrincipalKind = Literal["user", "service_account", "system"]


@dataclass(frozen=True, slots=True)
class Principal:
    kind: PrincipalKind
    id: str
    display_name: str
    email: str | None = None
    session_id: str | None = None
    """The web session that authenticated the request (hashed id), if any."""
    via: str = "web"
    forwards_user_id: bool = False
    """Service accounts only: the gateway passes the caller's ``user_id`` through instead of dropping it."""


SYSTEM_PRINCIPAL = Principal(kind="system", id="system", display_name="Agnostic", via="system")


class PrincipalResolver(Protocol):
    async def resolve(self, request: Request) -> Principal | None:
        """The caller, or ``None`` when the request carries no valid credentials. Raises for invalid CSRF."""
        ...


@dataclass(frozen=True, slots=True)
class Authentication:
    principal: Principal | None


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    scope: str
    instance_id: str | None = None
    missing_scopes: Sequence[str] = ()
    explanation: str = ""
    held_via: Sequence[str] = field(default_factory=tuple[str, ...])


class Authorizer(Protocol):
    async def check(self, principal: Principal, scope: str, *, instance_id: str | None = None) -> Decision: ...

    async def require(self, principal: Principal, scope: str, *, instance_id: str | None = None) -> Decision:
        """Like :meth:`check`, but raise ``ScopeMissingError`` (403, with the explanation) when denied."""
        ...


class HttpAuthProvider(Provider):
    """Request-scoped principal for HTTP routes (the worker has no requests, so this is wired by the API only)."""

    @provide(scope=Scope.REQUEST)
    async def authentication(self, request: Request, resolver: PrincipalResolver) -> Authentication:
        return Authentication(await resolver.resolve(request))

    @provide(scope=Scope.REQUEST)
    def principal(self, authentication: Authentication) -> Principal:
        if authentication.principal is None:
            raise UnauthenticatedError("Sign in to continue.")
        return authentication.principal
