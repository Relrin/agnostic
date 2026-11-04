"""SQL repository of the service_accounts module."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.db import aware, aware_or_none
from agnostic_service_accounts.domain.accounts import (
    GatewayToken,
    NativeToken,
    ScopeSource,
    ServiceAccount,
    TokenStatus,
)
from agnostic_service_accounts.infrastructure.tables import AccountRow, GatewayTokenRow, InstanceTokenRow


def _account(row: AccountRow) -> ServiceAccount:
    return ServiceAccount(
        id=row.id,
        name=row.name,
        description=row.description,
        scope_source=cast("ScopeSource", row.scope_source),
        role_id=row.role_id,
        scopes=tuple(row.scopes),
        instance_ids=tuple(row.instance_ids),
        forwards_user_id=row.forwards_user_id,
        created_by=row.created_by,
        created_by_name=row.created_by_name,
        created_at=aware(row.created_at),
        expires_at=aware_or_none(row.expires_at),
        deleted_at=aware_or_none(row.deleted_at),
    )


def _native(row: InstanceTokenRow) -> NativeToken:
    return NativeToken(
        id=row.id,
        account_id=row.sa_id,
        instance_id=row.instance_id,
        agentos_sa_id=row.agentos_sa_id,
        token_prefix=row.token_prefix,
        status=cast("TokenStatus", row.status),
        scopes=tuple(row.scopes),
        created_at=aware(row.created_at),
        revoked_at=aware_or_none(row.revoked_at),
        expires_at=aware_or_none(row.expires_at),
        last_used_at=aware_or_none(row.last_used_at),
    )


def _gateway(row: GatewayTokenRow) -> GatewayToken:
    return GatewayToken(
        id=row.id,
        account_id=row.sa_id,
        prefix=row.prefix,
        token_hash=row.token_hash,
        status=cast("TokenStatus", row.status),
        created_at=aware(row.created_at),
        grace_until=aware_or_none(row.grace_until),
        revoked_at=aware_or_none(row.revoked_at),
        revoke_reason=row.revoke_reason,
        last_used_at=aware_or_none(row.last_used_at),
        last_used_ip=row.last_used_ip,
    )


def _fill_account(row: AccountRow, account: ServiceAccount) -> None:
    row.name = account.name
    row.principal = account.principal
    row.description = account.description
    row.scope_source = account.scope_source
    row.role_id = account.role_id
    row.scopes = list(account.scopes)
    row.instance_ids = list(account.instance_ids)
    row.forwards_user_id = account.forwards_user_id
    row.created_by = account.created_by
    row.created_by_name = account.created_by_name
    row.created_at = account.created_at
    row.expires_at = account.expires_at
    row.deleted_at = account.deleted_at


def _fill_native(row: InstanceTokenRow, token: NativeToken) -> None:
    row.sa_id = token.account_id
    row.instance_id = token.instance_id
    row.agentos_sa_id = token.agentos_sa_id
    row.token_prefix = token.token_prefix
    row.status = token.status
    row.scopes = list(token.scopes)
    row.created_at = token.created_at
    row.revoked_at = token.revoked_at
    row.expires_at = token.expires_at
    row.last_used_at = token.last_used_at


def _fill_gateway(row: GatewayTokenRow, token: GatewayToken) -> None:
    row.sa_id = token.account_id
    row.prefix = token.prefix
    row.token_hash = token.token_hash
    row.status = token.status
    row.created_at = token.created_at
    row.grace_until = token.grace_until
    row.revoked_at = token.revoked_at
    row.revoke_reason = token.revoke_reason
    row.last_used_at = token.last_used_at
    row.last_used_ip = token.last_used_ip


class SqlServiceAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, account_id: str) -> ServiceAccount | None:
        row = await self._session.get(AccountRow, account_id)
        return _account(row) if row is not None else None

    async def by_name(self, name: str) -> ServiceAccount | None:
        query = select(AccountRow).where(AccountRow.name == name, AccountRow.deleted_at.is_(None))
        row = (await self._session.scalars(query)).first()
        return _account(row) if row is not None else None

    async def list(self, *, include_deleted: bool = False) -> list[ServiceAccount]:
        query = select(AccountRow).order_by(AccountRow.name, AccountRow.created_at)
        if not include_deleted:
            query = query.where(AccountRow.deleted_at.is_(None))
        return [_account(row) for row in (await self._session.scalars(query)).all()]

    async def add(self, account: ServiceAccount) -> None:
        row = AccountRow(id=account.id)
        _fill_account(row, account)
        self._session.add(row)
        await self._session.flush()

    async def save(self, account: ServiceAccount) -> None:
        row = await self._session.get(AccountRow, account.id)
        if row is None:
            await self.add(account)
            return
        _fill_account(row, account)
        await self._session.flush()

    async def native_tokens(self, account_ids: Sequence[str]) -> list[NativeToken]:
        if not account_ids:
            return []
        query = (
            select(InstanceTokenRow)
            .where(InstanceTokenRow.sa_id.in_(list(account_ids)))
            .order_by(InstanceTokenRow.created_at.desc(), InstanceTokenRow.id.desc())
        )
        return [_native(row) for row in (await self._session.scalars(query)).all()]

    async def active_native_tokens(self) -> list[NativeToken]:
        query = select(InstanceTokenRow).where(InstanceTokenRow.status == "active").order_by(InstanceTokenRow.id)
        return [_native(row) for row in (await self._session.scalars(query)).all()]

    async def add_native(self, token: NativeToken) -> None:
        row = InstanceTokenRow(id=token.id)
        _fill_native(row, token)
        self._session.add(row)
        await self._session.flush()

    async def save_native(self, token: NativeToken) -> None:
        row = await self._session.get(InstanceTokenRow, token.id)
        if row is None:
            await self.add_native(token)
            return
        _fill_native(row, token)
        await self._session.flush()

    async def gateway_tokens(self, account_ids: Sequence[str]) -> list[GatewayToken]:
        if not account_ids:
            return []
        query = (
            select(GatewayTokenRow)
            .where(GatewayTokenRow.sa_id.in_(list(account_ids)))
            .order_by(GatewayTokenRow.created_at.desc(), GatewayTokenRow.id.desc())
        )
        return [_gateway(row) for row in (await self._session.scalars(query)).all()]

    async def gateway_token_by_hash(self, token_hash: str) -> GatewayToken | None:
        row = (
            await self._session.scalars(select(GatewayTokenRow).where(GatewayTokenRow.token_hash == token_hash))
        ).first()
        return _gateway(row) if row is not None else None

    async def add_gateway(self, token: GatewayToken) -> None:
        row = GatewayTokenRow(id=token.id)
        _fill_gateway(row, token)
        self._session.add(row)
        await self._session.flush()

    async def save_gateway(self, token: GatewayToken) -> None:
        row = await self._session.get(GatewayTokenRow, token.id)
        if row is None:
            await self.add_gateway(token)
            return
        _fill_gateway(row, token)
        await self._session.flush()

    async def touch_gateway(self, token_id: str, *, at: datetime, ip: str | None) -> None:
        _ = await self._session.execute(
            update(GatewayTokenRow).where(GatewayTokenRow.id == token_id).values(last_used_at=at, last_used_ip=ip)
        )
        await self._session.commit()

    async def rehash_gateway(self, token_id: str, token_hash: str) -> None:
        _ = await self._session.execute(
            update(GatewayTokenRow).where(GatewayTokenRow.id == token_id).values(token_hash=token_hash)
        )
        await self._session.commit()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
