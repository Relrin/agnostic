"""Signing in through SSO providers: generic OIDC (any IdP with discovery) and GitHub, with mocked IdPs."""

import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from tests.support.stack import Stack, running_stack

ISSUER = "https://sso.localhost.test"
CALLBACK = "http://agnostic.test/api/v1/auth/sso/corp/callback"


@pytest.fixture(scope="module")
def idp_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
async def stack(sqlite_database: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    env = {
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__PRESET": "oidc",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__DISPLAY_NAME": "Localhost Company SSO",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__ISSUER": ISSUER,
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__CLIENT_ID": "agnostic",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__CLIENT_SECRET": "s3cret",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__JIT_PROVISIONING": "true",
        "AGNOSTIC_IDENTITY__PROVIDERS__CORP__ALLOWED_EMAIL_DOMAINS": "localhost.company",
        "AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__PRESET": "github",
        "AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__CLIENT_ID": "Iv1.abc",
        "AGNOSTIC_IDENTITY__PROVIDERS__GITHUB__CLIENT_SECRET": "gh-secret",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    async with running_stack(sqlite_database) as running:
        yield running


class Idp:
    def __init__(self, router: respx.MockRouter, key: rsa.RSAPrivateKey) -> None:
        self.key = key
        self.claims: dict[str, Any] = {}
        self.nonce = ""
        self.token_requests: list[httpx.Request] = []
        public = jwt.PyJWK.from_dict({**RSAAlgorithm.to_jwk(key.public_key(), as_dict=True), "kid": "k1", "use": "sig"})
        router.get(f"{ISSUER}/.well-known/openid-configuration").respond(
            json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "userinfo_endpoint": f"{ISSUER}/userinfo",
                "id_token_signing_alg_values_supported": ["RS256"],
                "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            }
        )
        router.get(f"{ISSUER}/jwks").respond(
            json={"keys": [{**public._jwk_data, "kid": "k1"}]}  # pyright: ignore[reportPrivateUsage]
        )
        router.post(f"{ISSUER}/token").mock(side_effect=self._token)

    def _token(self, request: httpx.Request) -> httpx.Response:
        self.token_requests.append(request)
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "agnostic",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "email_verified": True,
            **self.claims,
        }
        token = jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k1"})
        return httpx.Response(200, json={"access_token": "at", "id_token": token, "token_type": "Bearer"})


async def sso_sign_in(
    client: httpx.AsyncClient, idp: Idp, provider: str = "corp", next_path: str = "/"
) -> httpx.Response:
    start = await client.get(f"/api/v1/auth/sso/{provider}/start", params={"next": next_path})
    assert start.status_code == 302, start.text
    query = parse_qs(urlsplit(start.headers["location"]).query)
    idp.nonce = query.get("nonce", [""])[0]
    return await client.get(
        f"/api/v1/auth/sso/{provider}/callback", params={"code": "the-code", "state": query["state"][0]}
    )


async def test_providers_are_listed(stack: Stack) -> None:
    options = (await stack.client().get("/api/v1/auth/providers")).json()
    assert options == {
        "local_login": True,
        "sso_enforced": False,
        "providers": [
            {"id": "corp", "display_name": "Localhost Company SSO", "preset": "oidc"},
            {"id": "github", "display_name": "GitHub", "preset": "github"},
        ],
    }


async def test_oidc_invited_person_joins_with_their_role(stack: Stack, idp_key: rsa.RSAPrivateKey) -> None:
    owner = await stack.owner()
    roles = {role["slug"]: role["id"] for role in (await owner.get("/api/v1/access/roles")).json()}
    invited = await owner.post(
        "/api/v1/invitations",
        json={"email": "marcus@localhost.company", "org_role": "member", "bindings": [{"role_id": roles["viewer"]}]},
    )
    assert invited.status_code == 201
    with respx.mock(assert_all_called=False) as router:
        idp = Idp(router, idp_key)
        idp.claims = {"sub": "kc-marcus", "email": "Marcus@Localhost.company", "name": "Marcus Chen"}
        marcus = stack.client()
        start = await marcus.get("/api/v1/auth/sso/corp/start", params={"next": "/access/people"})
        location = urlsplit(start.headers["location"])
        query = parse_qs(location.query)
        assert f"{location.scheme}://{location.netloc}{location.path}" == f"{ISSUER}/authorize"
        assert query["redirect_uri"] == [CALLBACK]
        assert query["code_challenge_method"] == ["S256"]
        assert query["scope"] == ["openid profile email"]
        idp.nonce = query["nonce"][0]
        callback = await marcus.get(
            "/api/v1/auth/sso/corp/callback", params={"code": "the-code", "state": query["state"][0]}
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == "/access/people"
        token_form = parse_qs(idp.token_requests[0].content.decode())
        assert token_form["code_verifier"][0]
        assert idp.token_requests[0].headers["authorization"].startswith("Basic ")

        me = (await marcus.get("/api/v1/me")).json()
        assert (me["email"], me["display_name"], me["org_role"]) == (
            "marcus@localhost.company",
            "Marcus Chen",
            "member",
        )
        assert me["sso_providers"] == ["corp"]
        assert me["has_password"] is False
        access = (await marcus.get("/api/v1/me/access")).json()
        assert access["org_role"] == "member"

        # The state is single-use.
        replay = await stack.client().get(
            "/api/v1/auth/sso/corp/callback", params={"code": "the-code", "state": query["state"][0]}
        )
        assert replay.headers["location"] == "/login?error=state_expired"

        # Signing in again finds the linked identity.
        again = await sso_sign_in(stack.client(), idp)
        assert again.headers["location"] == "/"


async def test_oidc_admission_rules(stack: Stack, idp_key: rsa.RSAPrivateKey) -> None:
    _ = await stack.owner()
    with respx.mock(assert_all_called=False) as router:
        idp = Idp(router, idp_key)
        idp.claims = {"sub": "kc-evan", "email": "evan@elsewhere.dev", "name": "Evan"}
        outsider = await sso_sign_in(stack.client(), idp)
        assert outsider.headers["location"] == "/login?error=not_invited"

        idp.claims = {"sub": "kc-omar", "email": "omar@localhost.company", "name": "Omar", "email_verified": False}
        unverified = await sso_sign_in(stack.client(), idp)
        assert unverified.headers["location"] == "/login?error=email_unverified"

        idp.claims = {"sub": "kc-omar", "email": "omar@localhost.company", "name": "Omar Haddad"}
        omar = stack.client()
        joined = await sso_sign_in(omar, idp)
        assert joined.headers["location"] == "/"
        me = (await omar.get("/api/v1/me")).json()
        assert (me["display_name"], me["org_role"]) == ("Omar Haddad", "member")

        client = stack.client()
        start = await client.get("/api/v1/auth/sso/corp/start")
        state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
        idp.nonce = "forged"
        forged = await client.get("/api/v1/auth/sso/corp/callback", params={"code": "c", "state": state})
        assert forged.headers["location"] == "/login?error=nonce_mismatch"

    denied = await stack.client().get("/api/v1/auth/sso/corp/callback", params={"error": "access_denied"})
    assert denied.headers["location"] == "/login?error=provider_denied"
    unknown = await stack.client().get("/api/v1/auth/sso/nope/start")
    assert unknown.status_code == 404


async def test_github_sign_in(stack: Stack) -> None:
    owner = await stack.owner()
    _ = await owner.post("/api/v1/invitations", json={"email": "pavel@localhost.company", "org_role": "administrator"})
    with respx.mock(assert_all_called=False) as router:
        router.post("https://github.com/login/oauth/access_token").respond(json={"access_token": "gho_x"})
        router.get("https://api.github.com/user").respond(json={"id": 4242, "login": "pavel", "name": "Pavel Nair"})
        router.get("https://api.github.com/user/emails").respond(
            json=[
                {"email": "pavel@personal.dev", "primary": False, "verified": True},
                {"email": "pavel@localhost.company", "primary": True, "verified": True},
            ]
        )
        pavel = stack.client()
        start = await pavel.get("/api/v1/auth/sso/github/start")
        assert start.headers["location"].startswith("https://github.com/login/oauth/authorize?")
        query = parse_qs(urlsplit(start.headers["location"]).query)
        assert query["scope"] == ["read:user user:email"]
        callback = await pavel.get("/api/v1/auth/sso/github/callback", params={"code": "c", "state": query["state"][0]})
        assert callback.status_code == 302
        assert callback.headers["location"] == "/"
    me = (await pavel.get("/api/v1/me")).json()
    assert (me["email"], me["display_name"], me["org_role"]) == (
        "pavel@localhost.company",
        "Pavel Nair",
        "administrator",
    )
