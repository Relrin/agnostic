"""SQLAlchemy repositories of the identity module."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_identity.domain.providers import ExternalProfile
from agnostic_identity.domain.users import USER_ID_PREFIX, CreatedVia, User, UserStatus, WebSession
from agnostic_identity.infrastructure.tables import (
    CredentialRow,
    ExternalIdentityRow,
    PreferenceRow,
    SessionRecordRow,
    UserRow,
)
from agnostic_kernel.crypto import new_token
from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import NotFoundError
from agnostic_kernel.ids import new_id

PASSWORD = "password"  # noqa: S105  (the credential kind, not a secret)


def _to_domain(row: UserRow) -> User:
    return User(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        avatar_seed=row.avatar_seed,
        status=UserStatus(row.status),
        locale=row.locale,
        timezone=row.timezone,
        created_via=CreatedVia(row.created_via),
        created_at=aware(row.created_at),
        last_active_at=aware_or_none(row.last_active_at),
    )


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, email: str, display_name: str, created_via: CreatedVia) -> User:
        now = utcnow()
        row = UserRow(
            id=new_id(USER_ID_PREFIX),
            email=email,
            display_name=display_name,
            avatar_seed=new_token(6),
            status=UserStatus.ACTIVE.value,
            created_via=created_via.value,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_domain(row)

    async def get(self, user_id: str) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return _to_domain(row) if row else None

    async def get_many(self, user_ids: Sequence[str]) -> list[User]:
        if not user_ids:
            return []
        rows = await self._session.scalars(select(UserRow).where(UserRow.id.in_(list(user_ids))))
        return [_to_domain(row) for row in rows]

    async def find_by_email(self, email: str) -> User | None:
        row = await self._session.scalar(select(UserRow).where(UserRow.email == email))
        return _to_domain(row) if row else None

    async def update(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
        status: UserStatus | None = None,
    ) -> User:
        row = await self._session.get(UserRow, user_id)
        if row is None:
            raise NotFoundError(f"User {user_id} doesn't exist.")
        if display_name is not None:
            row.display_name = display_name
        if locale is not None:
            row.locale = locale or None
        if timezone is not None:
            row.timezone = timezone or None
        if status is not None:
            row.status = status.value
        row.updated_at = utcnow()
        await self._session.flush()
        return _to_domain(row)

    async def touch(self, user_id: str, at: datetime) -> None:
        _ = await self._session.execute(update(UserRow).where(UserRow.id == user_id).values(last_active_at=at))

    async def commit(self) -> None:
        await self._session.commit()


class SqlCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _row(self, user_id: str) -> CredentialRow | None:
        return await self._session.scalar(
            select(CredentialRow).where(CredentialRow.user_id == user_id, CredentialRow.kind == PASSWORD)
        )

    async def password_hash(self, user_id: str) -> str | None:
        row = await self._row(user_id)
        return row.secret_hash if row else None

    async def set_password_hash(self, user_id: str, password_hash: str) -> None:
        row = await self._row(user_id)
        if row is None:
            self._session.add(
                CredentialRow(
                    id=new_id("crd"), user_id=user_id, kind=PASSWORD, secret_hash=password_hash, created_at=utcnow()
                )
            )
        else:
            row.secret_hash = password_hash
        await self._session.flush()

    async def mark_used(self, user_id: str, at: datetime) -> None:
        _ = await self._session.execute(
            update(CredentialRow)
            .where(CredentialRow.user_id == user_id, CredentialRow.kind == PASSWORD)
            .values(last_used_at=at)
        )


class SqlExternalIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_user(self, provider_id: str, subject: str) -> str | None:
        return await self._session.scalar(
            select(ExternalIdentityRow.user_id).where(
                ExternalIdentityRow.provider_id == provider_id, ExternalIdentityRow.subject == subject
            )
        )

    async def link(self, user_id: str, provider_id: str, profile: ExternalProfile) -> None:
        self._session.add(
            ExternalIdentityRow(
                id=new_id("ext"),
                user_id=user_id,
                provider_id=provider_id,
                subject=profile.subject,
                email_at_provider=profile.email,
                raw_claims=dict(profile.claims),
                linked_at=utcnow(),
            )
        )
        await self._session.flush()

    async def providers_of(self, user_id: str) -> list[str]:
        rows = await self._session.scalars(
            select(ExternalIdentityRow.provider_id).where(ExternalIdentityRow.user_id == user_id)
        )
        return sorted(set(rows))

    async def unlink_provider(self, provider_id: str) -> int:
        result = await self._session.execute(
            delete(ExternalIdentityRow).where(ExternalIdentityRow.provider_id == provider_id)
        )
        return cast("CursorResult[Any]", result).rowcount or 0


class SqlPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self, user_id: str) -> dict[str, Any]:
        rows = await self._session.scalars(select(PreferenceRow).where(PreferenceRow.user_id == user_id))
        return {row.key: row.value for row in rows}

    async def set_many(self, user_id: str, values: Mapping[str, Any]) -> None:
        for key, value in values.items():
            row = await self._session.get(PreferenceRow, (user_id, key))
            if row is None:
                self._session.add(PreferenceRow(user_id=user_id, key=key, value=value))
            else:
                row.value = value
        await self._session.flush()


class SqlSessionRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, session: WebSession) -> None:
        self._session.add(
            SessionRecordRow(
                id=session.key,
                user_id=session.user_id,
                method=session.method,
                ip=session.ip,
                user_agent=session.user_agent,
                created_at=session.created_at,
            )
        )
        await self._session.flush()

    async def active_keys(self, user_id: str) -> list[str]:
        rows = await self._session.scalars(
            select(SessionRecordRow.id).where(
                SessionRecordRow.user_id == user_id, SessionRecordRow.revoked_at.is_(None)
            )
        )
        return list(rows)

    async def list_active(self, user_id: str) -> list[WebSession]:
        rows = await self._session.scalars(
            select(SessionRecordRow)
            .where(SessionRecordRow.user_id == user_id, SessionRecordRow.revoked_at.is_(None))
            .order_by(SessionRecordRow.created_at.desc())
        )
        return [
            WebSession(
                key=row.id,
                user_id=row.user_id,
                email="",
                display_name="",
                csrf_token="",
                created_at=aware(row.created_at),
                last_seen_at=aware(row.created_at),
                ip=row.ip,
                user_agent=row.user_agent,
                method=row.method,
            )
            for row in rows
        ]

    async def revoke(self, keys: Sequence[str], at: datetime) -> None:
        if keys:
            _ = await self._session.execute(
                update(SessionRecordRow)
                .where(SessionRecordRow.id.in_(list(keys)), SessionRecordRow.revoked_at.is_(None))
                .values(revoked_at=at)
            )
