"""A fake Gitea (the API code sources use) in front of an :class:`Upstream` repository on disk.

Pull requests are real branches in the upstream bare repository; ``merge`` merges one as the host's "Merge" button
does. Webhooks the source registers are kept, so tests can send deliveries signed with their secret. ``refuse_token``
makes the host turn the token down (every fetch fails), and ``fail_pulls`` makes the next pull requests fail to open.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Request

from agnostic_sources.domain.webhooks import hmac_sha256
from tests.support.git_repo import Upstream

TOKEN = "gitea-token-for-tests"


@dataclass
class FakePull:
    number: int
    head: str
    base: str
    title: str
    body: str
    state: str = "open"
    merged: bool = False
    merge_sha: str | None = None


@dataclass
class FakeGitea:
    upstream: Upstream
    repo: str = "northwind/agent-platform"
    required_approvals: int = 1
    teams: list[str] = field(default_factory=lambda: ["platform"])
    pulls: dict[int, FakePull] = field(default_factory=dict[int, FakePull])
    hooks: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    refuse_token: bool = False
    fail_pulls: int = 0

    def __post_init__(self) -> None:
        self.app = self._build()

    def _check(self, authorization: str | None) -> None:
        if self.refuse_token or authorization != f"token {TOKEN}":
            raise HTTPException(401, "bad token")

    def _repo(self, owner: str, name: str) -> None:
        if f"{owner}/{name}" != self.repo:
            raise HTTPException(404, "repository not found")

    def _summary(self) -> dict[str, Any]:
        return {
            "full_name": self.repo,
            "default_branch": self.upstream.branch,
            "private": True,
            "clone_url": self.upstream.url,
        }

    def _build(self) -> FastAPI:  # noqa: C901
        app = FastAPI()
        fake = self

        @app.get("/api/v1/user")
        async def user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
            fake._check(authorization)
            return {"id": 7, "login": "agnostic-bot"}

        @app.get("/api/v1/user/repos")
        async def user_repos(authorization: Annotated[str | None, Header()] = None) -> list[Any]:
            fake._check(authorization)
            return [fake._summary()]

        @app.get("/api/v1/repos/search")
        async def search(
            q: str = "", uid: int | None = None, authorization: Annotated[str | None, Header()] = None
        ) -> dict[str, Any]:
            fake._check(authorization)
            found = [fake._summary()] if uid == 7 and q.lower() in fake.repo.lower() else []
            return {"ok": True, "data": found}

        @app.get("/api/v1/repos/{owner}/{name}")
        async def repo(owner: str, name: str, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
            fake._check(authorization)
            fake._repo(owner, name)
            return fake._summary()

        @app.get("/api/v1/repos/{owner}/{name}/branches")
        async def branches(owner: str, name: str, authorization: Annotated[str | None, Header()] = None) -> list[Any]:
            fake._check(authorization)
            fake._repo(owner, name)
            return [{"name": branch} for branch in fake.upstream.branches()]

        @app.get("/api/v1/repos/{owner}/{name}/branch_protections")
        async def protections(
            owner: str, name: str, authorization: Annotated[str | None, Header()] = None
        ) -> list[dict[str, Any]]:
            fake._check(authorization)
            fake._repo(owner, name)
            return [
                {"rule_name": "release/*", "required_approvals": 3, "approvals_whitelist_teams": []},
                {
                    "rule_name": fake.upstream.branch,
                    "required_approvals": fake.required_approvals,
                    "approvals_whitelist_teams": fake.teams,
                },
            ]

        @app.post("/api/v1/repos/{owner}/{name}/pulls", status_code=201)
        async def open_pull(
            owner: str, name: str, request: Request, authorization: Annotated[str | None, Header()] = None
        ) -> dict[str, Any]:
            fake._check(authorization)
            fake._repo(owner, name)
            body = await request.json()
            if fake.fail_pulls > 0:
                fake.fail_pulls -= 1
                raise HTTPException(500, "the host had a hiccup")
            if body["head"] not in fake.upstream.branches():
                raise HTTPException(422, "head branch doesn't exist")
            number = len(fake.pulls) + 1
            fake.pulls[number] = FakePull(number, body["head"], body["base"], body["title"], body.get("body", ""))
            return {"number": number, "html_url": f"http://gitea.test/{fake.repo}/pulls/{number}"}

        @app.get("/api/v1/repos/{owner}/{name}/pulls/{number}")
        async def get_pull(
            owner: str, name: str, number: int, authorization: Annotated[str | None, Header()] = None
        ) -> dict[str, Any]:
            fake._check(authorization)
            fake._repo(owner, name)
            pull = fake.pulls.get(number)
            if pull is None:
                raise HTTPException(404, "no such pull request")
            return {
                "number": pull.number,
                "state": pull.state,
                "merged": pull.merged,
                "merge_commit_sha": pull.merge_sha,
                "head": {"sha": fake.upstream.head_or_none(pull.head)},
            }

        @app.post("/api/v1/repos/{owner}/{name}/hooks", status_code=201)
        async def add_hook(
            owner: str, name: str, request: Request, authorization: Annotated[str | None, Header()] = None
        ) -> dict[str, Any]:
            fake._check(authorization)
            fake._repo(owner, name)
            body = await request.json()
            hook_id = str(len(fake.hooks) + 1)
            fake.hooks[hook_id] = body
            return {"id": int(hook_id)}

        @app.delete("/api/v1/repos/{owner}/{name}/hooks/{hook_id}", status_code=204)
        async def delete_hook(
            owner: str, name: str, hook_id: str, authorization: Annotated[str | None, Header()] = None
        ) -> None:
            fake._check(authorization)
            fake._repo(owner, name)
            _ = fake.hooks.pop(hook_id, None)

        return app

    # ---------------------------------------------------------------- what the host does on its own

    def merge(self, number: int) -> str:
        pull = self.pulls[number]
        sha = self.upstream.merge(pull.head)
        pull.state, pull.merged, pull.merge_sha = "closed", True, sha
        return sha

    def close(self, number: int) -> None:
        """Close a pull request without merging it."""
        self.pulls[number].state = "closed"

    def secret(self) -> str:
        assert self.hooks, "the source registered no webhook"
        return str(next(iter(self.hooks.values()))["config"]["secret"])

    def delivery(
        self, event: str, payload: dict[str, Any], *, secret: str | None = None
    ) -> tuple[bytes, dict[str, str]]:
        body = json.dumps({**payload, "repository": {"full_name": self.repo}}).encode()
        signature = hmac_sha256(secret if secret is not None else self.secret(), body)
        headers = {
            "Content-Type": "application/json",
            "X-Gitea-Event": event,
            "X-Gitea-Delivery": str(uuid.uuid4()),
            "X-Gitea-Signature": signature,
        }
        return body, headers

    def push(self, before: str | None, after: str) -> tuple[bytes, dict[str, str]]:
        return self.delivery(
            "push",
            {"ref": f"refs/heads/{self.upstream.branch}", "before": before, "after": after, "pusher": {"login": "sam"}},
        )

    def pull_merged(self, number: int) -> tuple[bytes, dict[str, str]]:
        pull = self.pulls[number]
        return self.delivery(
            "pull_request",
            {
                "action": "closed",
                "number": number,
                "pull_request": {"number": number, "merged": pull.merged, "merge_commit_sha": pull.merge_sha},
            },
        )
