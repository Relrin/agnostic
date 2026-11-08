"""SQLAlchemy persistence for share links."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_artifacts.domain.shares import Audience, Share
from agnostic_artifacts.infrastructure.tables import ShareRow
from agnostic_kernel.db import aware


def _share(row: ShareRow) -> Share:
    return Share(
        id=row.id,
        instance_id=row.instance_id,
        session_id=row.session_id,
        storage_key=row.storage_key,
        filename=row.filename,
        content_type=row.content_type,
        size=row.size,
        sha256=row.sha256,
        audience=cast("Audience", row.audience),
        created_by=row.created_by,
        created_by_name=row.created_by_name,
        created_at=aware(row.created_at),
        expires_at=aware(row.expires_at),
        revoked_at=aware(row.revoked_at) if row.revoked_at is not None else None,
        opened_count=row.opened_count,
        last_opened_at=aware(row.last_opened_at) if row.last_opened_at is not None else None,
    )


class SqlShareRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, share: Share, token_hash: str) -> None:
        self._session.add(
            ShareRow(
                id=share.id,
                token_hash=token_hash,
                instance_id=share.instance_id,
                session_id=share.session_id,
                storage_key=share.storage_key,
                filename=share.filename,
                content_type=share.content_type,
                size=share.size,
                sha256=share.sha256,
                audience=share.audience,
                created_by=share.created_by,
                created_by_name=share.created_by_name,
                created_at=share.created_at,
                expires_at=share.expires_at,
                revoked_at=share.revoked_at,
                opened_count=share.opened_count,
                last_opened_at=share.last_opened_at,
            )
        )
        await self._session.flush()

    async def get(self, share_id: str) -> Share | None:
        row = await self._session.get(ShareRow, share_id)
        return _share(row) if row is not None else None

    async def by_token(self, token_hash: str) -> Share | None:
        row = await self._session.scalar(select(ShareRow).where(ShareRow.token_hash == token_hash))
        return _share(row) if row is not None else None

    async def list(
        self, instance_id: str, *, session_id: str | None = None, created_by: str | None = None
    ) -> list[Share]:
        query = select(ShareRow).where(ShareRow.instance_id == instance_id)
        if session_id is not None:
            query = query.where(ShareRow.session_id == session_id)
        if created_by is not None:
            query = query.where(ShareRow.created_by == created_by)
        return [_share(row) for row in await self._session.scalars(query.order_by(ShareRow.created_at.desc()))]

    async def save(self, share: Share) -> None:
        row = await self._session.get(ShareRow, share.id)
        if row is None:
            return
        row.revoked_at = share.revoked_at
        row.opened_count = share.opened_count
        row.last_opened_at = share.last_opened_at
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
