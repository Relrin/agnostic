"""HTTP routes: ``/api/v1/auth/*`` (sign-in, step-up, admin), ``/api/v1/me`` and ``/api/v1/me/mfa``."""

# No `from __future__ import annotations`: dishka wraps endpoints and FastAPI resolves annotations here.

from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from agnostic_audit.facade import actor_of
from agnostic_identity.api.admin_schemas import (
    AuthPolicyOut,
    AuthPolicyUpdate,
    ProviderCreate,
    ProviderOut,
    ProviderUpdate,
)
from agnostic_identity.api.schemas import (
    AuthOptions,
    EnrolledOut,
    LoginChallengeRequest,
    LoginMfaRequest,
    LoginRequest,
    MeOut,
    MeUpdate,
    MfaOut,
    MfaRequired,
    MfaSignedIn,
    PasswordResetConfirm,
    PasswordResetRequest,
    RecoveryCodesOut,
    SessionOut,
    SignedIn,
    SignInProviderOut,
    StepUpOut,
    StepUpRequest,
    TotpConfirm,
    TotpSetupOut,
    WebAuthnVerify,
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
from agnostic_identity.application.admin import (
    CreateLoginProvider,
    DeleteLoginProvider,
    GetAuthPolicy,
    GetLoginProvider,
    ListLoginProviders,
    ProviderSpMetadata,
    UpdateAuthPolicy,
    UpdateLoginProvider,
)
from agnostic_identity.application.mfa import (
    ConfirmTotp,
    GetMyMfa,
    RegenerateRecoveryCodes,
    RemoveFactor,
    SetupTotp,
    VerifyWebAuthnRegistration,
    WebAuthnRegistrationOptions,
)
from agnostic_identity.application.policy import AuthPolicies
from agnostic_identity.application.ports import SessionStore, SignInClients
from agnostic_identity.application.signin import (
    CompleteMfaLogin,
    CompleteSamlSso,
    CompleteSso,
    Login,
    LoginOutcome,
    LoginTotpSetup,
    LoginWebAuthnOptions,
    Logout,
    SignInPolicy,
    StartSso,
)
from agnostic_identity.application.stepup import GetStepUp, StepUp, StepUpWebAuthnOptions
from agnostic_identity.domain.policy import MfaPolicy
from agnostic_identity.domain.providers import SsoError
from agnostic_identity.facade import SessionCookies
from agnostic_kernel.auth import Authentication, Principal

auth_router = APIRouter(route_class=DishkaRoute)
admin_router = APIRouter(route_class=DishkaRoute)
me_router = APIRouter(route_class=DishkaRoute)
mfa_router = APIRouter(route_class=DishkaRoute)

MAX_ACS_BODY = 1024 * 1024
SAML_METADATA = "application/samlmetadata+xml"


@auth_router.get("/providers", summary="How people can sign in: password and/or SSO providers")
async def sign_in_options(
    policy: FromDishka[SignInPolicy], clients: FromDishka[SignInClients], policies: FromDishka[AuthPolicies]
) -> AuthOptions:
    return AuthOptions(
        local_login=policy.local_login,
        sso_enforced=(await policies.current()).enforce_sso,
        providers=[
            SignInProviderOut(id=config.id, display_name=config.display_name, preset=config.preset.value)
            for config in await clients.all()
        ],
    )


async def _signed_in(outcome: LoginOutcome, response: Response, get_me: GetMe, cookies: SessionCookies) -> MfaSignedIn:
    issued = outcome.issued
    assert issued is not None
    cookies.set(response, issued)
    user = outcome.user
    principal = Principal(kind="user", id=user.id, display_name=user.display_name, email=user.email)
    view = await get_me(principal, issued.session.method)
    return MfaSignedIn(user=MeOut.from_view(view), csrf_token=issued.csrf_token, recovery_codes=outcome.recovery_codes)


@auth_router.post(
    "/login",
    summary="Sign in with email and password",
    description=(
        "Returns the signed-in person, or `mfa_required: true` with a `challenge` when a second factor is needed "
        "(answer it at `POST /auth/login/mfa`). With SSO enforced only the break-glass Owner may use a password "
        "(others get `sso_required`)."
    ),
)
async def login(
    body: LoginRequest,
    response: Response,
    use_case: FromDishka[Login],
    get_me: FromDishka[GetMe],
    cookies: FromDishka[SessionCookies],
) -> SignedIn | MfaRequired:
    outcome = await use_case(body.email, body.password)
    if outcome.mfa is not None:
        pending = outcome.mfa
        return MfaRequired(
            challenge=pending.challenge,
            methods=list(pending.methods),  # pyright: ignore[reportArgumentType]
            enroll=pending.enroll,
        )
    signed_in = await _signed_in(outcome, response, get_me, cookies)
    return SignedIn(user=signed_in.user, csrf_token=signed_in.csrf_token)


@auth_router.post("/login/mfa", summary="Finish signing in with a second factor (or enroll one)")
async def login_mfa(
    body: LoginMfaRequest,
    response: Response,
    use_case: FromDishka[CompleteMfaLogin],
    get_me: FromDishka[GetMe],
    cookies: FromDishka[SessionCookies],
) -> MfaSignedIn:
    outcome = await use_case(
        body.challenge, code=body.code, recovery_code=body.recovery_code, webauthn=body.webauthn, label=body.label
    )
    return await _signed_in(outcome, response, get_me, cookies)


@auth_router.post("/login/mfa/totp/setup", summary="While signing in: set up an authenticator app (when required)")
async def login_totp_setup(body: LoginChallengeRequest, use_case: FromDishka[LoginTotpSetup]) -> TotpSetupOut:
    secret, uri = await use_case(body.challenge)
    return TotpSetupOut(secret=secret, otpauth_uri=uri)


@auth_router.post(
    "/login/mfa/webauthn/options",
    summary="While signing in: WebAuthn request options (or creation options when enrolling)",
)
async def login_webauthn_options(
    body: LoginChallengeRequest, use_case: FromDishka[LoginWebAuthnOptions]
) -> dict[str, Any]:
    return await use_case(body.challenge)


@auth_router.get("/step-up", summary="How recently you confirmed it's you, and how you can")
async def step_up_status(principal: FromDishka[Principal], use_case: FromDishka[GetStepUp]) -> StepUpOut:
    return StepUpOut.from_status(await use_case(principal))


@auth_router.post(
    "/step-up",
    summary="Confirm it's you (password, authenticator code or security key) before a sensitive change",
)
async def step_up(
    body: StepUpRequest,
    principal: FromDishka[Principal],
    use_case: FromDishka[StepUp],
    status_of: FromDishka[GetStepUp],
) -> StepUpOut:
    _ = await use_case(principal, password=body.password, code=body.code, webauthn=body.webauthn)
    return StepUpOut.from_status(await status_of(principal))


@auth_router.post("/step-up/webauthn/options", summary="WebAuthn request options for a step-up")
async def step_up_webauthn_options(
    principal: FromDishka[Principal], use_case: FromDishka[StepUpWebAuthnOptions]
) -> dict[str, Any]:
    return await use_case(principal)


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


@auth_router.post(
    "/sso/{provider}/acs",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
    summary="SAML assertion consumer service: the IdP posts SAMLResponse and RelayState here",
)
async def sso_acs(
    provider: str,
    request: Request,
    use_case: FromDishka[CompleteSamlSso],
    cookies: FromDishka[SessionCookies],
) -> RedirectResponse:
    body = await request.body()
    if len(body) > MAX_ACS_BODY:
        return _login_error("saml_invalid", status.HTTP_303_SEE_OTHER)
    form = parse_qs(body.decode("utf-8", errors="replace"), max_num_fields=20)
    saml_response = (form.get("SAMLResponse") or [""])[0]
    relay_state = (form.get("RelayState") or [""])[0]
    if not saml_response or not relay_state:
        return _login_error("saml_invalid", status.HTTP_303_SEE_OTHER)
    try:
        _user, issued, next_path = await use_case(provider, saml_response, relay_state)
    except SsoError as exc:
        return _login_error(exc.code, status.HTTP_303_SEE_OTHER)
    response = RedirectResponse(next_path, status_code=status.HTTP_303_SEE_OTHER)
    cookies.set(response, issued)
    return response


@auth_router.get(
    "/sso/{provider}/metadata",
    response_class=Response,
    responses={200: {"content": {SAML_METADATA: {}}}},
    summary="This installation's SAML service-provider metadata for an enabled SAML provider (public)",
)
async def sso_metadata(provider: str, use_case: FromDishka[ProviderSpMetadata]) -> Response:
    return Response(await use_case(None, provider), media_type=SAML_METADATA)


def _login_error(code: str, status_code: int = status.HTTP_302_FOUND) -> RedirectResponse:
    return RedirectResponse(f"/login?{urlencode({'error': code})}", status_code=status_code)


# ---------------------------------------------------------------------- /auth/admin (settings:write)


@admin_router.get("/providers", summary="Sign-in providers: from settings (read-only) and managed here")
async def list_providers(
    principal: FromDishka[Principal], use_case: FromDishka[ListLoginProviders]
) -> list[ProviderOut]:
    return [ProviderOut.from_view(view) for view in await use_case(principal)]


@admin_router.post(
    "/providers",
    status_code=status.HTTP_201_CREATED,
    summary="Add an OIDC / OAuth 2 or SAML provider (needs a recent sign-in or step-up)",
)
async def create_provider(
    body: ProviderCreate, principal: FromDishka[Principal], use_case: FromDishka[CreateLoginProvider]
) -> ProviderOut:
    view = await use_case(principal, body.id, body.values(), metadata_xml=body.metadata_xml)
    return ProviderOut.from_view(view)


@admin_router.get("/providers/{provider_id}", summary="One sign-in provider")
async def get_provider(
    provider_id: str, principal: FromDishka[Principal], use_case: FromDishka[GetLoginProvider]
) -> ProviderOut:
    return ProviderOut.from_view(await use_case(principal, provider_id))


@admin_router.patch("/providers/{provider_id}", summary="Change a provider (needs a recent sign-in or step-up)")
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    principal: FromDishka[Principal],
    use_case: FromDishka[UpdateLoginProvider],
) -> ProviderOut:
    view = await use_case(
        principal,
        provider_id,
        body.changes(),
        metadata_xml=body.metadata_xml,
        refresh_metadata=body.refresh_metadata,
    )
    return ProviderOut.from_view(view)


