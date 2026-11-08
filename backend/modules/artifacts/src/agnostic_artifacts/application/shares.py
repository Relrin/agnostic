"""Create, list, revoke and open share links.

Creating a link reads the artefact as the person sharing it, so nobody can share what they cannot see, and records
its hash. Opening a link reads the object as the control plane, because the person opening it may hold no access to
the instance at all; the link is the grant, so it is checked here: active, the right audience, the same bytes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from agnostic_artifacts.application.content import ArtifactContent, Fetched, checked, media_path
from agnostic_artifacts.application.ports import MANAGE, SHARE, ShareRepository
from agnostic_artifacts.domain.content import safe_filename
from agnostic_artifacts.domain.shares import (
    ID_PREFIX,
    Audience,
    Share,
    ShareError,
    expiry,
    looks_like_token,
    new_token,
    token_hash,
)
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import ForbiddenError, NotFoundError, UnauthenticatedError, ValidationFailedError
from agnostic_kernel.ids import new_id

MiB = 1024 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ShareRequest:
    session_id: str
    storage_key: str
    filename: str
    audience: Audience
    ttl_seconds: int


@dataclass(frozen=True, slots=True)
class CreatedShare:
    share: Share
    token: str


class Shares:
    def __init__(
        self,
        content: ArtifactContent,
        instances: InstancesFacade,
        repository: ShareRepository,
        authorizer: Authorizer,
        audit: AuditLog,
        *,
        max_content_mb: int,
        max_share_days: int,
        public_links: bool,
    ) -> None:
        self._content = content
        self._instances = instances
        self._repository = repository
        self._authorizer = authorizer
        self._audit = audit
        self._max_bytes = max_content_mb * MiB
        self._max_ttl = timedelta(days=max_share_days)
        self.public_links = public_links

    async def create(self, principal: Principal, instance_ref: str, request: ShareRequest) -> CreatedShare:
        instance = await self._content.instance(instance_ref)
        _ = await self._authorizer.require(principal, SHARE, instance_id=instance.id)
        if request.audience == "link" and not self.public_links:
            raise ForbiddenError("Links for anyone are turned off here; share with members of the organization.")
        now = _now()
        try:
            expires_at = expiry(now, request.ttl_seconds, maximum=self._max_ttl)
        except ShareError as error:
            raise ValidationFailedError(str(error)) from error
        fetched = await self._content.fetch(principal, instance, request.session_id, request.storage_key)
        filename = safe_filename(request.filename)
        share = Share(
            id=new_id(ID_PREFIX),
            instance_id=instance.id,
            session_id=request.session_id,
            storage_key=request.storage_key,
            filename=filename,
            content_type=fetched.served(filename, "inline").content_type.split(";", 1)[0],
            size=len(fetched.data),
            sha256=fetched.sha256,
            audience=request.audience,
            created_by=principal.id,
            created_by_name=principal.display_name,
            created_at=now,
            expires_at=expires_at,
        )
        token = new_token()
        await self._repository.add(share, token_hash(token))
        await self._record(principal, "artifact.share.created", share, audience=_audience_label(share.audience))
        await self._repository.commit()
        return CreatedShare(share, token)

    async def list(self, principal: Principal, instance_ref: str, *, session_id: str | None = None) -> list[Share]:
        instance = await self._content.instance(instance_ref)
        _ = await self._authorizer.require(principal, SHARE, instance_id=instance.id)
        manage = (await self._authorizer.check(principal, MANAGE, instance_id=instance.id)).allowed
        shares = await self._repository.list(
            instance.id, session_id=session_id, created_by=None if manage else principal.id
        )
        return sorted(shares, key=lambda share: share.created_at, reverse=True)

    async def revoke(self, principal: Principal, instance_ref: str, share_id: str) -> Share:
        instance = await self._content.instance(instance_ref)
        share = await self._repository.get(share_id)
        if share is None or share.instance_id != instance.id:
            raise NotFoundError("No such share link")
        if share.created_by != principal.id:
            _ = await self._authorizer.require(principal, MANAGE, instance_id=instance.id)
        if share.revoked_at is None:
            share = share.revoked(_now())
            await self._repository.save(share)
            await self._record(principal, "artifact.share.revoked", share, audience=_audience_label(share.audience))
            await self._repository.commit()
        return share

    async def _active(self, token: str, principal: Principal | None) -> Share:
        share = await self._repository.by_token(token_hash(token)) if looks_like_token(token) else None
        # Expired, revoked and unknown links answer the same, so a link's history is not observable.
        if share is None or not share.active(_now()):
            raise NotFoundError("This link has expired or was revoked, or it never existed")
        if share.audience == "link" and not self.public_links:
            raise NotFoundError("This link has expired or was revoked, or it never existed")
        if share.audience == "org" and principal is None:
            raise UnauthenticatedError("Sign in to open this link: it is shared with members of the organization")
        return share

    async def describe(self, token: str, principal: Principal | None) -> Share:
        return await self._active(token, principal)

    async def open(self, token: str, principal: Principal | None) -> tuple[Share, Fetched]:
        share = await self._active(token, principal)
        instance = await self._instances.get(share.instance_id)
        if instance is None:
            raise NotFoundError("The instance this link points to is gone")
        status, headers, body = await self._instances.system_fetch(
            instance, media_path(share.session_id, share.storage_key), max_bytes=self._max_bytes
        )
        data = checked(instance, status, body)
        digest = hashlib.sha256(data).hexdigest()
        if digest != share.sha256:
            raise NotFoundError("The shared file is no longer the one that was shared")
        opened = share.opened(_now())
        await self._repository.save(opened)
        await self._record(principal, "artifact.share.opened", opened, audience=_audience_label(share.audience))
        await self._repository.commit()
        return opened, Fetched(data, headers.get("content-type"), digest)

    async def _record(self, principal: Principal | None, action: str, share: Share, **fields: str) -> None:
        _ = await self._audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="artifact_share",
                resource_id=share.id,
                resource_display=share.filename,
                instance_id=share.instance_id,
                fields={"file": share.filename, "session": share.session_id, **fields},
            )
        )


def _audience_label(audience: Audience) -> str:
    return "anyone with the link" if audience == "link" else "members of the organization"
