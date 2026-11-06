"""GitHub (github.com and Enterprise Server): a GitHub App installation (preferred) or a token.

A GitHub App signs a short JWT with its private key and trades it for an installation token, which expires after an
hour; tokens are cached sealed until shortly before then.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, cast
from urllib.parse import quote

import httpx
import jwt
import orjson

from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_sources.application.ports import (
    OpenedPullRequest,
    ProviderError,
    PullRequestState,
    Remote,
    RepoSummary,
)
from agnostic_sources.infrastructure.providers.base import (
    FORBIDDEN,
    NOT_FOUND,
    Api,
    already_open,
    basic,
    items,
    remote_for,
)

TOKEN_MARGIN = 300.0
ACCEPT = "application/vnd.github+json"
SEARCH_LIMIT = 256


class GitHubAppTokens:
    """Installation tokens for a GitHub App, cached (sealed) in the ephemeral store."""

    def __init__(self, client: httpx.AsyncClient, store: EphemeralStore, box: SecretBox) -> None:
        self._client = client
        self._store = store
        self._box = box

    def app_jwt(self, app_id: str, private_key: str) -> str:
        now = int(time.time())
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256")

    async def token(self, api_url: str, app_id: str, private_key: str, installation_id: str) -> str:
        # App and installation ids are only unique per GitHub host: github.com and a GitHub Enterprise Server
        # can both have app 3 / installation 7.
        host = hashlib.sha256(api_url.rstrip("/").lower().encode()).hexdigest()[:16]
        key = f"sources:gh-token:{host}:{app_id}:{installation_id}"
        cached = await self._store.get(key)
        if cached is not None:
            return self._box.open(cached.decode()).decode()
        try:
            response = await self._client.post(
                f"{api_url.rstrip('/')}/app/installations/{installation_id}/access_tokens",
                headers={"Authorization": f"Bearer {self.app_jwt(app_id, private_key)}", "Accept": ACCEPT},
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"GitHub couldn't be reached: {exc}") from exc
        if not response.is_success:
            raise ProviderError(
                f"GitHub didn't issue an installation token (HTTP {response.status_code}); check the app id, key and "
                "installation."
            )
        body = cast("dict[str, Any]", response.json())
        token = str(body["token"])
        ttl = 3600.0 - TOKEN_MARGIN
        await self._store.set(key, self._box.seal(token.encode()).encode(), ttl=ttl)
        return token

    async def installation(self, api_url: str, app_id: str, private_key: str, installation_id: str) -> str:
        """The account the installation belongs to (``northwind``)."""
        try:
            response = await self._client.get(
                f"{api_url.rstrip('/')}/app/installations/{installation_id}",
                headers={"Authorization": f"Bearer {self.app_jwt(app_id, private_key)}", "Accept": ACCEPT},
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"GitHub couldn't be reached: {exc}") from exc
        if not response.is_success:
            raise ProviderError(f"GitHub doesn't know installation {installation_id} (HTTP {response.status_code}).")
        account = cast("dict[str, Any]", orjson.loads(response.content).get("account") or {})
        return str(account.get("login") or "")


class GitHubClient(Api):
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_url: str,
        web_url: str,
        *,
        token: str | None = None,
        app: tuple[str, str, str] | None = None,
        tokens: GitHubAppTokens | None = None,
    ) -> None:
        """``app`` is ``(app_id, private_key, installation_id)``; without it, ``token`` is used as is."""
        super().__init__(client, api_url, "GitHub")
        self._api = api_url
        self._web = web_url.rstrip("/")
        self._token = token
        self._app = app
        self._tokens = tokens

    async def _bearer(self) -> str:
        if self._app is not None and self._tokens is not None:
            app_id, key, installation = self._app
            return await self._tokens.token(self._api, app_id, key, installation)
        if not self._token:
            raise ProviderError("The GitHub connection has no token.")
        return self._token

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self._bearer()}", "Accept": ACCEPT}

    async def verify(self) -> str:
        if self._app is not None and self._tokens is not None:
            app_id, key, installation = self._app
            return await self._tokens.installation(self._api, app_id, key, installation)
        user = cast("dict[str, Any]", await self.json("GET", "/user"))
        return str(user.get("login") or "")

    async def repos(self, query: str | None = None) -> list[RepoSummary]:
        if not query:
            if self._app is not None:
                found = await self.pages("/installation/repositories", key="repositories")
            else:
                found = await self.pages("/user/repos", params={"sort": "pushed"})
            return [_repo(item) for item in found]
        # Search on the server, narrowed to the accounts the connection reaches (search alone covers all of GitHub).
        seen: dict[str, RepoSummary] = {}
        for search in _searches(query, await self._owners()):
            for item in await self.pages("/search/repositories", params={"q": search}, key="items", max_pages=3):
                repo = _repo(item)
                seen.setdefault(repo.full_name, repo)
        return list(seen.values())

    async def _owners(self) -> list[str]:
        if self._app is not None and self._tokens is not None:
            app_id, key, installation = self._app
            account = await self._tokens.installation(self._api, app_id, key, installation)
            return [account] if account else []
        login = await self.verify()
        orgs = [str(item.get("login")) for item in await self.pages("/user/orgs") if item.get("login")]
        return [owner for owner in (login, *orgs) if owner]

    async def repo(self, repo: str) -> RepoSummary:
        return _repo(cast("dict[str, Any]", await self.json("GET", f"/repos/{repo}")))

    async def branches(self, repo: str) -> list[str]:
        found = await self.pages(f"/repos/{repo}/branches")
        return sorted(str(item.get("name")) for item in found if item.get("name"))

    async def remote(self, repo: str, clone_url: str | None) -> Remote:
        return remote_for(self._web, self._base, repo, clone_url, basic("x-access-token", await self._bearer()))

    async def review_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:
        status, body = await self.request(
            "GET", f"/repos/{repo}/rules/branches/{quote(branch, safe='')}", allow=frozenset({NOT_FOUND, FORBIDDEN})
        )
        # Every ruleset that applies (organisation and repository) and classic branch protection are all enforced:
        # the strictest count wins. GitHub names no approving teams here (``dismissal_restrictions`` says who may
        # dismiss reviews, not who must give them), so none are listed.
        counts: list[int] = []
        if status not in {NOT_FOUND, FORBIDDEN}:
            for rule in items(body):
                if rule.get("type") == "pull_request":
                    parameters = cast("dict[str, Any]", rule.get("parameters") or {})
                    counts.append(int(parameters.get("required_approving_review_count") or 0))
        status, body = await self.request(
            "GET",
            f"/repos/{repo}/branches/{quote(branch, safe='')}/protection/required_pull_request_reviews",
            allow=frozenset({NOT_FOUND, FORBIDDEN}),
        )
        if status == FORBIDDEN and not counts:
            return None
        if status not in {NOT_FOUND, FORBIDDEN} and isinstance(body, dict):
            counts.append(int(cast("dict[str, Any]", body).get("required_approving_review_count") or 0))
        return max(counts, default=0), []

    async def open_pull_request(self, repo: str, *, head: str, base: str, title: str, body: str) -> OpenedPullRequest:
        try:
            created = cast(
                "dict[str, Any]",
                await self.json(
                    "POST", f"/repos/{repo}/pulls", json={"title": title, "head": head, "base": base, "body": body}
                ),
            )
        except ProviderError as exc:
            # A retry after a lost answer: the pull request was opened the first time.
            if already_open(exc):
                owner = repo.split("/", 1)[0]
                params: dict[str, str | int] = {"head": f"{owner}:{head}", "base": base, "state": "open"}
                found = items(await self.json("GET", f"/repos/{repo}/pulls", params=params))
                if found:
                    return OpenedPullRequest(int(found[0]["number"]), str(found[0].get("html_url") or ""))
            raise
        return OpenedPullRequest(int(created["number"]), str(created.get("html_url") or ""))

    async def pull_request(self, repo: str, number: int) -> PullRequestState:
        data = cast("dict[str, Any]", await self.json("GET", f"/repos/{repo}/pulls/{number}"))
        head = cast("dict[str, Any]", data.get("head") or {})
        if data.get("merged") or data.get("merged_at"):
            return PullRequestState("merged", str(data.get("merge_commit_sha") or "") or None, head.get("sha"))
        return PullRequestState("closed" if data.get("state") == "closed" else "open", None, head.get("sha"))

    async def register_webhook(self, repo: str, url: str, secret: str) -> str | None:
        if self._app is not None:
            return None  # a GitHub App delivers its own webhooks, configured on the app
        created = cast(
            "dict[str, Any]",
            await self.json(
                "POST",
                f"/repos/{repo}/hooks",
                json={
                    "name": "web",
                    "active": True,
                    "events": ["push", "pull_request"],
                    "config": {"url": url, "content_type": "json", "secret": secret},
                },
            ),
        )
        return str(created.get("id")) if created.get("id") is not None else None

    async def delete_webhook(self, repo: str, hook_id: str) -> None:
        _ = await self.request("DELETE", f"/repos/{repo}/hooks/{hook_id}", allow=frozenset({NOT_FOUND}))


def _searches(query: str, owners: list[str]) -> list[str]:
    """Search queries for ``query`` in the owners' repositories, each within GitHub's 256-character limit."""
    base = f"{query.strip()[:100]} in:name"
    if not owners:
        return [base]
    searches: list[str] = []
    current = base
    for owner in owners:
        term = f" user:{owner}"
        if current != base and len(current) + len(term) > SEARCH_LIMIT:
            searches.append(current)
            current = base
        current += term
    searches.append(current)
    return searches


def _repo(data: dict[str, Any]) -> RepoSummary:
    return RepoSummary(
        full_name=str(data.get("full_name") or ""),
        default_branch=str(data.get("default_branch") or "main"),
        private=bool(data.get("private", True)),
        clone_url=data.get("clone_url"),
    )
