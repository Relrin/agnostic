"""GitLab (gitlab.com and self-managed) with a project, group or personal access token."""

from __future__ import annotations

from typing import Any, cast
from urllib.parse import quote

import httpx

from agnostic_sources.application.ports import OpenedPullRequest, PullRequestState, Remote, RepoSummary
from agnostic_sources.infrastructure.providers.base import FORBIDDEN, NOT_FOUND, Api, basic, items


class GitLabClient(Api):
    def __init__(self, client: httpx.AsyncClient, api_url: str, web_url: str, token: str) -> None:
        super().__init__(client, api_url, "GitLab")
        self._web = web_url.rstrip("/")
        self._token = token

    async def headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self._token, "Accept": "application/json"}

    async def verify(self) -> str:
        user = cast("dict[str, Any]", await self.json("GET", "/user"))
        return str(user.get("username") or user.get("name") or "")

    async def repos(self, query: str | None = None) -> list[RepoSummary]:
        params: dict[str, str | int] = {"membership": "true", "simple": "true", "per_page": 50}
        if query:
            params["search"] = query
        return [_repo(item) for item in items(await self.json("GET", "/projects", params=params))]

    async def repo(self, repo: str) -> RepoSummary:
        return _repo(cast("dict[str, Any]", await self.json("GET", f"/projects/{_id(repo)}")))

    async def branches(self, repo: str) -> list[str]:
        body = await self.json("GET", f"/projects/{_id(repo)}/repository/branches", params={"per_page": 100})
        return sorted(str(item.get("name")) for item in items(body) if item.get("name"))

    async def remote(self, repo: str, clone_url: str | None) -> Remote:
        return Remote(clone_url or f"{self._web}/{repo}.git", header=basic("oauth2", self._token))

    async def review_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:  # noqa: ARG002
        status, body = await self.request(
            "GET", f"/projects/{_id(repo)}/approval_rules", allow=frozenset({NOT_FOUND, FORBIDDEN})
        )
        if status in {NOT_FOUND, FORBIDDEN}:
            return None
        rules = items(body)
        required = sum(int(rule.get("approvals_required") or 0) for rule in rules)
        teams = [str(rule.get("name")) for rule in rules if rule.get("approvals_required") and rule.get("name")]
        return required, teams

    async def open_pull_request(self, repo: str, *, head: str, base: str, title: str, body: str) -> OpenedPullRequest:
        created = cast(
            "dict[str, Any]",
            await self.json(
                "POST",
                f"/projects/{_id(repo)}/merge_requests",
                json={"source_branch": head, "target_branch": base, "title": title, "description": body},
            ),
        )
        return OpenedPullRequest(int(created["iid"]), str(created.get("web_url") or ""))

    async def pull_request(self, repo: str, number: int) -> PullRequestState:
        data = cast("dict[str, Any]", await self.json("GET", f"/projects/{_id(repo)}/merge_requests/{number}"))
        state = str(data.get("state") or "")
        head = data.get("sha")
        if state == "merged":
            sha = data.get("merge_commit_sha") or data.get("squash_commit_sha")
            return PullRequestState("merged", str(sha) if sha else None, head)
        return PullRequestState("closed" if state in {"closed", "locked"} else "open", None, head)

    async def register_webhook(self, repo: str, url: str, secret: str) -> str | None:
        created = cast(
            "dict[str, Any]",
            await self.json(
                "POST",
                f"/projects/{_id(repo)}/hooks",
                json={"url": url, "token": secret, "push_events": True, "merge_requests_events": True},
            ),
        )
        return str(created.get("id")) if created.get("id") is not None else None

    async def delete_webhook(self, repo: str, hook_id: str) -> None:
        _ = await self.request("DELETE", f"/projects/{_id(repo)}/hooks/{hook_id}", allow=frozenset({NOT_FOUND}))


def _id(repo: str) -> str:
    return quote(repo, safe="")


def _repo(data: dict[str, Any]) -> RepoSummary:
    return RepoSummary(
        full_name=str(data.get("path_with_namespace") or ""),
        default_branch=str(data.get("default_branch") or "main"),
        private=data.get("visibility") != "public",
        clone_url=data.get("http_url_to_repo"),
    )
