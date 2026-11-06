"""The OIDC and GitHub sign-in clients against IdPs with uncommon (but valid) answers."""

from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agnostic_identity.domain.providers import Preset, resolve_provider
from agnostic_identity.infrastructure.signin_clients import GitHubClient, OidcClient

REDIRECT = "https://agnostic.test/api/v1/auth/sso/idp/callback"


def _discovery(router: respx.MockRouter, issuer: str, *, authorize: str | None = None) -> None:
    router.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration").respond(
        json={
            "issuer": issuer,
            "authorization_endpoint": authorize or f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/jwks",
        }
    )


async def test_an_authorize_endpoint_with_its_own_query_keeps_it() -> None:
    config = resolve_provider("b2c", preset=Preset.OIDC, client_id="c", client_secret=None, issuer="https://b2c.test")
    with respx.mock() as router:
        _discovery(router, "https://b2c.test", authorize="https://b2c.test/authorize?p=b2c_1_signin")
        async with httpx.AsyncClient() as http:
            url = httpx.URL(
                await OidcClient(config, http).authorization_url(
                    redirect_uri=REDIRECT, state="s", nonce="n", code_challenge="x"
                )
            )
    assert url.path == "/authorize"
    assert url.params["p"] == "b2c_1_signin"
    assert url.params["state"] == "s"


@pytest.mark.parametrize("iss", ["https://accounts.google.com", "accounts.google.com"])
async def test_google_id_tokens_name_either_form_of_its_issuer(iss: str) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    now = int(time.time())
    claims = {"iss": iss, "aud": "c", "sub": "42", "iat": now, "exp": now + 300, "nonce": "n", "email": "a@b.test"}
    id_token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})
    config = resolve_provider("google", preset=Preset.GOOGLE, client_id="c", client_secret="s")
    with respx.mock() as router:
        _discovery(router, "https://accounts.google.com")
        router.get("https://accounts.google.com/jwks").respond(json={"keys": [{**jwk, "kid": "k1", "alg": "RS256"}]})
        router.post("https://accounts.google.com/token").respond(json={"id_token": id_token})
        async with httpx.AsyncClient() as http:
            profile = await OidcClient(config, http).complete(
                redirect_uri=REDIRECT, code="code", code_verifier="v", nonce="n"
            )
    assert profile.subject == "42"


@pytest.mark.parametrize("base_url", [None, "https://github.com/", "https://www.github.com", "HTTPS://GitHub.com"])
async def test_github_com_is_recognised_however_its_url_is_written(base_url: str | None) -> None:
    config = resolve_provider("github", preset=Preset.GITHUB, client_id="c", client_secret="s", base_url=base_url)
    async with httpx.AsyncClient() as http:
        client = GitHubClient(config, http)
        url = await client.authorization_url(redirect_uri=REDIRECT, state="s", nonce="n", code_challenge="x")
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert client._api == "https://api.github.com"  # pyright: ignore[reportPrivateUsage]


async def test_github_enterprise_server_uses_its_own_api() -> None:
    config = resolve_provider(
        "ghe", preset=Preset.GITHUB, client_id="c", client_secret="s", base_url="https://github.corp.test/"
    )
    async with httpx.AsyncClient() as http:
        client = GitHubClient(config, http)
        url = await client.authorization_url(redirect_uri=REDIRECT, state="s", nonce="n", code_challenge="x")
    assert url.startswith("https://github.corp.test/login/oauth/authorize?")
    assert client._api == "https://github.corp.test/api/v3"  # pyright: ignore[reportPrivateUsage]
