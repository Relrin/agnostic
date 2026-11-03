"""Webhooks from git hosts: signature checks and the few fields Agnostic reads from push and pull request events."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from agnostic_sources.domain.model import Provider

ZERO_SHA = "0" * 40


@dataclass(frozen=True, slots=True)
class PushEvent:
    repo: str
    branch: str | None
    before: str | None
    after: str | None
    pusher: str | None


@dataclass(frozen=True, slots=True)
class PullEvent:
    repo: str
    number: int
    action: str
    merged: bool
    merge_sha: str | None


def hmac_sha256(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(provider: Provider, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    """Whether the delivery was signed with ``secret`` (header names are lowercase)."""
    if not secret:
        return False
    match provider:
        case "github":
            header = headers.get("x-hub-signature-256", "")
            return header.startswith("sha256=") and hmac.compare_digest(
                header.removeprefix("sha256="), hmac_sha256(secret, body)
            )
        case "gitea" | "forgejo":
            header = headers.get("x-forgejo-signature") or headers.get("x-gitea-signature") or ""
            return bool(header) and hmac.compare_digest(header.lower(), hmac_sha256(secret, body))
        case "gitlab":
            return hmac.compare_digest(headers.get("x-gitlab-token", "").encode(), secret.encode())
        case "local":
            return False


def delivery_id(provider: Provider, headers: Mapping[str, str], body: bytes) -> str:
    for name in ("x-github-delivery", "x-gitea-delivery", "x-forgejo-delivery", "x-gitlab-event-uuid"):
        if headers.get(name):
            return headers[name][:200]
    return f"{provider}:{hashlib.sha256(body).hexdigest()[:40]}"


def event_name(provider: Provider, headers: Mapping[str, str], payload: Mapping[str, Any]) -> str:
    match provider:
        case "github":
            return headers.get("x-github-event", "")
        case "gitea" | "forgejo":
            return headers.get("x-forgejo-event") or headers.get("x-gitea-event") or ""
        case "gitlab":
            kind = str(payload.get("object_kind") or headers.get("x-gitlab-event", ""))
            return {"merge_request": "pull_request", "Push Hook": "push", "Merge Request Hook": "pull_request"}.get(
                kind, kind
            )
        case "local":
            return ""


def repo_of(provider: Provider, payload: Mapping[str, Any]) -> str | None:
    if provider == "gitlab":
        project = _dict(payload.get("project"))
        return str(project.get("path_with_namespace") or "") or None
    repository = _dict(payload.get("repository"))
    return str(repository.get("full_name") or "") or None


def installation_of(payload: Mapping[str, Any]) -> str | None:
    installation = _dict(payload.get("installation"))
    value = installation.get("id")
    return str(value) if value is not None else None


def push_event(provider: Provider, payload: Mapping[str, Any]) -> PushEvent | None:
    repo = repo_of(provider, payload)
    if repo is None:
        return None
    ref = str(payload.get("ref") or "")
    branch = ref.removeprefix("refs/heads/") if ref.startswith("refs/heads/") else None
    pusher = _dict(payload.get("pusher")) or _dict(payload.get("sender"))
    name = pusher.get("name") or pusher.get("login") or payload.get("user_name")
    return PushEvent(
        repo=repo,
        branch=branch,
        before=_sha(payload.get("before")),
        after=_sha(payload.get("after") or payload.get("checkout_sha")),
        pusher=str(name) if name else None,
    )


def pull_event(provider: Provider, payload: Mapping[str, Any]) -> PullEvent | None:
    repo = repo_of(provider, payload)
    if repo is None:
        return None
    if provider == "gitlab":
        attributes = _dict(payload.get("object_attributes"))
        number = attributes.get("iid")
        action = str(attributes.get("action") or attributes.get("state") or "")
        merged = attributes.get("state") == "merged" or action == "merge"
        return PullEvent(repo, int(number or 0), action, merged, _sha(attributes.get("merge_commit_sha")))
    pull = _dict(payload.get("pull_request"))
    number = pull.get("number") or payload.get("number")
    return PullEvent(
        repo=repo,
        number=int(number or 0),
        action=str(payload.get("action") or ""),
        merged=bool(pull.get("merged")),
        merge_sha=_sha(pull.get("merge_commit_sha")),
    )


def _dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _sha(value: object) -> str | None:
    text = str(value or "")
    return text if text and text != ZERO_SHA else None
