"""SQLAlchemy repositories for directory sync: SCIM tokens, users and status, mapping rules, config rows."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_directory.domain.sync import (
    DeprovisionBehaviour,
    GoogleRecord,
    MappingRule,
    RuleSource,
    ScimToken,
    ScimUser,
    SyncSettings,
    SyncState,
)
from agnostic_directory.infrastructure.tables import (
    DirectorySettingsRow,
    GoogleSyncRow,
    GroupRow,
    MappingRuleRow,
    ScimSyncStateRow,
    ScimTokenRow,
    ScimUserRow,
)
from agnostic_kernel.db import aware, aware_or_none, utcnow

SINGLE_ROW = 1


def _token(row: ScimTokenRow) -> ScimToken:
    return ScimToken(
        id=row.id,
        label=row.label,
        prefix=row.prefix,
        token_hash=row.token_hash,
        created_by=row.created_by,
        created_at=aware(row.created_at),
        last_used_at=aware_or_none(row.last_used_at),
        expires_at=aware_or_none(row.expires_at),
        revoked_at=aware_or_none(row.revoked_at),
        rotated_from=row.rotated_from,
    )


def _scim_user(row: ScimUserRow) -> ScimUser:
    return ScimUser(
        user_id=row.user_id,
        external_id=row.external_id,
        user_name=row.user_name,
        active=row.active,
        raw=dict(row.raw),
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
    )


def _rule(row: MappingRuleRow) -> MappingRule:
    return MappingRule(
        id=row.id,
        source=cast("RuleSource", row.source),
        provider_id=row.provider_id,
        idp_group=row.idp_group,
        group_id=row.group_id,
        created_by=row.created_by,
        created_at=aware(row.created_at),
    )


class SqlScimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tokens(self) -> list[ScimToken]:
        rows = await self._session.scalars(select(ScimTokenRow).order_by(ScimTokenRow.created_at.desc()))
        return [_token(row) for row in rows]

    async def token(self, token_id: str) -> ScimToken | None:
        row = await self._session.get(ScimTokenRow, token_id)
        return _token(row) if row else None

    async def token_by_hash(self, token_hash: str) -> ScimToken | None:
        row = await self._session.scalar(select(ScimTokenRow).where(ScimTokenRow.token_hash == token_hash))
        return _token(row) if row else None

    async def add_token(self, token: ScimToken) -> None:
        self._session.add(
            ScimTokenRow(
                id=token.id,
                label=token.label,
                token_hash=token.token_hash,
                prefix=token.prefix,
                created_by=token.created_by,
                created_at=token.created_at,
                rotated_from=token.rotated_from,
            )
        )
        await self._session.flush()

    async def update_token(
        self,
        token_id: str,
        *,
        last_used_at: datetime | None = None,
        expires_at: datetime | None = None,
        revoked_at: datetime | None = None,
    ) -> None:
        row = await self._session.get(ScimTokenRow, token_id)
        if row is None:
            return
        if last_used_at is not None:
            row.last_used_at = last_used_at
        if expires_at is not None:
            row.expires_at = expires_at
        if revoked_at is not None:
            row.revoked_at = revoked_at
        await self._session.flush()

    async def state(self) -> SyncState:
        row = await self._session.get(ScimSyncStateRow, SINGLE_ROW)
        if row is None:
            return SyncState()
        return SyncState(
            last_request_at=aware_or_none(row.last_request_at),
            last_error=row.last_error,
            last_error_at=aware_or_none(row.last_error_at),
            counts=dict(row.counts),
        )

    async def record_request(self, *, error: str | None = None, counts: dict[str, int] | None = None) -> None:
        row = await self._session.get(ScimSyncStateRow, SINGLE_ROW)
        if row is None:
            row = ScimSyncStateRow(id=SINGLE_ROW, counts={})
            self._session.add(row)
        now = utcnow()
        if error is None:
            row.last_request_at = now
        else:
            row.last_error = error[:1000]
            row.last_error_at = now
        if counts is not None:
            row.counts = dict(counts)
        await self._session.flush()

    async def save_counts(self, counts: dict[str, int]) -> None:
        row = await self._session.get(ScimSyncStateRow, SINGLE_ROW)
        if row is None:
            row = ScimSyncStateRow(id=SINGLE_ROW, counts={})
            self._session.add(row)
        row.counts = dict(counts)
        await self._session.flush()

    async def counts(self) -> dict[str, int]:
        users = await self._session.scalar(
            select(func.count()).select_from(ScimUserRow).where(ScimUserRow.active.is_(True))
        )
        deactivated = await self._session.scalar(
            select(func.count()).select_from(ScimUserRow).where(ScimUserRow.active.is_(False))
        )
        groups = await self._session.scalar(select(func.count()).select_from(GroupRow).where(GroupRow.source == "scim"))
        return {"users": int(users or 0), "deactivated_users": int(deactivated or 0), "groups": int(groups or 0)}

    async def users(self) -> list[ScimUser]:
        return [_scim_user(row) for row in await self._session.scalars(select(ScimUserRow))]

    async def user(self, user_id: str) -> ScimUser | None:
        row = await self._session.get(ScimUserRow, user_id)
        return _scim_user(row) if row else None

    async def user_by_name(self, user_name: str) -> ScimUser | None:
        row = await self._session.scalar(select(ScimUserRow).where(ScimUserRow.user_name_key == user_name.lower()))
        return _scim_user(row) if row else None

    async def user_by_external_id(self, external_id: str) -> ScimUser | None:
        row = await self._session.scalar(select(ScimUserRow).where(ScimUserRow.external_id == external_id))
        return _scim_user(row) if row else None

    async def save_user(self, user: ScimUser) -> None:
        row = await self._session.get(ScimUserRow, user.user_id)
        if row is None:
            row = ScimUserRow(user_id=user.user_id, created_at=user.created_at)
            self._session.add(row)
        row.external_id = user.external_id
        row.user_name = user.user_name
        row.user_name_key = user.user_name.lower()
        row.active = user.active
        row.raw = dict(user.raw)
        row.updated_at = user.updated_at
        await self._session.flush()

    async def delete_user(self, user_id: str) -> None:
        row = await self._session.get(ScimUserRow, user_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class SqlMappingRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[MappingRule]:
        rows = await self._session.scalars(select(MappingRuleRow).order_by(MappingRuleRow.created_at))
        return [_rule(row) for row in rows]

    async def get(self, rule_id: str) -> MappingRule | None:
        row = await self._session.get(MappingRuleRow, rule_id)
        return _rule(row) if row else None

    async def add(self, rule: MappingRule) -> None:
        self._session.add(
            MappingRuleRow(
                id=rule.id,
                source=rule.source,
                provider_id=rule.provider_id,
                idp_group=rule.idp_group,
                group_id=rule.group_id,
                created_by=rule.created_by,
                created_at=rule.created_at,
            )
        )
        await self._session.flush()

    async def delete(self, rule_id: str) -> None:
        row = await self._session.get(MappingRuleRow, rule_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()


class SqlDirectoryConfigRepository:
    """The single-row ``dir_settings`` and ``dir_google_sync`` tables (the Google key stays sealed here)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def settings(self) -> SyncSettings:
        row = await self._session.get(DirectorySettingsRow, SINGLE_ROW)
        if row is None:
            return SyncSettings()
        return SyncSettings(deprovision=cast("DeprovisionBehaviour", row.deprovision))

    async def save_settings(self, settings: SyncSettings) -> None:
        row = await self._session.get(DirectorySettingsRow, SINGLE_ROW)
        if row is None:
            row = DirectorySettingsRow(id=SINGLE_ROW)
            self._session.add(row)
        row.deprovision = settings.deprovision
        row.updated_at = utcnow()
        await self._session.flush()

    async def google(self) -> GoogleRecord:
        row = await self._session.get(GoogleSyncRow, SINGLE_ROW)
        if row is None:
            return GoogleRecord()
        return GoogleRecord(
            config_enc=row.config_enc,
            group_filter=tuple(row.group_filter),
            enabled=row.enabled,
            last_run_at=aware_or_none(row.last_run_at),
            last_error=row.last_error,
            counts=dict(row.counts),
        )

    async def save_google(
        self,
        *,
        config_enc: str | None = None,
        group_filter: tuple[str, ...] | None = None,
        enabled: bool | None = None,
    ) -> None:
        row = await self._row()
        if config_enc is not None:
            row.config_enc = config_enc
        if group_filter is not None:
            row.group_filter = list(group_filter)
        if enabled is not None:
            row.enabled = enabled
        row.updated_at = utcnow()
        await self._session.flush()

    async def record_google_run(self, *, error: str | None, counts: dict[str, int] | None) -> None:
        row = await self._row()
        row.last_run_at = utcnow()
        row.last_error = error[:1000] if error else None
        if counts is not None:
            row.counts = dict(counts)
        await self._session.flush()

    async def _row(self) -> GoogleSyncRow:
        row = await self._session.get(GoogleSyncRow, SINGLE_ROW)
        if row is None:
            row = GoogleSyncRow(id=SINGLE_ROW, group_filter=[], enabled=False, counts={})
            self._session.add(row)
        return row

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
