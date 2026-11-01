"""HTTP routes: ``/api/v1/auth/*`` (sign-in) and ``/api/v1/me`` (the signed-in person)."""

# No `from __future__ import annotations`: dishka wraps endpoints and FastAPI resolves annotations here.

from typing import Annotated
from urllib.parse import urlencode

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response, status
from fastapi.responses import RedirectResponse

from agnostic_audit.facade import actor_of
from agnostic_identity.api.schemas import (
    AuthOptions,
    LoginRequest,
    MeOut,
    MeUpdate,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionOut,
    SignedIn,
    SignInProviderOut,
)
from agnostic_identity.application.account import (
    ConfirmPasswordReset,
    GetMe,
    ListMySessions,
    ProfileChanges,
    RequestPasswordReset,
    RevokeMySession,
    UpdateMe,
)
from agnostic_identity.application.ports import SessionStore, SignInClients
from agnostic_identity.application.signin import CompleteSso, Login, Logout, SignInPolicy, StartSso
from agnostic_identity.domain.providers import SsoError
from agnostic_identity.facade import SessionCookies
from agnostic_kernel.auth import Authentication, Principal

auth_router = APIRouter(route_class=DishkaRoute)
me_router = APIRouter(route_class=DishkaRoute)


@auth_router.get("/providers", summary="How people can sign in: password and/or SSO providers")
async def sign_in_options(policy: FromDishka[SignInPolicy], clients: FromDishka[SignInClients]) -> AuthOptions:
    return AuthOptions(
        local_login=policy.local_login,
        providers=[
            SignInProviderOut(id=config.id, display_name=config.display_name, preset=config.preset.value)
            for config in clients.all()
        ],
    )


@auth_router.post("/login", summary="Sign in with email and password")
async def login(
    body: LoginRequest,
    response: Response,
    use_case: FromDishka[Login],
    get_me: FromDishka[GetMe],
    cookies: FromDishka[SessionCookies],
) -> SignedIn:
    user, issued = await use_case(body.email, body.password)
    cookies.set(response, issued)
    principal = Principal(kind="user", id=user.id, display_name=user.display_name, email=user.email)
    view = await get_me(principal, issued.session.method)
    return SignedIn(user=MeOut.from_view(view), csrf_token=issued.csrf_token)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of this browser")
async def logout(
    response: Response,
    authentication: FromDishka[Authentication],
    use_case: FromDishka[Logout],
    cookies: FromDishka[SessionCookies],
) -> None:
    principal = authentication.principal
    if principal is not None and principal.session_id is not None:
        await use_case(actor_of(principal), principal.session_id)
    cookies.clear(response)


@auth_router.post(
    "/password/reset",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password-reset link (always accepted, so accounts can't be discovered)",
)
async def request_password_reset(body: PasswordResetRequest, use_case: FromDishka[RequestPasswordReset]) -> None:
    await use_case(body.email)


@auth_router.post(
    "/password/reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Choose a new password with a reset token; signs out every session",
)
async def confirm_password_reset(body: PasswordResetConfirm, use_case: FromDishka[ConfirmPasswordReset]) -> None:
    await use_case(body.token, body.password)


@auth_router.get(
    "/sso/{provider}/start",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    summary="Start signing in with an SSO provider (redirects to it)",
)
async def sso_start(
    provider: str,
    use_case: FromDishka[StartSso],
    next: Annotated[str | None, Query(description="Where to go after signing in (a path)")] = None,  # noqa: A002
) -> RedirectResponse:
    try:
        url = await use_case(provider, next)
    except SsoError as exc:
        return _login_error(exc.code)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@auth_router.get(
    "/sso/{provider}/callback",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    summary="Where the SSO provider sends people back (redirects into the app)",
)
async def sso_callback(
    provider: str,
    use_case: FromDishka[CompleteSso],
    cookies: FromDishka[SessionCookies],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error or not code or not state:
        return _login_error("provider_denied" if error else "provider_error")
    try:
        _user, issued, next_path = await use_case(provider, code, state)
    except SsoError as exc:
        return _login_error(exc.code)
    response = RedirectResponse(next_path, status_code=status.HTTP_302_FOUND)
    cookies.set(response, issued)
    return response


def _login_error(code: str) -> RedirectResponse:
    return RedirectResponse(f"/login?{urlencode({'error': code})}", status_code=status.HTTP_302_FOUND)


@me_router.get("", summary="The signed-in person: profile, org role, preferences")
async def get_me(
    principal: FromDishka[Principal], store: FromDishka[SessionStore], use_case: FromDishka[GetMe]
) -> MeOut:
    session = await store.load(principal.session_id) if principal.session_id else None
    return MeOut.from_view(await use_case(principal, session.method if session else None))


@me_router.patch("", summary="Change your name, locale, time zone or preferences")
async def update_me(
    body: MeUpdate,
    principal: FromDishka[Principal],
    store: FromDishka[SessionStore],
    use_case: FromDishka[UpdateMe],
) -> MeOut:
    session = await store.load(principal.session_id) if principal.session_id else None
    changes = ProfileChanges(
        display_name=body.display_name, locale=body.locale, timezone=body.timezone, preferences=body.preferences
    )
    return MeOut.from_view(await use_case(principal, changes, session))


@me_router.get("/sessions", summary="Your signed-in browsers")
async def list_my_sessions(principal: FromDishka[Principal], use_case: FromDishka[ListMySessions]) -> list[SessionOut]:
    return [SessionOut.from_domain(item, principal.session_id) for item in await use_case(principal)]


@me_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out a browser")
async def revoke_my_session(
    session_id: str, principal: FromDishka[Principal], use_case: FromDishka[RevokeMySession]
) -> None:
    await use_case(principal, session_id)
