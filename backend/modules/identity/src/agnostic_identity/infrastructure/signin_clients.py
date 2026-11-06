"""SSO clients: OIDC (authorization code + PKCE, verified ``id_token``) and GitHub (OAuth 2 + REST profile)."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import jwt

from agnostic_identity.application.ports import LoginProviderRepository
from agnostic_identity.domain.providers import ExternalProfile, Preset, ProviderConfig, SignInProtocol, SsoError
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

DISCOVERY_TTL = 3600.0
ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA")
CLOCK_LEEWAY = 60
_CLAIMS_KEPT = ("sub", "iss", "email", "email_verified", "name", "preferred_username", "hd", "groups", "login", "id")


def _provider_error(config: ProviderConfig, detail: str) -> SsoError:
    log.warning("identity.sso_provider_error", provider=config.id, detail=detail)
    return SsoError("provider_error", f"{config.display_name} sign-in failed: {detail}")


def _truthy(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _kept(claims: Mapping[str, Any]) -> dict[str, Any]:
    return {key: claims[key] for key in _CLAIMS_KEPT if key in claims}


class OidcClient:
    def __init__(self, config: ProviderConfig, http: httpx.AsyncClient) -> None:
        assert config.issuer is not None
        self.config = config
        self._http = http
        self._discovery: tuple[float, dict[str, Any]] | None = None
        self._jwks: jwt.PyJWKSet | None = None

    async def _metadata(self) -> dict[str, Any]:
        if self._discovery and self._discovery[0] > time.monotonic():
            return self._discovery[1]
        url = f"{self.config.issuer}/.well-known/openid-configuration"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            metadata = cast("dict[str, Any]", response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise _provider_error(self.config, f"can't read {url} ({exc})") from exc
        if str(metadata.get("issuer", "")).rstrip("/") != self.config.issuer:
            raise _provider_error(self.config, f"discovery issuer {metadata.get('issuer')!r} != {self.config.issuer!r}")
        self._discovery = (time.monotonic() + DISCOVERY_TTL, metadata)
        return metadata

    async def check(self) -> str:
        """Read the discovery document (raises like a sign-in would); returns the authorization endpoint."""
        return str((await self._metadata()).get("authorization_endpoint", ""))

    async def _signing_key(self, metadata: Mapping[str, Any], kid: str | None) -> jwt.PyJWK:
        for refresh in (False, True):
            if self._jwks is None or refresh:
                try:
                    response = await self._http.get(str(metadata["jwks_uri"]))
                    response.raise_for_status()
                    self._jwks = jwt.PyJWKSet.from_dict(response.json())
                except (httpx.HTTPError, ValueError, KeyError, jwt.PyJWKSetError) as exc:
                    raise _provider_error(self.config, f"can't read the signing keys ({exc})") from exc
            for key in self._jwks.keys:
                if kid is None or key.key_id == kid:
                    return key
        raise _provider_error(self.config, f"no signing key with id {kid!r}")

    async def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:
        metadata = await self._metadata()
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            **self.config.extra_authorize_params,
        }
        return f"{metadata['authorization_endpoint']}?{urlencode(params)}"

    async def complete(self, *, redirect_uri: str, code: str, code_verifier: str, nonce: str) -> ExternalProfile:
        metadata = await self._metadata()
        tokens = await self._exchange(metadata, redirect_uri=redirect_uri, code=code, code_verifier=code_verifier)
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise _provider_error(self.config, "the token response has no id_token")
        claims = await self._verify(metadata, id_token, nonce)

        # GitLab keeps the full group list in userinfo; its id_token only carries ``groups_direct``.
        needs_email = not claims.get("email")
        wants_groups = self.config.preset is Preset.GITLAB and "groups" not in claims
        access_token = tokens.get("access_token")
        groups_unknown = False
        if (needs_email or wants_groups) and metadata.get("userinfo_endpoint") and isinstance(access_token, str):
            try:
                claims = {**await self._userinfo(str(metadata["userinfo_endpoint"]), access_token), **claims}
            except SsoError:
                if needs_email:
                    raise  # without an email nobody can be signed in; for groups alone, keep going
                # ``groups_direct`` leaves out the groups someone is in through a parent group: syncing from it
                # would take those memberships away until the next sign-in. Leave the groups as they are.
                groups_unknown = True
        if "groups" not in claims and not groups_unknown and isinstance(claims.get("groups_direct"), list):
            claims = {**claims, "groups": claims["groups_direct"]}

        name = claims.get("name") or claims.get("preferred_username")
        return ExternalProfile(
            subject=str(claims["sub"]),
            email=str(claims["email"]) if claims.get("email") else None,
            email_verified=_truthy(claims.get("email_verified")),
            display_name=str(name) if name else None,
            claims=_kept(claims),
        )

    async def _exchange(
        self, metadata: Mapping[str, Any], *, redirect_uri: str, code: str, code_verifier: str
    ) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": self.config.client_id,
        }
        auth: httpx.BasicAuth | httpx._client.UseClientDefault = httpx.USE_CLIENT_DEFAULT  # pyright: ignore[reportPrivateUsage]
        methods: Sequence[str] = metadata.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        if self.config.client_secret:
            if "client_secret_basic" in methods:
                auth = httpx.BasicAuth(self.config.client_id, self.config.client_secret)
            else:
                data["client_secret"] = self.config.client_secret
        try:
            response = await self._http.post(
                str(metadata["token_endpoint"]), data=data, auth=auth, headers={"Accept": "application/json"}
            )
            body = cast("dict[str, Any]", response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise _provider_error(self.config, f"token request failed ({exc})") from exc
        if response.status_code >= 400 or "error" in body:  # noqa: PLR2004
            raise _provider_error(
                self.config, str(body.get("error_description") or body.get("error") or response.status_code)
            )
        return body

    async def _verify(self, metadata: Mapping[str, Any], id_token: str, nonce: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise _provider_error(self.config, f"malformed id_token ({exc})") from exc
        supported = metadata.get("id_token_signing_alg_values_supported") or ["RS256"]
        algorithms = [alg for alg in supported if alg in ALLOWED_ALGORITHMS]
        key = await self._signing_key(metadata, header.get("kid"))
        try:
            claims: dict[str, Any] = jwt.decode(
                id_token,
                key=key,
                algorithms=algorithms,
                audience=self.config.client_id,
                issuer=str(metadata["issuer"]),
                leeway=CLOCK_LEEWAY,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise _provider_error(self.config, f"the id_token is not valid ({exc})") from exc
        if claims.get("nonce") != nonce:
            raise SsoError("nonce_mismatch", "The sign-in response was replayed or tampered with. Start again.")
        return claims

    async def _userinfo(self, url: str, access_token: str) -> dict[str, Any]:
        try:
            response = await self._http.get(url, headers={"Authorization": f"Bearer {access_token}"})
            response.raise_for_status()
            body: object = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise _provider_error(self.config, f"userinfo request failed ({exc})") from exc
        if not isinstance(body, dict):
            raise _provider_error(self.config, "the userinfo response is not a JSON object")
        return cast("dict[str, Any]", body)


class GitHubClient:
    """github.com or GitHub Enterprise Server. Requires a verified primary email address."""

    def __init__(self, config: ProviderConfig, http: httpx.AsyncClient) -> None:
        self.config = config
        self._http = http
        base = config.base_url or "https://github.com"
        self._web = base
        self._api = "https://api.github.com" if base == "https://github.com" else f"{base}/api/v3"

    async def authorization_url(self, *, redirect_uri: str, state: str, nonce: str, code_challenge: str) -> str:  # noqa: ARG002
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "allow_signup": "false",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._web}/login/oauth/authorize?{urlencode(params)}"

    async def complete(self, *, redirect_uri: str, code: str, code_verifier: str, nonce: str) -> ExternalProfile:  # noqa: ARG002
        try:
            response = await self._http.post(
                f"{self._web}/login/oauth/access_token",
                data={
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret or "",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            body = cast("dict[str, Any]", response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise _provider_error(self.config, f"token request failed ({exc})") from exc
        token = body.get("access_token")
        if not isinstance(token, str):
            raise _provider_error(self.config, str(body.get("error_description") or body.get("error") or "no token"))

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            user_response = await self._http.get(f"{self._api}/user", headers=headers)
            user_response.raise_for_status()
            user = cast("dict[str, Any]", user_response.json())
            emails_response = await self._http.get(f"{self._api}/user/emails", headers=headers)
            emails_response.raise_for_status()
            emails = cast("list[dict[str, Any]]", emails_response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise _provider_error(self.config, f"profile request failed ({exc})") from exc

        primary = next((item for item in emails if item.get("primary") and item.get("verified")), None)
        return ExternalProfile(
            subject=str(user["id"]),
            email=str(primary["email"]) if primary else None,
            email_verified=primary is not None,
            display_name=str(user.get("name") or user.get("login") or "") or None,
            claims=_kept({**user, "email": primary["email"] if primary else None}),
        )


@dataclass(frozen=True, slots=True)
class SsoHttp:
    """The outbound HTTP client for identity providers (discovery, tokens, profiles, SAML metadata)."""

    client: httpx.AsyncClient


def _client_for(config: ProviderConfig, http: httpx.AsyncClient) -> OidcClient | GitHubClient | None:
    if config.protocol is SignInProtocol.GITHUB:
        return GitHubClient(config, http)
    if config.protocol is SignInProtocol.OIDC:
        return OidcClient(config, http)
    return None


class SignInClientRegistry:
    """Clients of the settings-configured providers, plus clients of stored providers cached per version.

    Discovery documents and signing keys are reused across requests.
    """

    def __init__(self, configs: Sequence[ProviderConfig], http: SsoHttp) -> None:
        self._configs = list(configs)
        self._http = http.client
        self._clients: dict[str, OidcClient | GitHubClient | None] = {
            config.id: _client_for(config, self._http) for config in configs
        }
        self._stored: dict[str, tuple[str, OidcClient | GitHubClient | None]] = {}

    def configured(self) -> list[ProviderConfig]:
        return list(self._configs)

    def configured_client(self, provider_id: str) -> OidcClient | GitHubClient | None:
        return self._clients.get(provider_id)

    def stored_client(self, config: ProviderConfig) -> OidcClient | GitHubClient | None:
        cached = self._stored.get(config.id)
        if cached is not None and cached[0] == config.version:
            return cached[1]
        client = _client_for(config, self._http)
        self._stored[config.id] = (config.version, client)
        return client


class SignInDirectory:
    """``SignInClients`` for one request: settings-configured providers first, then enabled stored ones."""

    def __init__(self, registry: SignInClientRegistry, providers: LoginProviderRepository) -> None:
        self._registry = registry
        self._providers = providers

    def configured(self) -> list[ProviderConfig]:
        return self._registry.configured()

    async def all(self) -> list[ProviderConfig]:
        configured = self._registry.configured()
        taken = {config.id for config in configured}
        stored = [item.config for item in await self._providers.list() if item.enabled and item.config.id not in taken]
        return sorted([*configured, *stored], key=lambda config: config.id)

    async def config(self, provider_id: str) -> ProviderConfig | None:
        for config in self._registry.configured():
            if config.id == provider_id:
                return config
        stored = await self._providers.get(provider_id)
        return stored.config if stored is not None and stored.enabled else None

    async def get(self, provider_id: str) -> OidcClient | GitHubClient | None:
        if provider_id in {config.id for config in self._registry.configured()}:
            return self._registry.configured_client(provider_id)
        stored = await self._providers.get(provider_id)
        if stored is None or not stored.enabled:
            return None
        return self._registry.stored_client(stored.config)
