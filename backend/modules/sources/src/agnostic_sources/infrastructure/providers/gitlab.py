"""GitLab (gitlab.com and self-managed) with a project, group or personal access token."""

from __future__ import annotations

import re
from typing import Any, cast
from urllib.parse import quote

import httpx

from agnostic_sources.application.ports import (
    OpenedPullRequest,
    ProviderError,
    PullRequestState,
    Remote,
    RepoSummary,
)
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
        # Not ``simple=true``: the simple view leaves out ``visibility``, so every project would read as private.
        params: dict[str, str | int] = {"membership": "true", "order_by": "last_activity_at"}
        if query:
            params["search"] = query
        return [_repo(item) for item in await self.pages("/projects", params=params)]

    async def repo(self, repo: str) -> RepoSummary:
        return _repo(cast("dict[str, Any]", await self.json("GET", f"/projects/{_id(repo)}")))

    async def branches(self, repo: str) -> list[str]:
        found = await self.pages(f"/projects/{_id(repo)}/repository/branches")
        return sorted(str(item.get("name")) for item in found if item.get("name"))

    async def remote(self, repo: str, clone_url: str | None) -> Remote:
        return Remote(clone_url or f"{self._web}/{repo}.git", header=basic("oauth2", self._token))

    async def review_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:
        status, body = await self.request(
            "GET", f"/projects/{_id(repo)}/approval_rules", allow=frozenset({NOT_FOUND, FORBIDDEN})
        )
        if status in {NOT_FOUND, FORBIDDEN}:
            return None
        protected: list[str] | None = None
        unknown = False
        applying: list[dict[str, Any]] = []
        for rule in items(body):
            if rule.get("rule_type") == "report_approver":
                continue  # security and coverage approvals: asked for only when a report finds something
            names = [str(item.get("name") or "") for item in items(rule.get("protected_branches"))]
            if rule.get("applies_to_all_protected_branches"):
                if protected is None and not unknown:
                    protected = await self._protected(repo)
                    unknown = protected is None
                if protected is None:
                    # The protected branches can't be read with this token: the branch a merge request targets
                    # is protected almost always, so count the rule rather than ask for too few approvals.
                    applying.append(rule)
                    continue
                names = protected
            elif not names:
                applying.append(rule)  # a rule without branches applies to every branch
                continue
            if any(_matches(name, branch) for name in names):
                applying.append(rule)
        # Every applying rule must be met on its own: the strictest one is what the merge request needs.
        required = max((int(rule.get("approvals_required") or 0) for rule in applying), default=0)
        teams = [str(rule.get("name")) for rule in applying if rule.get("approvals_required") and rule.get("name")]
        return required, teams

    async def _protected(self, repo: str) -> list[str] | None:
        """The project's protected branch names (``None`` when the token can't read them)."""
        try:
            found = await self.pages(f"/projects/{_id(repo)}/protected_branches")
        except ProviderError:
            return None
        return [str(item.get("name")) for item in found if item.get("name")]

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
        # ``locked`` is a merge in progress: still open, so the next refresh sees it merged.
        return PullRequestState("closed" if state == "closed" else "open", None, head)

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


def _matches(pattern: str, branch: str) -> bool:
    """GitLab protected branch names are exact, or wildcards where ``*`` matches anything (``release/*``)."""
    if "*" not in pattern:
        return pattern == branch
    return re.fullmatch(".*".join(re.escape(part) for part in pattern.split("*")), branch) is not None


def _repo(data: dict[str, Any]) -> RepoSummary:
    return RepoSummary(
        full_name=str(data.get("path_with_namespace") or ""),
        default_branch=str(data.get("default_branch") or "main"),
        private=data.get("visibility") != "public",
        clone_url=data.get("http_url_to_repo"),
    )