@admin_router.delete(
    "/providers/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a provider and its account links (needs a recent sign-in or step-up)",
)
async def delete_provider(
    provider_id: str, principal: FromDishka[Principal], use_case: FromDishka[DeleteLoginProvider]
) -> None:
    await use_case(principal, provider_id)


@admin_router.get(
    "/providers/{provider_id}/saml-metadata",
    response_class=Response,
    responses={200: {"content": {SAML_METADATA: {}}}},
    summary="SAML service-provider metadata to import at the IdP",
)
async def provider_saml_metadata(
    provider_id: str, principal: FromDishka[Principal], use_case: FromDishka[ProviderSpMetadata]
) -> Response:
    return Response(
        await use_case(principal, provider_id),
        media_type=SAML_METADATA,
        headers={"Content-Disposition": f'attachment; filename="agnostic-{provider_id}-sp-metadata.xml"'},
    )


@admin_router.get("/policy", summary="The org's authentication policy")
async def get_policy(principal: FromDishka[Principal], use_case: FromDishka[GetAuthPolicy]) -> AuthPolicyOut:
    return AuthPolicyOut.from_view(await use_case(principal))


@admin_router.put(
    "/policy",
    summary="Change the authentication policy: enforce SSO, break-glass Owner, session lifetimes, MFA",
)
async def update_policy(
    body: AuthPolicyUpdate, principal: FromDishka[Principal], use_case: FromDishka[UpdateAuthPolicy]
) -> AuthPolicyOut:
    view = await use_case(
        principal,
        enforce_sso=body.enforce_sso,
        break_glass_user_id=body.break_glass_user_id,
        session_idle_minutes=body.session_idle_minutes,
        session_absolute_hours=body.session_absolute_hours,
        mfa_policy=MfaPolicy(body.mfa_policy),
    )
    return AuthPolicyOut.from_view(view)


