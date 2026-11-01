"""SQLAlchemy repositories of the instances module."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast

import orjson
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_instances.domain.instances import (
    AuthMode,
    Capability,
    CapabilityStatus,
    EnvTag,
    Instance,
    InstanceStatus,
    JwtKey,
    KeyStatus,
    SubClaimMode,
)
from agnostic_instances.infrastructure.tables import CapabilityRow, InstanceRow, JwtKeyRow, SnapshotRow
from agnostic_kernel.db import aware, aware_or_none
from agnostic_kernel.errors import NotFoundError, VersionConflictError

SNAPSHOT_HISTORY = timedelta(days=30)


def _instance(row: InstanceRow) -> Instance:
    return Instance(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        env_tag=EnvTag(row.env_tag),
        endpoint_url=row.endpoint_url,
        os_id=row.os_id,
        agno_version=row.agno_version,
        os_version=row.os_version,
        auth_mode=AuthMode(row.auth_mode),
        user_isolation=row.user_isolation,
        status=InstanceStatus(row.status),
        last_seen_at=aware_or_none(row.last_seen_at),
        latency_ms=row.latency_ms,
        sub_claim_mode=SubClaimMode(row.sub_claim_mode),
        tls_verify=row.tls_verify,
        ca_bundle_pem=row.ca_bundle_pem,
        has_security_key=row.security_key_enc is not None,
        previous_agno_version=row.previous_agno_version,
        version_changed_at=aware_or_none(row.version_changed_at),
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
        version=row.version,
        elevation_enabled=row.elevation_enabled,
    )


def _apply(row: InstanceRow, instance: Instance) -> None:
    row.slug = instance.slug
    row.display_name = instance.display_name
    row.env_tag = instance.env_tag.value
    row.endpoint_url = instance.endpoint_url
    row.os_id = instance.os_id
    row.agno_version = instance.agno_version
    row.os_version = instance.os_version
    row.auth_mode = instance.auth_mode.value
    row.user_isolation = instance.user_isolation
    row.status = instance.status.value
    row.last_seen_at = instance.last_seen_at
    row.latency_ms = instance.latency_ms
    row.sub_claim_mode = instance.sub_claim_mode.value
    row.tls_verify = instance.tls_verify
    row.ca_bundle_pem = instance.ca_bundle_pem
    row.previous_agno_version = instance.previous_agno_version
    row.version_changed_at = instance.version_changed_at
    row.updated_at = instance.updated_at
    row.elevation_enabled = instance.elevation_enabled


class SqlInstanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _row(self, ref: str) -> InstanceRow | None:
        return await self._session.scalar(
            select(InstanceRow).where(or_(InstanceRow.id == ref, InstanceRow.slug == ref))
        )

    async def add(self, instance: Instance, security_key_sealed: str | None) -> None:
        row = InstanceRow(id=instance.id, created_at=instance.created_at, version=1, network_mode="gateway")
        _apply(row, instance)
        row.security_key_enc = security_key_sealed
        self._session.add(row)
        await self._session.flush()

    async def get(self, ref: str) -> Instance | None:
        row = await self._row(ref)
        return _instance(row) if row else None

    async def list(self) -> list[Instance]:
        rows = await self._session.scalars(select(InstanceRow).order_by(InstanceRow.created_at))
        return [_instance(row) for row in rows]

    async def save(self, instance: Instance, *, expected_version: int | None = None) -> Instance:
        row = await self._session.get(InstanceRow, instance.id)
        if row is None:
            raise NotFoundError(f"Instance {instance.id} doesn't exist.")
        if expected_version is not None and row.version != expected_version:
            raise VersionConflictError(
                f"{row.display_name} was changed by someone else (version {row.version}, you had {expected_version})."
            )
        _apply(row, instance)
        row.version += 1
        await self._session.flush()
        return _instance(row)

    async def security_key(self, instance_id: str) -> str | None:
        return await self._session.scalar(select(InstanceRow.security_key_enc).where(InstanceRow.id == instance_id))

    async def set_security_key(self, instance_id: str, sealed: str | None) -> None:
        _ = await self._session.execute(
            update(InstanceRow).where(InstanceRow.id == instance_id).values(security_key_enc=sealed)
        )

    async def delete(self, instance_id: str) -> None:
        for table in (SnapshotRow, CapabilityRow, JwtKeyRow):
            _ = await self._session.execute(delete(table).where(table.instance_id == instance_id))
        _ = await self._session.execute(delete(InstanceRow).where(InstanceRow.id == instance_id))

    async def record_health(
        self, instance_id: str, *, status: InstanceStatus, latency_ms: int | None, seen_at: datetime | None
    ) -> None:
        values: dict[str, Any] = {"status": status.value, "latency_ms": latency_ms}
        if seen_at is not None:
            values["last_seen_at"] = seen_at
        _ = await self._session.execute(
            update(InstanceRow)
            .where(InstanceRow.id == instance_id, InstanceRow.status != InstanceStatus.DISABLED.value)
            .values(**values)
        )

    async def commit(self) -> None:
        await self._session.commit()


def _key(row: JwtKeyRow) -> JwtKey:
    return JwtKey(
        instance_id=row.instance_id,
        kid=row.kid,
        alg=row.alg,
        public_pem=row.public_pem,
        status=KeyStatus(row.status),
        created_at=aware(row.created_at),
        activated_at=aware_or_none(row.activated_at),
    )


class SqlKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, key: JwtKey, private_sealed: str) -> None:
        self._session.add(
            JwtKeyRow(
                instance_id=key.instance_id,
                kid=key.kid,
                alg=key.alg,
                public_pem=key.public_pem,
                private_enc=private_sealed,
                status=key.status.value,
                created_at=key.created_at,
                activated_at=key.activated_at,
            )
        )
        await self._session.flush()

    async def list(self, instance_id: str, statuses: Sequence[KeyStatus] | None = None) -> list[JwtKey]:
        statement = select(JwtKeyRow).where(JwtKeyRow.instance_id == instance_id).order_by(JwtKeyRow.created_at)
        if statuses:
            statement = statement.where(JwtKeyRow.status.in_([status.value for status in statuses]))
        return [_key(row) for row in await self._session.scalars(statement)]

    async def private(self, instance_id: str, kid: str) -> str | None:
        return await self._session.scalar(
            select(JwtKeyRow.private_enc).where(JwtKeyRow.instance_id == instance_id, JwtKeyRow.kid == kid)
        )

    async def set_status(self, instance_id: str, kid: str, status: KeyStatus, at: datetime) -> None:
        values: dict[str, Any] = {"status": status.value}
        if status is KeyStatus.ACTIVE:
            values["activated_at"] = at
        if status is KeyStatus.RETIRED:
            values["retired_at"] = at
        _ = await self._session.execute(
            update(JwtKeyRow).where(JwtKeyRow.instance_id == instance_id, JwtKeyRow.kid == kid).values(**values)
        )


class SqlSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, instance_id: str, kind: str, payload: Any, fetched_at: datetime) -> None:  # noqa: ANN401
        digest = hashlib.sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).hexdigest()
        latest = await self._session.scalar(
            select(SnapshotRow)
            .where(SnapshotRow.instance_id == instance_id, SnapshotRow.kind == kind)
            .order_by(SnapshotRow.fetched_at.desc())
            .limit(1)
        )
        if latest is not None and latest.hash == digest:
            latest.fetched_at = fetched_at  # unchanged: keep one row, refresh its time
        else:
            self._session.add(
                SnapshotRow(instance_id=instance_id, kind=kind, payload=payload, hash=digest, fetched_at=fetched_at)
            )
        _ = await self._session.execute(
            delete(SnapshotRow)
            .where(
                SnapshotRow.instance_id == instance_id,
                SnapshotRow.kind == kind,
                SnapshotRow.fetched_at < fetched_at - SNAPSHOT_HISTORY,
            )
            # No in-session evaluation: SQLite hands back naive datetimes that can't be compared to aware ones.
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()

    async def latest(self, instance_id: str, kind: str) -> tuple[Any, datetime] | None:
        row = await self._session.scalar(
            select(SnapshotRow)
            .where(SnapshotRow.instance_id == instance_id, SnapshotRow.kind == kind)
            .order_by(SnapshotRow.fetched_at.desc())
            .limit(1)
        )
        return (row.payload, aware(row.fetched_at)) if row else None

    async def save_capabilities(self, instance_id: str, capabilities: Sequence[Capability], at: datetime) -> None:
        _ = await self._session.execute(delete(CapabilityRow).where(CapabilityRow.instance_id == instance_id))
        self._session.add_all(
            CapabilityRow(
                instance_id=instance_id,
                capability=item.name,
                status=item.status,
                detail=item.detail or None,
                probed_at=at,
            )
            for item in capabilities
        )
        await self._session.flush()

    async def capabilities(self, instance_id: str) -> tuple[list[Capability], datetime | None]:
        rows = list(
            await self._session.scalars(
                select(CapabilityRow).where(CapabilityRow.instance_id == instance_id).order_by(CapabilityRow.capability)
            )
        )
        items = [Capability(row.capability, cast("CapabilityStatus", row.status), row.detail or "") for row in rows]
        return items, (aware(rows[0].probed_at) if rows else None)
