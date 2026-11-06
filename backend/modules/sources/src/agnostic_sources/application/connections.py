"""Connections to git hosts (org-wide): GitHub App installations, tokens and deploy keys."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, cast
from urllib.parse import quote

import orjson

from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_kernel.auth import Principal
from agnostic_kernel.crypto import SecretBox, SecretDecryptionError
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError, ForbiddenError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_sources.application.access import SOURCES_DELETE, SOURCES_READ, SOURCES_WRITE, SourcesAccess
from agnostic_sources.application.ports import (
    ProviderClients,
    ProviderError,
    RepoSummary,
    Secrets,
    SourceLimits,
    SourceStore,
)
from agnostic_sources.domain.model import Access, AuthKind, Connection, Provider

INSTALL_STATE_TTL = 1800
PROVIDERS = frozenset({"github", "gitlab", "gitea", "forgejo"})
_KIND: dict[str, str] = {
    "github_app": "the GitHub App",
    "token": "a token",
    "deploy_key": "a deploy key",
    "local": "a local folder",
}


@dataclass(frozen=True, slots=True)
class ConnectionDraft:
    name: str
    provider: Provider
    auth_kind: AuthKind
    access: Access = "read_write"
    api_url: str | None = None
    web_url: str | None = None
    app_slug: str | None = None
    installation_id: str | None = None
    secrets: Secrets | None = None


@dataclass(frozen=True, slots=True)
class ConnectionPatch:
    """A change to a connection: only the fields named in ``given`` change (a URL given as ``None`` is cleared)."""

    given: frozenset[str]
    name: str | None = None
    provider: Provider | None = None
    auth_kind: AuthKind | None = None
    access: Access | None = None
    api_url: str | None = None
    web_url: str | None = None
    app_slug: str | None = None
    installation_id: str | None = None
    secrets: Secrets | None = None


class Connections:
    def __init__(
        self,
        store: SourceStore,
        access: SourcesAccess,
        clients: ProviderClients,
        audit: AuditLog,
        box: SecretBox,
        settings: SourceLimits,
    ) -> None:
        self._store = store
        self._access = access
        self._clients = clients
        self._audit = audit
        self._box = box
        self._settings = settings

    async def list(self, principal: Principal) -> list[Connection]:
        await self._access.require(principal, SOURCES_READ)
        return await self._store.connections()

    async def get(self, principal: Principal, connection_id: str) -> Connection:
        await self._access.require(principal, SOURCES_READ)
        return await self._found(connection_id)

    async def _found(self, connection_id: str) -> Connection:
        connection = await self._store.connection(connection_id)
        if connection is None:
            raise NotFoundError(f"There is no connection {connection_id}.")
        return connection

    async def create(self, principal: Principal, draft: ConnectionDraft) -> Connection:
        await self._access.require(principal, SOURCES_WRITE)
        _check(draft)
        if draft.auth_kind == "deploy_key" and not (draft.secrets and draft.secrets.private_key):
            raise ValidationFailedError("Paste the deploy key's private key (the public half goes on the repository).")
        connection = Connection(
            id=new_id("scn"),
            name=draft.name.strip(),
            provider=draft.provider,
            auth_kind=draft.auth_kind,
            access=draft.access,
            api_url=_url(draft.api_url),
            web_url=_url(draft.web_url),
            app_slug=draft.app_slug or (self._settings.github_app_slug if draft.auth_kind == "github_app" else None),
            installation_id=draft.installation_id,
            created_by=principal.id,
            created_at=utcnow(),
        )
        saved = await self._store.save_connection(connection, draft.secrets or Secrets())
        if draft.auth_kind != "github_app" or draft.installation_id:
            saved = await self._verify(saved)
        await self._audited(principal, "sources.connection.create", saved)
        await self._store.commit()
        return saved

    async def update(
        self, principal: Principal, connection_id: str, patch: ConnectionPatch, expected_version: int | None
    ) -> Connection:
        await self._access.require(principal, SOURCES_WRITE)
        existing = await self._found(connection_id)
        given = patch.given
        if "provider" in given and patch.provider not in {None, existing.provider}:
            raise ValidationFailedError(
                f"{existing.name} connects to {existing.provider}; connect {patch.provider} as a new connection."
            )
        if "auth_kind" in given and patch.auth_kind not in {None, existing.auth_kind}:
            # The secrets a connection keeps belong to its kind (a token, an app key, a deploy key): switching kinds
            # would leave the wrong ones behind, so it is a new connection.
            raise ValidationFailedError(
                f"{existing.name} signs in with {_KIND[existing.auth_kind]}; it can't switch to "
                f"{_KIND[patch.auth_kind or existing.auth_kind]}. Connect again with the new kind, then move the "
                "sources over."
            )
        updated = replace(
            existing,
            name=(patch.name or "").strip() if "name" in given else existing.name,
            access=patch.access or existing.access if "access" in given else existing.access,
            api_url=_url(patch.api_url) if "api_url" in given else existing.api_url,
            web_url=_url(patch.web_url) if "web_url" in given else existing.web_url,
            app_slug=patch.app_slug or existing.app_slug if "app_slug" in given else existing.app_slug,
            installation_id=patch.installation_id or existing.installation_id
            if "installation_id" in given
            else existing.installation_id,
        )
        _check(
            ConnectionDraft(
                name=updated.name,
                provider=updated.provider,
                auth_kind=updated.auth_kind,
                access=updated.access,
                api_url=updated.api_url,
                web_url=updated.web_url,
            )
        )
        secrets = None
        if patch.secrets is not None and any(
            (patch.secrets.token, patch.secrets.private_key, patch.secrets.app_id, patch.secrets.webhook_secret)
        ):
            old = await self._store.connection_secrets(connection_id)
            secrets = Secrets(
                token=patch.secrets.token or old.token,
                private_key=patch.secrets.private_key or old.private_key,
                app_id=patch.secrets.app_id or old.app_id,
                webhook_secret=patch.secrets.webhook_secret or old.webhook_secret,
            )
        saved = await self._store.save_connection(updated, secrets, expected_version=expected_version)
        saved = await self._verify(saved)
        await self._audited(principal, "sources.connection.update", saved)
        await self._store.commit()
        return saved

    async def delete(self, principal: Principal, connection_id: str) -> None:
        await self._access.require(principal, SOURCES_DELETE)
        connection = await self._found(connection_id)
        using = [source for source in await self._store.sources() if source.connection_id == connection_id]
        if using:
            raise ConflictError(
                f"{len(using)} source{'s use' if len(using) > 1 else ' uses'} {connection.name}; disconnect "
                f"{'them' if len(using) > 1 else 'it'} first."
            )
        await self._store.delete_connection(connection_id)
        await self._audited(principal, "sources.connection.delete", connection)
        await self._store.commit()

    async def verify(self, principal: Principal, connection_id: str) -> Connection:
        await self._access.require(principal, SOURCES_WRITE)
        saved = await self._verify(await self._found(connection_id))
        await self._store.commit()
        return saved

    async def _verify(self, connection: Connection) -> Connection:
        try:
            client = self._clients.client(connection, await self._store.connection_secrets(connection.id))
            account = await client.verify()
        except ProviderError as exc:
            updated = replace(connection, status="failed", last_error=str(exc), last_checked_at=utcnow())
        else:
            updated = replace(
                connection, status="verified", last_error=None, account=account or None, last_checked_at=utcnow()
            )
        return await self._store.save_connection(updated, None)

    async def repos(self, principal: Principal, connection_id: str, query: str | None) -> list[RepoSummary]:
        await self._access.require(principal, SOURCES_WRITE)
        connection = await self._found(connection_id)
        client = self._clients.client(connection, await self._store.connection_secrets(connection_id))
        return await client.repos(query)

    async def branches(self, principal: Principal, connection_id: str, repo: str) -> list[str]:
        await self._access.require(principal, SOURCES_WRITE)
        connection = await self._found(connection_id)
        client = self._clients.client(connection, await self._store.connection_secrets(connection_id))
        return await client.branches(repo)

    # ---------------------------------------------------------------- GitHub App installation

    async def install_url(self, principal: Principal, connection_id: str, return_to: str | None) -> str:
        await self._access.require(principal, SOURCES_WRITE)
        connection = await self._found(connection_id)
        if connection.auth_kind != "github_app" or not connection.app_slug:
            raise ValidationFailedError("Only GitHub App connections (with the app's slug) are installed.")
        state = self._box.seal(
            orjson.dumps(
                {
                    "connection_id": connection.id,
                    "user_id": principal.id,
                    "return_to": return_to,
                    "exp": int(time.time()) + INSTALL_STATE_TTL,
                }
            )
        )
        web = (connection.web_url or self._settings.github_web_url).rstrip("/")
        return f"{web}/apps/{quote(connection.app_slug)}/installations/new?state={quote(state)}"

    async def complete_install(
        self, principal: Principal, state: str, installation_id: str
    ) -> tuple[Connection, str | None]:
        try:
            data = cast("dict[str, Any]", orjson.loads(self._box.open(state)))
        except (SecretDecryptionError, ValueError) as exc:
            raise ValidationFailedError("The installation link expired or was tampered with; start again.") from exc
        if int(data.get("exp") or 0) < time.time():
            raise ValidationFailedError("The installation link expired; start again.")
        if data.get("user_id") != principal.id:
            raise ForbiddenError("Someone else started this installation.")
        await self._access.require(principal, SOURCES_WRITE)
        if not installation_id.isdigit():
            raise ValidationFailedError("GitHub sent an installation id Agnostic doesn't understand.")
        connection = await self._found(str(data.get("connection_id")))
        saved = await self._store.save_connection(replace(connection, installation_id=installation_id), None)
        saved = await self._verify(saved)
        await self._audited(principal, "sources.connection.update", saved)
        await self._store.commit()
        return saved, cast("str | None", data.get("return_to"))

    async def _audited(self, principal: Principal, action: str, connection: Connection) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="source_connection",
                resource_id=connection.id,
                resource_display=connection.name,
                decision="allowed",
                scope_checked=SOURCES_DELETE if action.endswith("delete") else SOURCES_WRITE,
                fields={"connection": connection.name, "provider": connection.provider, "status": connection.status},
            )
        )


def _check(draft: ConnectionDraft) -> None:
    if not draft.name.strip():
        raise ValidationFailedError("Name the connection.")
    if draft.provider not in PROVIDERS:
        raise ValidationFailedError(f"{draft.provider!r} isn't a git host Agnostic connects to.")
    if draft.auth_kind == "github_app" and draft.provider != "github":
        raise ValidationFailedError("GitHub Apps are for GitHub connections.")
    if draft.provider in {"gitea", "forgejo"} and not draft.web_url:
        raise ValidationFailedError("Give the server's URL (https://git.example.com).")


def _url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().rstrip("/")
    if not value.startswith(("https://", "http://")):
        raise ValidationFailedError(f"{value} isn't an http(s) URL.")
    return value