# ---------------------------------------------------------------------- /me


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


# ---------------------------------------------------------------------- /me/mfa


@mfa_router.get("", summary="Your second factors and the org's MFA policy")
async def get_my_mfa(principal: FromDishka[Principal], use_case: FromDishka[GetMyMfa]) -> MfaOut:
    return MfaOut.from_status(await use_case(principal))


@mfa_router.post("/totp/setup", summary="Start setting up an authenticator app (pending until confirmed)")
async def setup_totp(principal: FromDishka[Principal], use_case: FromDishka[SetupTotp]) -> TotpSetupOut:
    secret, uri = await use_case(principal)
    return TotpSetupOut(secret=secret, otpauth_uri=uri)


@mfa_router.post("/totp/confirm", summary="Confirm the authenticator app with a code from it")
async def confirm_totp(
    body: TotpConfirm, principal: FromDishka[Principal], use_case: FromDishka[ConfirmTotp]
) -> EnrolledOut:
    return EnrolledOut.from_domain(await use_case(principal, body.code, body.label))


@mfa_router.post("/webauthn/options", summary="WebAuthn creation options for a new security key or passkey")
async def webauthn_options(
    principal: FromDishka[Principal], use_case: FromDishka[WebAuthnRegistrationOptions]
) -> dict[str, Any]:
    return await use_case(principal)


@mfa_router.post("/webauthn/verify", summary="Register the security key or passkey")
async def webauthn_verify(
    body: WebAuthnVerify, principal: FromDishka[Principal], use_case: FromDishka[VerifyWebAuthnRegistration]
) -> EnrolledOut:
    return EnrolledOut.from_domain(await use_case(principal, body.credential, body.label))


@mfa_router.post(
    "/recovery-codes", summary="Replace your recovery codes (shown once; needs a recent sign-in or step-up)"
)
async def regenerate_recovery_codes(
    principal: FromDishka[Principal], use_case: FromDishka[RegenerateRecoveryCodes]
) -> RecoveryCodesOut:
    return RecoveryCodesOut(recovery_codes=await use_case(principal))


@mfa_router.delete(
    "/{factor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a second factor (needs a recent sign-in or step-up)",
)
async def remove_factor(factor_id: str, principal: FromDishka[Principal], use_case: FromDishka[RemoveFactor]) -> None:
    await use_case(principal, factor_id)
