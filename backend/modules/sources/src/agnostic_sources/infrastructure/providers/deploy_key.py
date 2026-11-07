"""Deploy keys: an SSH key for one repository, on any git host.

Git reads and pushes over SSH; the host's API (pull requests, webhooks, repository lists, branch protection) isn't
reachable with it.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from agnostic_sources.application.ports import (
    GitError,
    GitRepo,
    OpenedPullRequest,
    ProviderError,
    PullRequestState,
    Remote,
    RepoSummary,
)
from agnostic_sources.domain.remote import is_ssh_url, ssh_host

# Built from their parts: written out one after another, the PEM headers read as a key block to secret scanners.
_KEY_HEADERS = tuple(f"-----BEGIN {kind}PRIVATE KEY-----" for kind in ("OPENSSH ", "RSA ", "EC ", ""))
NO_API = (
    "A deploy key reaches the repository over SSH only; opening pull requests needs a token or the GitHub App. "
    "Commit straight to the branch, or don't write back."
)
PROBE_REPO = "agnostic/deploy-key-check"
"""A repository no host has: asking for it tells whether the host accepts the key without needing the real one."""
_REFUSED = ("Permission denied", "publickey")
_BAD_KEY = ("invalid format", "libcrypto", "no such identity", "bad permissions")
_UNREACHABLE = (
    "Could not resolve hostname",
    "Connection refused",
    "Connection timed out",
    "Operation timed out",
    "No route to host",
    "Network is unreachable",
    "Connection closed",
    "Connection reset",
    "Host key verification failed",
    "took longer than",
    "cannot run ssh",
)


def ssh_url(web_url: str, repo: str, ssh_address: str | None = None) -> str:
    """The repository over SSH, at the connection's SSH address (keeping its port) or else the server's host.

    The SSH address is ``ssh://git@host:2222`` when SSH isn't on port 22 (Gitea and Forgejo often use 2222).
    """
    if ssh_address:
        parts = urlsplit(ssh_address)
        user, host, port = parts.username or "git", parts.hostname or "", parts.port
    else:
        user, host, port = "git", urlsplit(web_url).hostname or web_url, None
    if ":" in host:
        host = f"[{host}]"
    return f"ssh://{user}@{host}{f':{port}' if port else ''}/{repo}.git"


class DeployKeyClient:
    def __init__(
        self, git: GitRepo | None, web_url: str, private_key: str, host: str, ssh_address: str | None = None
    ) -> None:
        self._git = git
        self._web = web_url.rstrip("/")
        self._key = private_key
        self._host = host
        self._ssh = ssh_address

    async def verify(self) -> str:
        key = self._key.strip()
        if not key.startswith(_KEY_HEADERS) or "PRIVATE KEY-----" not in key.splitlines()[-1]:
            raise ProviderError("The deploy key isn't an SSH private key (PEM or OpenSSH).")
        if self._git is not None:
            await self._probe(self._git)
        return "deploy key"

    async def _probe(self, git: GitRepo) -> None:
        """Ask the host over SSH for a repository it doesn't have: one that turns the key down says so before that."""
        remote = Remote(ssh_url(self._web, PROBE_REPO, self._ssh), ssh_key=self._key)
        where = ssh_host(remote.url)
        try:
            _ = await git.branches("", remote)
        except GitError as exc:
            detail = str(exc)
            if any(marker in detail for marker in _REFUSED):
                raise ProviderError(
                    f"{where} turned the deploy key down; add its public half to the repository's deploy keys."
                ) from exc
            if any(marker.lower() in detail.lower() for marker in _BAD_KEY):
                raise ProviderError(f"ssh couldn't use the deploy key: {detail}") from exc
            if any(marker in detail for marker in _UNREACHABLE):
                raise ProviderError(
                    f"Couldn't reach {where} over SSH ({detail}); check the server URL, or give the SSH address "
                    "(ssh://git@host:2222) when SSH isn't on port 22."
                ) from exc
            # Anything else came after the host accepted the key: it has no such repository, as expected.

    async def repos(self, query: str | None = None) -> list[RepoSummary]:  # noqa: ARG002
        return []  # the key is for one repository, which the person names

    async def repo(self, repo: str) -> RepoSummary:
        remote = await self.remote(repo, None)
        branch: str | None = None
        if self._git is not None:
            try:
                branch = await self._git.default_branch(remote)
            except GitError as exc:
                raise ProviderError(f"Couldn't read {repo} over SSH: {exc}") from exc
        return RepoSummary(full_name=repo, default_branch=branch or "main", clone_url=remote.url)

    async def branches(self, repo: str) -> list[str]:
        if self._git is None:
            return []
        return await self._git.branches("", await self.remote(repo, None))

    async def remote(self, repo: str, clone_url: str | None) -> Remote:
        url = clone_url if clone_url and is_ssh_url(clone_url) else ssh_url(self._web, repo, self._ssh)
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
