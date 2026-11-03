"""Repository names, clone URLs, and keeping secrets out of anything git prints."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from agnostic_sources.domain.model import SourceRuleError

_REPO = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+){1,5}")
_BRANCH = re.compile(r"[^\x00-\x20~^:?*\[\\\x7f]{1,200}")
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


def redact(text: str) -> str:
    text = _USERINFO.sub(r"\g<scheme>***@", text)
    text = _HEADER.sub(r"\1***", text)
    return _TOKENS.sub("***", text)
