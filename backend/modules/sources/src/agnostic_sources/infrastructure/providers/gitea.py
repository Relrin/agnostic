"""Gitea and Forgejo (Forgejo keeps the Gitea API): one client for both."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

import httpx

from agnostic_sources.application.ports import OpenedPullRequest, PullRequestState, Remote, RepoSummary
from agnostic_sources.domain.outcomes import team_label
from agnostic_sources.infrastructure.providers.base import NOT_FOUND, Api, basic, items


class GiteaClient(Api):
    def __init__(self, client: httpx.AsyncClient, api_url: str, web_url: str, token: str, kind: str) -> None:
        super().__init__(client, api_url, "Forgejo" if kind == "forgejo" else "Gitea")
        self._web = web_url.rstrip("/")
        self._token = token
        self._kind = kind
        self._login: str | None = None

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self._token}", "Accept": "application/json"}

    async def verify(self) -> str:
        user = cast("dict[str, Any]", await self.json("GET", "/user"))
        self._login = str(user.get("login") or user.get("username") or "")
        return self._login

    async def repos(self, query: str | None = None) -> list[RepoSummary]:
        body = await self.json("GET", "/repos/search", params={"q": query or "", "limit": 50})
        return [_repo(item) for item in items(body, "data")]

    async def repo(self, repo: str) -> RepoSummary:
        return _repo(cast("dict[str, Any]", await self.json("GET", f"/repos/{_path(repo)}")))

    async def branches(self, repo: str) -> list[str]:
        body = await self.json("GET", f"/repos/{_path(repo)}/branches", params={"limit": 100})
        return sorted(str(item.get("name")) for item in items(body) if item.get("name"))

    async def remote(self, repo: str, clone_url: str | None) -> Remote:
        login = self._login or await self.verify()
        return Remote(clone_url or f"{self._web}/{repo}.git", header=basic(login or "agnostic", self._token))

    async def review_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:
        status, body = await self.request(
            "GET", f"/repos/{_path(repo)}/branch_protections/{quote(branch, safe='')}", allow=frozenset({NOT_FOUND})
        )
        if status == NOT_FOUND or not isinstance(body, dict):
            return (0, [])
        data = cast("dict[str, Any]", body)
        teams = [team_label(str(team)) for team in cast("list[Any]", data.get("approvals_whitelist_teams") or [])]
        return int(data.get("required_approvals") or 0), teams

    async def open_pull_request(self, repo: str, *, head: str, base: str, title: str, body: str) -> OpenedPullRequest:
        created = cast(
            "dict[str, Any]",
            await self.json(
                "POST", f"/repos/{_path(repo)}/pulls", json={"head": head, "base": base, "title": title, "body": body}
            ),
        )
        return OpenedPullRequest(int(created["number"]), str(created.get("html_url") or ""))

    async def pull_request(self, repo: str, number: int) -> PullRequestState:
        data = cast("dict[str, Any]", await self.json("GET", f"/repos/{_path(repo)}/pulls/{number}"))
        head = cast("dict[str, Any]", data.get("head") or {})
        if data.get("merged"):
            return PullRequestState("merged", str(data.get("merge_commit_sha") or "") or None, head.get("sha"))
        return PullRequestState("closed" if data.get("state") == "closed" else "open", None, head.get("sha"))

    async def register_webhook(self, repo: str, url: str, secret: str) -> str | None:
        created = cast(
            "dict[str, Any]",
            await self.json(
                "POST",
                f"/repos/{_path(repo)}/hooks",
                json={
                    "type": "forgejo" if self._kind == "forgejo" else "gitea",
                    "active": True,
                    "events": ["push", "pull_request"],
                    "config": {"url": url, "content_type": "json", "secret": secret},
                },
            ),
        )
        return str(created.get("id")) if created.get("id") is not None else None

    async def delete_webhook(self, repo: str, hook_id: str) -> None:
        _ = await self.request("DELETE", f"/repos/{_path(repo)}/hooks/{hook_id}", allow=frozenset({NOT_FOUND}))


def _path(repo: str) -> str:
    owner, _, name = repo.partition("/")
    return f"{quote(owner, safe='')}/{quote(name, safe='')}"


def _repo(data: dict[str, Any]) -> RepoSummary:
    return RepoSummary(
        full_name=str(data.get("full_name") or ""),
        default_branch=str(data.get("default_branch") or "main"),
        private=bool(data.get("private", True)),
        clone_url=data.get("clone_url"),
    )
