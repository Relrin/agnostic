"""Deploy keys: an SSH key for one repository, on any git host.

Git reads and pushes over SSH; the host's API (pull requests, webhooks, repository lists, branch protection) isn't
reachable with it.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from agnostic_sources.application.ports import (
    GitRepo,
    OpenedPullRequest,
    ProviderError,
    PullRequestState,
    Remote,
    RepoSummary,
)

_KEY_HEADERS = (
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
)
NO_API = (
    "A deploy key reaches the repository over SSH only; opening pull requests needs a token or the GitHub App. "
    "Commit straight to the branch, or don't write back."
)


def ssh_url(web_url: str, repo: str) -> str:
    host = urlsplit(web_url).hostname or web_url
    return f"ssh://git@{host}/{repo}.git"


class DeployKeyClient:
    def __init__(self, git: GitRepo | None, web_url: str, private_key: str, host: str) -> None:
        self._git = git
        self._web = web_url.rstrip("/")
        self._key = private_key
        self._host = host

    async def verify(self) -> str:
        key = self._key.strip()
        if not key.startswith(_KEY_HEADERS) or "PRIVATE KEY-----" not in key.splitlines()[-1]:
            raise ProviderError("The deploy key isn't an SSH private key (PEM or OpenSSH).")
        return "deploy key"

    async def repos(self, query: str | None = None) -> list[RepoSummary]:  # noqa: ARG002
        return []  # the key is for one repository, which the person names

    async def repo(self, repo: str) -> RepoSummary:
        return RepoSummary(full_name=repo, default_branch="main", clone_url=ssh_url(self._web, repo))

    async def branches(self, repo: str) -> list[str]:
        if self._git is None:
            return []
        return await self._git.branches("", await self.remote(repo, None))

    async def remote(self, repo: str, clone_url: str | None) -> Remote:
        url = clone_url if clone_url and urlsplit(clone_url).scheme == "ssh" else ssh_url(self._web, repo)
        return Remote(url, ssh_key=self._key)

    async def review_requirement(self, repo: str, branch: str) -> tuple[int, list[str]] | None:  # noqa: ARG002
        return None

    async def open_pull_request(
        self,
        repo: str,  # noqa: ARG002
        *,
        head: str,  # noqa: ARG002
        base: str,  # noqa: ARG002
        title: str,  # noqa: ARG002
        body: str,  # noqa: ARG002
    ) -> OpenedPullRequest:
        raise ProviderError(NO_API)

    async def pull_request(self, repo: str, number: int) -> PullRequestState:  # noqa: ARG002
        raise ProviderError(f"{self._host} pull requests can't be read with a deploy key.")

    async def register_webhook(self, repo: str, url: str, secret: str) -> str | None:  # noqa: ARG002
        return None  # without the API, Studio fetches on its schedule

    async def delete_webhook(self, repo: str, hook_id: str) -> None:  # noqa: ARG002
        return None
