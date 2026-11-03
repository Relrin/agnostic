"""Git host clients against recorded-style responses: GitHub App tokens (a signed JWT traded for an installation
token, cached sealed), review requirements from branch protection, pull requests, and GitLab merge requests."""

import asyncio
import base64

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.ephemeral import MemoryStore
from agnostic_sources.application.ports import ProviderError, Secrets
from agnostic_sources.domain.model import Connection
from agnostic_sources.infrastructure.http import SourcesHttp
from agnostic_sources.infrastructure.providers import HttpProviderClients
from agnostic_sources.infrastructure.providers.github import GitHubAppTokens
from agnostic_sources.infrastructure.providers.gitlab import GitLabClient
from agnostic_sources.settings import SourcesSettings

API = "https://api.github.com"


def rsa_pair() -> tuple[str, rsa.RSAPublicKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return pem, key.public_key()


def test_github_app_trades_a_signed_jwt_for_a_cached_installation_token() -> None:
    pem, public = rsa_pair()
    calls: list[str] = []

    def issue(request: httpx.Request) -> httpx.Response:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, public, algorithms=["RS256"])
        assert claims["iss"] == "12345"
        calls.append(token)
        return httpx.Response(201, json={"token": "ghs_installation_token_value", "expires_at": "2026-11-03T23:00:00Z"})

    async def scenario() -> None:
        http = SourcesHttp()
        tokens = GitHubAppTokens(http.client, MemoryStore(), SecretBox(b"k" * 32))
        connection = Connection(
            id="scn_1", name="GitHub", provider="github", auth_kind="github_app", installation_id="777"
        )
        client = HttpProviderClients(http, SourcesSettings(), tokens).client(
            connection, Secrets(app_id="12345", private_key=pem)
        )
        with respx.mock(base_url=API, assert_all_called=True) as mock:
            _ = mock.post("/app/installations/777/access_tokens").mock(side_effect=issue)
            _ = mock.get("/repos/northwind/agent-platform/rules/branches/main").respond(
                200, json=[{"type": "pull_request", "parameters": {"required_approving_review_count": 1}}]
            )
            _ = mock.post("/repos/northwind/agent-platform/pulls").respond(
                201, json={"number": 12, "html_url": "https://github.com/northwind/agent-platform/pull/12"}
            )
            _ = mock.get("/repos/northwind/agent-platform/pulls/12").respond(
                200, json={"merged": True, "merge_commit_sha": "c" * 40, "head": {"sha": "b" * 40}}
            )
            assert await client.review_requirement("northwind/agent-platform", "main") == (1, [])
            opened = await client.open_pull_request(
                "northwind/agent-platform", head="studio/support-triage-v4", base="main", title="t", body="b"
            )
            assert opened.number == 12
            state = await client.pull_request("northwind/agent-platform", 12)
            assert (state.status, state.merge_sha) == ("merged", "c" * 40)
            remote = await client.remote("northwind/agent-platform", None)
            assert remote.url == "https://github.com/northwind/agent-platform.git"
            assert remote.header is not None
            user, _, password = base64.b64decode(remote.header.removeprefix("Basic ")).decode().partition(":")
            assert (user, password) == ("x-access-token", "ghs_installation_token_value")
            assert await client.register_webhook("northwind/agent-platform", "https://x/hooks/github", "s") is None
        assert len(calls) == 1, "the installation token is minted once and then reused"
        await http.aclose()

    asyncio.run(scenario())


def test_an_uninstalled_github_app_is_explained() -> None:
    http = SourcesHttp()
    clients = HttpProviderClients(
        http, SourcesSettings(), GitHubAppTokens(http.client, MemoryStore(), SecretBox(b"k" * 32))
    )
    connection = Connection(id="scn_2", name="GitHub", provider="github", auth_kind="github_app")
    with pytest.raises(ProviderError, match="isn't installed"):
        _ = clients.client(connection, Secrets(app_id="1", private_key="x"))
    asyncio.run(http.aclose())


def test_gitlab_merge_requests_and_approval_rules() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient() as raw:
            client = GitLabClient(raw, "https://gitlab.test/api/v4", "https://gitlab.test", "glpat-token")
            with respx.mock(base_url="https://gitlab.test/api/v4", assert_all_called=True) as mock:
                rules = mock.get("/projects/northwind%2Fdata-agents/approval_rules").respond(
                    200, json=[{"name": "Platform", "approvals_required": 1}]
                )
                _ = mock.post("/projects/northwind%2Fdata-agents/merge_requests").respond(
                    201, json={"iid": 3, "web_url": "https://gitlab.test/northwind/data-agents/-/merge_requests/3"}
                )
                _ = mock.get("/projects/northwind%2Fdata-agents/merge_requests/3").respond(
                    200, json={"state": "merged", "merge_commit_sha": "d" * 40, "sha": "e" * 40}
                )
                assert await client.review_requirement("northwind/data-agents", "main") == (1, ["Platform"])
                assert rules.calls.last.request.headers["PRIVATE-TOKEN"] == "glpat-token"
                opened = await client.open_pull_request(
                    "northwind/data-agents", head="studio/x-v1", base="main", title="t", body="b"
                )
                assert opened.number == 3
                state = await client.pull_request("northwind/data-agents", 3)
                assert (state.status, state.merge_sha) == ("merged", "d" * 40)

    asyncio.run(scenario())
