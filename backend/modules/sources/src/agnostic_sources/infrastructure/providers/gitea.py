"""Gitea and Forgejo (Forgejo keeps the Gitea API): one client for both."""

from __future__ import annotations

import re
from functools import lru_cache
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
from agnostic_sources.domain.outcomes import team_label
from agnostic_sources.infrastructure.providers.base import FORBIDDEN, NOT_FOUND, UNPROCESSABLE, Api, basic


class GiteaClient(Api):
    def __init__(self, client: httpx.AsyncClient, api_url: str, web_url: str, token: str, kind: str) -> None:
        super().__init__(client, api_url, "Forgejo" if kind == "forgejo" else "Gitea")
        self._web = web_url.rstrip("/")
        self._token = token
        self._kind = kind
        self._login: str | None = None
        self._user_id: int | None = None

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self._token}", "Accept": "application/json"}

    async def verify(self) -> str:
        user = cast("dict[str, Any]", await self.json("GET", "/user"))
        self._login = str(user.get("login") or user.get("username") or "")
        user_id = user.get("id")
        self._user_id = int(user_id) if isinstance(user_id, int) else None
        return self._login

    async def repos(self, query: str | None = None) -> list[RepoSummary]:
        if not query:
            # Owned, collaborated on and through the user's organizations: what the token reaches.
            found = await self.pages("/user/repos", page_param="limit")
            return [_repo(item) for item in found]
        if self._user_id is None:
            _ = await self.verify()
        params: dict[str, str | int] = {"q": query}
        if self._user_id is not None:
            # Without ``uid`` the search covers every public repository on the server.
            params["uid"] = self._user_id
        found = await self.pages("/repos/search", params=params, key="data", page_param="limit")
        return [_repo(item) for item in found]

    async def repo(self, repo: str) -> RepoSummary:
        return _repo(cast("dict[str, Any]", await self.json("GET", f"/repos/{_path(repo)}")))

    async def branches(self, repo: str) -> list[str]:
        found = await self.pages(f"/repos/{_path(repo)}/branches", page_param="limit")
        return sorted(str(item.get("name")) for item in found if item.get("name"))

    async def remote(self, repo: str, clone_url: str | None) -> Remote:
        login = self._login or await self.verify()
        return Remote(clone_url or f"{self._web}/{repo}.git", header=basic(login or "agnostic", self._token))

    async def review_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:
        try:
            rules = await self.pages(f"/repos/{_path(repo)}/branch_protections", page_param="limit")
        except ProviderError as exc:
            status = exc.extra.get("upstream_status")
            if status == NOT_FOUND:
                return (0, [])
            if status == FORBIDDEN:
                # Reading protection rules takes admin on the repository; the branch itself says what applies.
                return await self._branch_requirement(repo, branch)
            raise
        rule = _protection(rules, branch)
        if rule is None:
            return (0, [])
        teams = [team_label(str(team)) for team in cast("list[Any]", rule.get("approvals_whitelist_teams") or [])]
        return int(rule.get("required_approvals") or 0), teams

    async def _branch_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:
        """The approvals the branch's effective rule asks for (its teams aren't shown); ``None`` when unknown."""
        try:
            data = await self.json("GET", f"/repos/{_path(repo)}/branches/{quote(branch, safe='')}")
        except ProviderError:
            return None
        if not isinstance(data, dict):
            return None
        found = cast("dict[str, Any]", data)
        if not found.get("protected"):
            return (0, [])
        approvals = found.get("required_approvals")
        return (approvals, []) if isinstance(approvals, int) else None

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
        hook: dict[str, Any] = {
            "type": "forgejo" if self._kind == "forgejo" else "gitea",
            "active": True,
            "events": ["push", "pull_request"],
            "config": {"url": url, "content_type": "json", "secret": secret},
        }
        status, created = await self.request(
            "POST", f"/repos/{_path(repo)}/hooks", json=hook, allow=frozenset({UNPROCESSABLE})
        )
        if status == UNPROCESSABLE and hook["type"] == "forgejo":
            # Forgejo before its own hook type (and Gitea behind a Forgejo connection) takes the Gitea one.
            created = await self.json("POST", f"/repos/{_path(repo)}/hooks", json={**hook, "type": "gitea"})
        elif status == UNPROCESSABLE:
            raise ProviderError(f"{self._host} refused the webhook: {created}")
        data = cast("dict[str, Any]", created) if isinstance(created, dict) else {}
        return str(data.get("id")) if data.get("id") is not None else None

    async def delete_webhook(self, repo: str, hook_id: str) -> None:
        _ = await self.request("DELETE", f"/repos/{_path(repo)}/hooks/{hook_id}", allow=frozenset({NOT_FOUND}))


def _path(repo: str) -> str:
    owner, _, name = repo.partition("/")
    return f"{quote(owner, safe='')}/{quote(name, safe='')}"


def _protection(rules: list[dict[str, Any]], branch: str) -> dict[str, Any] | None:
    """The rule Gitea applies to ``branch``: by priority, plain names before globs, then oldest first.

    Names match case-insensitively, the way Gitea matches them.
    """
    named = [(str(rule.get("rule_name") or rule.get("branch_name") or ""), rule) for rule in rules]
    ordered = sorted(
        (item for item in named if item[0]),
        key=lambda item: (_priority(item[1]), bool(_SPECIAL.search(item[0]))),
    )
    for name, rule in ordered:
        if _glob(name.lower()).fullmatch(branch.lower()):
            return rule
    return None


_SPECIAL = re.compile(r"[*?\[\]{}\\]")


def _priority(rule: dict[str, Any]) -> int:
    value = rule.get("priority")
    return value if isinstance(value, int) else 0


@lru_cache(maxsize=256)
def _glob(pattern: str) -> re.Pattern[str]:
    """Gitea's branch globs (gobwas/glob with ``/`` as the separator) as a regular expression.

    ``*`` and ``?`` stay inside one path segment, ``**`` crosses them, ``[abc]`` / ``[!a-z]`` are character classes,
    ``{a,b}`` alternatives, and a backslash escapes the next character.
    """
    regex, _ = _translate(pattern, 0, inside=False)
    try:
        return re.compile(regex)
    except re.error:
        return re.compile(re.escape(pattern))


def _translate(pattern: str, start: int, *, inside: bool) -> tuple[str, int]:  # noqa: C901, PLR0912
    out: list[str] = []
    index = start
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            out.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if char == "*":
            if pattern.startswith("**", index):
                out.append(".*")
                index += 2
            else:
                out.append("[^/]*")
                index += 1
            continue
        if char == "?":
            out.append("[^/]")
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end == -1:
                out.append(re.escape(char))
            else:
                body = pattern[index + 1 : end]
                negate = body.startswith("!")
                body = body.removeprefix("!").replace("\\", "\\\\")
                out.append(f"[{'^' if negate else ''}{body}]")
                index = end + 1
                continue
        elif char == "{":
            options: list[str] = []
            index += 1
            while True:
                option, index = _translate(pattern, index, inside=True)
                options.append(option)
                if index >= len(pattern) or pattern[index] == "}":
                    break
                index += 1  # past the comma
            out.append(f"(?:{'|'.join(options)})")
        elif inside and char in ",}":
            return "".join(out), index
        else:
            out.append(re.escape(char))
        index += 1
    return "".join(out), index


def _repo(data: dict[str, Any]) -> RepoSummary:
    return RepoSummary(
        full_name=str(data.get("full_name") or ""),
        default_branch=str(data.get("default_branch") or "main"),
        private=bool(data.get("private", True)),
        clone_url=data.get("clone_url"),
    )
