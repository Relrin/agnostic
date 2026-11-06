"""Repository names, clone URLs, and keeping secrets out of anything git prints."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from agnostic_sources.domain.model import SourceRuleError

_REPO = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+){1,5}")
_BRANCH = re.compile(r"[^\x00-\x20~^:?*\[\\\x7f]{1,200}")
_SCP = re.compile(r"[A-Za-z0-9._-]+@(?P<host>[A-Za-z0-9.-]+):(?!//)(?P<path>\S+)")
"""The scp-like SSH address ``git@host:owner/repo.git``."""
_USERINFO = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)
_HEADER = re.compile(r"(authorization:\s*)(\S+\s+)?\S+", re.IGNORECASE)
_TOKENS = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|x-access-token:[^@\s]+)")


def check_repo(repo: str) -> str:
    repo = repo.strip().strip("/").removesuffix(".git")
    if not _REPO.fullmatch(repo) or ".." in repo:
        raise SourceRuleError(f"{repo!r} isn't a repository name like owner/name.")
    return repo


def check_branch(branch: str) -> str:
    branch = branch.strip()
    if not _BRANCH.fullmatch(branch) or ".." in branch or branch.startswith(("-", "/")) or branch.endswith("/"):
        raise SourceRuleError(f"{branch!r} isn't a branch name.")
    return branch


def check_clone_url(url: str, *, allow_file: bool = False) -> str:
    url = url.strip()
    if (scp := _SCP.fullmatch(url)) is not None:
        if scp.group("path").startswith(("-", "/")) or ".." in scp.group("path"):
            raise SourceRuleError(f"{url!r} isn't a repository path.")
        return url
    parts = urlsplit(url)
    if parts.scheme == "file" and allow_file:
        return url
    if parts.scheme not in {"https", "http", "ssh"}:
        raise SourceRuleError("Clone over https or ssh.")
    if parts.password or (parts.username and parts.scheme != "ssh"):
        raise SourceRuleError("Leave credentials out of the URL; the connection supplies them.")
    if not parts.hostname:
        raise SourceRuleError(f"{url!r} has no host.")
    return url


def is_ssh_url(url: str) -> bool:
    """``ssh://git@host:2222/owner/repo.git`` or the scp-like ``git@host:owner/repo.git``."""
    return urlsplit(url).scheme == "ssh" or _SCP.fullmatch(url) is not None


def ssh_host(url: str) -> str:
    """``host`` or ``host:port`` of an SSH clone URL, for messages."""
    if (scp := _SCP.fullmatch(url)) is not None:
        return scp.group("host")
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port}" if parts.port else parts.hostname or url


def ssh_address(value: str) -> str:
    """A host's SSH address, ``ssh://git@host:2222`` (where deploy keys reach it when SSH isn't on port 22)."""
    parts = urlsplit(value.strip().rstrip("/"))
    try:
        _ = parts.port
    except ValueError as exc:
        raise SourceRuleError(f"{value} has a port that isn't a number.") from exc
    if parts.scheme != "ssh" or not parts.hostname or parts.password or parts.path or parts.query:
        raise SourceRuleError(f"{value} isn't an SSH address like ssh://git@git.example.com:2222.")
    return value.strip().rstrip("/")


def redact(text: str) -> str:
    text = _USERINFO.sub(r"\g<scheme>***@", text)
    text = _HEADER.sub(r"\1***", text)
    return _TOKENS.sub("***", text)
