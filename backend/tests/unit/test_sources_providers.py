"""Git host clients against recorded-style responses: GitHub App tokens (a signed JWT traded for an installation
token, cached sealed), review requirements from branch protection, pull requests, GitLab merge requests, paging
through lists, server-side repository search, GitHub Enterprise URLs, Gitea and Forgejo, and deploy keys."""

import asyncio
import base64
import json
from collections.abc import Callable
from typing import Any, Literal, cast

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.ephemeral import MemoryStore
from agnostic_sources.application.ports import GitError, ProviderError, Remote, Secrets
from agnostic_sources.domain.model import Connection
from agnostic_sources.infrastructure.http import SourcesHttp
from agnostic_sources.infrastructure.providers import HttpProviderClients
from agnostic_sources.infrastructure.providers.gitea import GiteaClient
from agnostic_sources.infrastructure.providers.github import SEARCH_LIMIT, GitHubAppTokens, _searches
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


# ---------------------------------------------------------------- against a scripted host (httpx MockTransport)


type Route = Callable[[httpx.Request], httpx.Response]


class Host:
    """A scripted git host: ``routes`` maps ``METHOD /path`` to a handler; every request is kept."""

    def __init__(self, routes: dict[str, Route]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(f"{request.method} {_path(request)}")
        if route is None:
            return httpx.Response(404, json={"message": f"no route {request.method} {_path(request)}"})
        return route(request)

    def http(self) -> SourcesHttp:
        return SourcesHttp(transport=httpx.MockTransport(self))

    def seen(self, method: str, path: str) -> list[httpx.Request]:
        return [request for request in self.requests if (request.method, _path(request)) == (method, path)]


def _path(request: httpx.Request) -> str:
    """The path as sent (GitLab project ids keep their ``%2F``)."""
    return request.url.raw_path.split(b"?")[0].decode()


def respond(body: object, status: int = 200, headers: dict[str, str] | None = None) -> Route:
    return lambda _: httpx.Response(status, json=body, headers=headers)


def paged(pages: list[list[dict[str, Any]]], *, gitlab: bool = False, page_param: str = "page") -> Route:
    """A list endpoint answering page ``?page=N`` with a ``Link`` (or GitLab's ``X-Next-Page``) to the next one."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get(page_param, "1"))
        headers: dict[str, str] = {}
        if page < len(pages):
            if gitlab:
                headers["X-Next-Page"] = str(page + 1)
            else:
                following = request.url.copy_merge_params({page_param: str(page + 1)})
                headers["Link"] = f'<{following}>; rel="next"'
        elif gitlab:
            headers["X-Next-Page"] = ""
        return httpx.Response(200, json=pages[page - 1], headers=headers)

    return handler


def clients(http: SourcesHttp, settings: SourcesSettings | None = None) -> HttpProviderClients:
    return HttpProviderClients(
        http, settings or SourcesSettings(), GitHubAppTokens(http.client, MemoryStore(), SecretBox(b"k" * 32))
    )


def gitea_connection(provider: Literal["gitea", "forgejo"] = "gitea") -> Connection:
    return Connection(id="scn_g", name="Gitea", provider=provider, auth_kind="token", web_url="https://git.test")


async def test_gitea_lists_the_users_repositories_page_by_page_and_searches_only_what_it_reaches() -> None:
    host = Host(
        {
            "GET /api/v1/user": respond({"id": 42, "login": "agnostic-bot"}),
            "GET /api/v1/user/repos": paged(
                [
                    [{"full_name": "northwind/a", "private": False, "default_branch": "main"}],
                    [{"full_name": "northwind/b", "private": True, "default_branch": "trunk"}],
                ]
            ),
            "GET /api/v1/repos/search": respond({"ok": True, "data": [{"full_name": "northwind/agents"}]}),
            "GET /api/v1/repos/northwind/a/branches": paged([[{"name": "main"}], [{"name": "dev"}], [{"name": "x"}]]),
        }
    )
    http = host.http()
    client = clients(http).client(gitea_connection(), Secrets(token="tok"))
    repos = await client.repos()
    assert [(repo.full_name, repo.private, repo.default_branch) for repo in repos] == [
        ("northwind/a", False, "main"),
        ("northwind/b", True, "trunk"),
    ]
    assert [request.url.params.get("limit") for request in host.seen("GET", "/api/v1/user/repos")] == ["100", "100"]
    assert [repo.full_name for repo in await client.repos("agents")] == ["northwind/agents"]
    [search] = host.seen("GET", "/api/v1/repos/search")
    assert (search.url.params["q"], search.url.params["uid"]) == ("agents", "42")
    assert await client.branches("northwind/a") == ["dev", "main", "x"]
    assert host.seen("GET", "/api/v1/repos/search")[0].headers["Authorization"] == "token tok"
    await http.aclose()


async def test_gitea_branch_protection_is_found_by_its_glob() -> None:
    rules = [
        {"rule_name": "main", "required_approvals": 1, "approvals_whitelist_teams": ["platform"]},
        {"rule_name": "release/*", "required_approvals": 2, "approvals_whitelist_teams": ["release-managers"]},
    ]
    host = Host({"GET /api/v1/repos/northwind/agents/branch_protections": respond(rules)})
    http = host.http()
    client = clients(http).client(gitea_connection(), Secrets(token="tok"))
    assert await client.review_requirement("northwind/agents", "release/2026.11") == (2, ["Release managers"])
    assert await client.review_requirement("northwind/agents", "main") == (1, ["Platform"])
    assert await client.review_requirement("northwind/agents", "feature/x") == (0, [])
    await http.aclose()


async def test_a_forgejo_webhook_falls_back_to_the_gitea_type() -> None:
    kinds: list[str] = []

    def hooks(request: httpx.Request) -> httpx.Response:
        kind = json.loads(request.content)["type"]
        kinds.append(kind)
        if kind == "forgejo":
            return httpx.Response(422, json={"message": "invalid hook type"})
        return httpx.Response(201, json={"id": 9})

    host = Host({"POST /api/v1/repos/northwind/agents/hooks": hooks})
    http = host.http()
    forgejo = clients(http).client(gitea_connection("forgejo"), Secrets(token="tok"))
    assert await forgejo.register_webhook("northwind/agents", "https://agnostic.test/hooks/gitea", "s") == "9"
    assert kinds == ["forgejo", "gitea"]
    gitea = clients(http).client(gitea_connection("gitea"), Secrets(token="tok"))
    assert await gitea.register_webhook("northwind/agents", "https://agnostic.test/hooks/gitea", "s") == "9"
    assert kinds == ["forgejo", "gitea", "gitea"]
    await http.aclose()


async def test_github_with_a_token_searches_on_the_server_in_the_accounts_it_reaches() -> None:
    host = Host(
        {
            "GET /user": respond({"login": "sam"}),
            "GET /user/orgs": paged([[{"login": "northwind"}], [{"login": "contoso"}]]),
            "GET /user/repos": paged(
                [[{"full_name": "sam/dotfiles", "private": False}], [{"full_name": "northwind/agents"}]]
            ),
            "GET /search/repositories": respond(
                {"total_count": 1, "items": [{"full_name": "northwind/agents", "private": True}]}
            ),
            "GET /repos/northwind/agents/branches": paged([[{"name": "main"}], [{"name": "studio/x-v1"}]]),
        }
    )
    http = host.http()
    connection = Connection(id="scn_t", name="GitHub", provider="github", auth_kind="token")
    client = clients(http).client(connection, Secrets(token="ghp_token"))
    assert [repo.full_name for repo in await client.repos()] == ["sam/dotfiles", "northwind/agents"]
    assert [repo.full_name for repo in await client.repos("agents")] == ["northwind/agents"]
    [search] = host.seen("GET", "/search/repositories")
    assert search.url.params["q"] == "agents in:name user:sam user:northwind user:contoso"
    assert search.headers["Authorization"] == "Bearer ghp_token"
    assert await client.branches("northwind/agents") == ["main", "studio/x-v1"]
    assert {request.url.host for request in host.requests} == {"api.github.com"}
    await http.aclose()


def test_github_search_queries_stay_within_the_length_limit() -> None:
    owners = [f"organization-{index:03d}" for index in range(40)]
    searches = _searches("agents", owners)
    assert len(searches) > 1
    assert all(len(search) <= SEARCH_LIMIT and search.startswith("agents in:name ") for search in searches)
    assert sorted(term for search in searches for term in search.split() if term.startswith("user:")) == sorted(
        f"user:{owner}" for owner in owners
    )


@pytest.mark.parametrize(
    ("web_url", "api_url", "expected_api", "expected_clone"),
    [
        (None, None, "https://api.github.com/user", "https://github.com/northwind/agents.git"),
        ("https://github.com", None, "https://api.github.com/user", "https://github.com/northwind/agents.git"),
        (
            "https://ghe.northwind.test",
            None,
            "https://ghe.northwind.test/api/v3/user",
            "https://ghe.northwind.test/northwind/agents.git",
        ),
        (
            "https://ghe.northwind.test/",
            "https://api.ghe.northwind.test",
            "https://api.ghe.northwind.test/user",
            "https://ghe.northwind.test/northwind/agents.git",
        ),
    ],
)
async def test_github_enterprise_urls(
    web_url: str | None, api_url: str | None, expected_api: str, expected_clone: str
) -> None:
    host = Host({})
    host.routes = {"GET " + httpx.URL(expected_api).path: respond({"login": "sam"})}
    http = host.http()
    connection = Connection(
        id="scn_e", name="GHE", provider="github", auth_kind="token", web_url=web_url, api_url=api_url
    )
    client = clients(http).client(connection, Secrets(token="ghp_token"))
    assert await client.verify() == "sam"
    assert str(host.requests[0].url) == expected_api
    assert (await client.remote("northwind/agents", None)).url == expected_clone
    await http.aclose()


async def test_gitlab_pages_with_x_next_page_and_reads_visibility() -> None:
    host = Host(
        {
            "GET /api/v4/projects": paged(
                [
                    [{"path_with_namespace": "northwind/public-agents", "visibility": "public"}],
                    [{"path_with_namespace": "northwind/agents", "visibility": "private"}],
                ],
                gitlab=True,
            ),
            "GET /api/v4/projects/northwind%2Fagents/repository/branches": paged(
                [[{"name": "main"}], [{"name": "dev"}]], gitlab=True
            ),
        }
    )
    http = host.http()
    connection = Connection(
        id="scn_l", name="GitLab", provider="gitlab", auth_kind="token", web_url="https://gitlab.test"
    )
    client = clients(http).client(connection, Secrets(token="glpat-token"))
    repos = await client.repos("agents")
    assert [(repo.full_name, repo.private) for repo in repos] == [
        ("northwind/public-agents", False),
        ("northwind/agents", True),
    ]
    first = host.seen("GET", "/api/v4/projects")[0]
    assert "simple" not in first.url.params
    assert (first.url.params["search"], first.url.params["membership"]) == ("agents", "true")
    assert [request.url.params.get("page") for request in host.seen("GET", "/api/v4/projects")] == [None, "2"]
    assert await client.branches("northwind/agents") == ["dev", "main"]
    await http.aclose()


async def test_a_locked_gitlab_merge_request_is_still_open() -> None:
    host = Host(
        {
            "GET /api/v4/projects/northwind%2Fagents/merge_requests/4": respond({"state": "locked", "sha": "a" * 40}),
            "GET /api/v4/projects/northwind%2Fagents/merge_requests/5": respond({"state": "closed"}),
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(host)) as raw:
        client = GitLabClient(raw, "https://gitlab.test/api/v4", "https://gitlab.test", "glpat-token")
        assert (await client.pull_request("northwind/agents", 4)).status == "open"
        assert (await client.pull_request("northwind/agents", 5)).status == "closed"


async def test_gitlab_review_requirement_counts_only_the_target_branchs_rules_and_takes_the_strictest() -> None:
    rules = [
        {"name": "Everyone", "approvals_required": 1, "protected_branches": []},
        {"name": "Release", "approvals_required": 3, "protected_branches": [{"name": "release/*"}]},
        {"name": "Platform", "approvals_required": 2, "protected_branches": [{"name": "main"}]},
        {"name": "Protected", "approvals_required": 2, "applies_to_all_protected_branches": True},
    ]
    host = Host(
        {
            "GET /api/v4/projects/northwind%2Fagents/approval_rules": respond(rules),
            "GET /api/v4/projects/northwind%2Fagents/protected_branches": respond([{"name": "main"}]),
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(host)) as raw:
        client = GitLabClient(raw, "https://gitlab.test/api/v4", "https://gitlab.test", "glpat-token")
        assert await client.review_requirement("northwind/agents", "main") == (2, ["Everyone", "Platform", "Protected"])
        assert await client.review_requirement("northwind/agents", "release/1.0") == (3, ["Everyone", "Release"])
        assert await client.review_requirement("northwind/agents", "feature/x") == (1, ["Everyone"])


async def test_gitlab_counts_rules_for_every_protected_branch_even_when_the_list_is_hidden() -> None:
    rules = [
        {"name": "Everyone", "approvals_required": 1, "protected_branches": []},
        {"name": "Protected", "approvals_required": 2, "applies_to_all_protected_branches": True},
        {"name": "Vulnerabilities", "approvals_required": 4, "rule_type": "report_approver", "protected_branches": []},
        {"name": "Hotfixes", "approvals_required": 3, "protected_branches": [{"name": "hotfix/*"}]},
    ]
    hidden = respond({"message": "403 Forbidden"}, 403)
    host = Host(
        {
            "GET /api/v4/projects/northwind%2Fagents/approval_rules": respond(rules),
            "GET /api/v4/projects/northwind%2Fagents/protected_branches": hidden,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(host)) as raw:
        client = GitLabClient(raw, "https://gitlab.test/api/v4", "https://gitlab.test", "glpat-token")
        assert await client.review_requirement("northwind/agents", "main") == (2, ["Everyone", "Protected"])
        assert await client.review_requirement("northwind/agents", "hotfix/2026/11") == (
            3,
            ["Everyone", "Protected", "Hotfixes"],
        ), "GitLab's * matches across folders"
    assert len(host.seen("GET", "/api/v4/projects/northwind%2Fagents/protected_branches")) == 2


async def test_pages_stop_at_the_limit_and_never_follow_a_link_to_another_host() -> None:
    def endless(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200,
            json=[{"name": f"b{page}"}],
            headers={"Link": f'<https://git.test/api/v1/repos/o/r/branches?page={page + 1}>; rel="next"'},
        )

    def elsewhere(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[{"name": "main"}], headers={"Link": '<https://evil.test/steal?page=2>; rel="next"'}
        )

    host = Host({"GET /api/v1/repos/o/r/branches": endless, "GET /api/v1/repos/o/other/branches": elsewhere})
    http = host.http()
    client = GiteaClient(http.client, "https://git.test/api/v1", "https://git.test", "tok", "gitea")
    assert len(await client.pages("/repos/o/r/branches", max_pages=3)) == 3
    assert len(host.seen("GET", "/api/v1/repos/o/r/branches")) == 3
    assert await client.branches("o/other") == ["main"]


async def test_a_next_link_from_the_public_url_is_followed_on_the_connection_host() -> None:
    def branches(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        link = '<https://git.example.com/api/v1/repos/o/r/branches?page=2>; rel="next"' if page == 1 else ""
        return httpx.Response(200, json=[{"name": f"b{page}"}], headers={"Link": link} if link else {})

    host = Host({"GET /api/v1/repos/o/r/branches": branches})
    http = host.http()
    # The connection uses the internal address; Gitea's ROOT_URL (in its links) is the public one.
    client = GiteaClient(http.client, "https://git.test/api/v1", "https://git.test", "tok", "gitea")
    assert await client.branches("o/r") == ["b1", "b2"]
    assert {request.url.host for request in host.requests} == {"git.test"}
    await http.aclose()


async def test_a_deploy_key_reaches_git_over_ssh_and_skips_the_api() -> None:
    pem, _ = rsa_pair()
    host = Host({})
    http = host.http()
    connection = Connection(id="scn_k", name="Deploy key", provider="github", auth_kind="deploy_key")
    client = clients(http).client(connection, Secrets(private_key=pem))
    assert await client.verify() == "deploy key"
    remote = await client.remote("northwind/agents", None)
    assert (remote.url, remote.ssh_key, remote.header) == ("ssh://git@github.com/northwind/agents.git", pem, None)
    own = await client.remote("northwind/agents", "ssh://git@git.northwind.test:2222/northwind/agents.git")
    assert own.url == "ssh://git@git.northwind.test:2222/northwind/agents.git"
    assert await client.repos("agents") == []
    assert await client.review_requirement("northwind/agents", "main") is None
    assert await client.register_webhook("northwind/agents", "https://x/hooks/github", "s") is None
    with pytest.raises(ProviderError, match="opening pull requests needs a token"):
        _ = await client.open_pull_request("northwind/agents", head="h", base="main", title="t", body="b")
    assert host.requests == [], "a deploy key never calls the host's API"
    garbage = clients(http).client(connection, Secrets(private_key="not a key"))
    with pytest.raises(ProviderError, match="isn't an SSH private key"):
        _ = await garbage.verify()
    with pytest.raises(ProviderError, match="no deploy key"):
        _ = clients(http).client(connection, Secrets(token="t"))
    await http.aclose()


class SshGit:
    """``git ls-remote`` over SSH as a host answers it: ``answer`` is what git prints when it fails."""

    def __init__(self, answer: str | None = None, head: str | None = "trunk") -> None:
        self.answer = answer
        self.head = head
        self.remotes: list[Remote] = []

    async def branches(self, source_id: str, remote: Remote) -> list[str]:
        self.remotes.append(remote)
        if self.answer is not None:
            raise GitError(f"git ls-remote: {self.answer}")
        return ["main"]

    async def default_branch(self, remote: Remote) -> str | None:
        self.remotes.append(remote)
        return self.head


def deploy_key(git: SshGit, *, ssh: str | None = None) -> Any:
    http = SourcesHttp()
    connection = Connection(
        id="scn_k",
        name="Deploy key",
        provider="forgejo",
        auth_kind="deploy_key",
        web_url="https://git.northwind.test",
        api_url=ssh,
    )
    tokens = GitHubAppTokens(http.client, MemoryStore(), SecretBox(b"k" * 32))
    pem, _ = rsa_pair()
    return HttpProviderClients(http, SourcesSettings(), tokens, cast("Any", git)).client(
        connection, Secrets(private_key=pem)
    )


async def test_a_deploy_key_is_checked_over_ssh_at_the_hosts_ssh_port() -> None:
    accepted = SshGit("ERROR: Repository not found.\nfatal: Could not read from remote repository.")
    assert await deploy_key(accepted, ssh="ssh://git@git.northwind.test:2222").verify() == "deploy key"
    assert accepted.remotes[0].url == "ssh://git@git.northwind.test:2222/agnostic/deploy-key-check.git"
    assert accepted.remotes[0].ssh_key

    refused = SshGit("git@git.northwind.test: Permission denied (publickey).")
    with pytest.raises(ProviderError, match="turned the deploy key down"):
        _ = await deploy_key(refused).verify()
    assert refused.remotes[0].url == "ssh://git@git.northwind.test/agnostic/deploy-key-check.git"
    unreachable = SshGit("ssh: connect to host git.northwind.test port 22: Connection refused")
    with pytest.raises(ProviderError, match=r"Couldn't reach git.northwind.test over SSH.*ssh://git@host:2222"):
        _ = await deploy_key(unreachable).verify()


async def test_a_deploy_key_keeps_the_clone_url_it_is_given_and_reads_the_default_branch() -> None:
    git = SshGit()
    client = deploy_key(git, ssh="ssh://git@git.northwind.test:2222")
    scp = await client.remote("northwind/agents", "git@git.northwind.test:northwind/agents.git")
    assert scp.url == "git@git.northwind.test:northwind/agents.git"
    own = await client.remote("northwind/agents", "https://git.northwind.test/northwind/agents.git")
    assert own.url == "ssh://git@git.northwind.test:2222/northwind/agents.git", "a deploy key reaches git over SSH"
    summary = await client.repo("northwind/agents")
    assert (summary.default_branch, summary.clone_url) == (
        "trunk",
        "ssh://git@git.northwind.test:2222/northwind/agents.git",
    )
    assert (await deploy_key(SshGit(head=None)).repo("northwind/agents")).default_branch == "main"


async def test_gitea_globs_keep_a_star_inside_one_folder_like_gitea() -> None:
    rules = [
        {"rule_name": "release/*", "required_approvals": 2},
        {"rule_name": "release/**", "required_approvals": 3},
        {"rule_name": "{hotfix,fix}-?", "required_approvals": 4},
        {"rule_name": "Main", "required_approvals": 1},
        {"rule_name": "m*", "required_approvals": 5},
    ]
    host = Host({"GET /api/v1/repos/northwind/agents/branch_protections": respond(rules)})
    http = host.http()
    client = clients(http).client(gitea_connection(), Secrets(token="tok"))
    assert await client.review_requirement("northwind/agents", "release/2026") == (2, [])
    assert await client.review_requirement("northwind/agents", "release/2026/rc1") == (3, []), "* stops at a /"
    assert await client.review_requirement("northwind/agents", "fix-1") == (4, [])
    assert await client.review_requirement("northwind/agents", "fix-12") == (0, [])
    assert await client.review_requirement("northwind/agents", "main") == (1, []), "a plain name wins, any case"
    assert await client.review_requirement("northwind/agents", "mine") == (5, [])
    await http.aclose()


async def test_gitea_protections_hidden_from_the_token_fall_back_to_the_branch() -> None:
    forbidden = respond({"message": "user should be an owner or a collaborator with admin write"}, 403)
    host = Host(
        {
            "GET /api/v1/repos/northwind/agents/branch_protections": forbidden,
            "GET /api/v1/repos/northwind/agents/branches/main": respond(
                {"name": "main", "protected": True, "required_approvals": 2}
            ),
            "GET /api/v1/repos/northwind/agents/branches/feature%2Fx": respond(
                {"name": "feature/x", "protected": False}
            ),
        }
    )
    http = host.http()
    client = clients(http).client(gitea_connection(), Secrets(token="tok"))
    assert await client.review_requirement("northwind/agents", "main") == (2, [])
    assert await client.review_requirement("northwind/agents", "feature/x") == (0, [])
    assert await client.review_requirement("northwind/agents", "gone") is None, "unknown, not a failure"
    await http.aclose()
