"""Retention, archive and hash-chain policy: one row, owned by the audit module."""

from __future__ import annotations

import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, cast

from agnostic_audit.application.ports import ObjectStoreError, ObjectStores, PolicyStore, UnitOfWork
from agnostic_audit.domain.archive import ArchiveTarget
from agnostic_audit.domain.governance import DEFAULT_HOT_RETENTION_DAYS, ObjectLock, Policy
from agnostic_kernel.crypto import SecretBox, SecretDecryptionError
from agnostic_kernel.db import aware_or_none, utcnow
from agnostic_kernel.errors import ValidationFailedError
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

POLICY_FIELDS = (
    "hot_retention_days",
    "archive_enabled",
    "endpoint",
    "bucket",
    "prefix",
    "region",
    "access_key_id",
    "object_lock_mode",
    "archive_retention_days",
    "hash_chain",
)
SECRET_FIELD = "secret_access_key"  # noqa: S105  (a field name)
OBJECT_LOCK_MODES = ("off", "governance", "compliance")


def policy_from(stored: tuple[dict[str, Any], str | None] | None, default_retention: int) -> Policy:
    if stored is None:
        return Policy(hot_retention_days=default_retention)
    values, secret_enc = stored
    return Policy(
        hot_retention_days=int(values.get("hot_retention_days") or default_retention),
        archive_enabled=bool(values.get("archive_enabled")),
        endpoint=values.get("endpoint"),
        bucket=values.get("bucket"),
        prefix=str(values.get("prefix") or ""),
        region=str(values.get("region") or "us-east-1"),
        access_key_id=values.get("access_key_id"),
        has_secret=bool(secret_enc),
        object_lock_mode=cast("ObjectLock", values.get("object_lock_mode") or "off"),
        archive_retention_days=values.get("archive_retention_days"),
        hash_chain=bool(values.get("hash_chain")),
        updated_by=values.get("updated_by"),
        updated_at=aware_or_none(values.get("updated_at")),
        last_archive_at=aware_or_none(values.get("last_archive_at")),
        last_archive_error=values.get("last_archive_error"),
    )


class PolicyCache:
    """The policy as recently read (the record path checks the hash-chain flag on every event)."""

    def __init__(self, load: Callable[[], Awaitable[Policy]], ttl: float = 10.0) -> None:
        self._load = load
        self._ttl = ttl
        self._value: Policy | None = None
        self._expires = 0.0

    async def get(self) -> Policy:
        if self._value is None or time.monotonic() >= self._expires:
            try:
                self._value = await self._load()
            except Exception as exc:  # noqa: BLE001  (auditing must not fail because the policy can't be read)
                log.warning("audit.policy_unavailable", error=str(exc))
                self._value = self._value or Policy(hot_retention_days=DEFAULT_HOT_RETENTION_DAYS)
            self._expires = time.monotonic() + self._ttl
        return self._value

    def invalidate(self) -> None:
        self._value = None


@dataclass(frozen=True, slots=True)
class WriteCheck:
    ok: bool
    error: str | None = None
    latency_ms: int | None = None


class PolicyService:
    def __init__(
        self,
        store: PolicyStore,
        uow: UnitOfWork,
        box: SecretBox,
        cache: PolicyCache,
        stores: ObjectStores,
        default_retention: int,
    ) -> None:
        self._store = store
        self._uow = uow
        self._box = box
        self._cache = cache
        self._stores = stores
        self._default_retention = default_retention

    async def current(self) -> Policy:
        return policy_from(await self._store.load(), self._default_retention)

    async def target(self) -> ArchiveTarget | None:
        """The archive bucket with its decrypted credentials, when the archive is switched on and complete."""
        stored = await self._store.load()
        policy = policy_from(stored, self._default_retention)
        if stored is None or not policy.archive_ready:
            return None
        return self._target(policy, stored[1])

    def _target(self, policy: Policy, secret_enc: str | None, secret: str | None = None) -> ArchiveTarget:
        if secret is None:
            try:
                secret = self._box.open(secret_enc).decode() if secret_enc else ""
            except SecretDecryptionError as exc:
                raise ObjectStoreError(f"The stored secret key can't be decrypted: {exc}") from exc
        return ArchiveTarget(
            endpoint=policy.endpoint or "",
            bucket=policy.bucket or "",
            prefix=policy.prefix,
            region=policy.region,
            access_key_id=policy.access_key_id or "",
            secret_access_key=secret,
            object_lock_mode=policy.object_lock_mode,
            retention_days=policy.archive_retention_days,
        )

    def _merge(self, policy: Policy, changes: Mapping[str, Any]) -> Policy:
        values = {key: changes[key] for key in POLICY_FIELDS if key in changes}
        merged = replace(policy, **values)
        if merged.object_lock_mode not in OBJECT_LOCK_MODES:
            raise ValidationFailedError(f"Object Lock mode must be one of {', '.join(OBJECT_LOCK_MODES)}.")
        if merged.endpoint and not merged.endpoint.startswith(("https://", "http://")):
            raise ValidationFailedError("The endpoint must be an http(s) URL, like https://s3.eu-west-1.amazonaws.com.")
        return merged

    async def update(self, changes: Mapping[str, Any], *, by: str) -> tuple[Policy, Policy]:
        """Apply ``changes`` (policy fields, plus ``secret_access_key``: text sets it, ``""`` clears it).

        Returns ``(before, after)``; the caller audits the change.
        """
        stored = await self._store.load()
        before = policy_from(stored, self._default_retention)
        secret_enc = stored[1] if stored else None
        if SECRET_FIELD in changes:
            secret = changes[SECRET_FIELD]
            secret_enc = self._box.seal(str(secret).encode()) if secret else None
        after = replace(self._merge(before, changes), has_secret=bool(secret_enc), updated_by=by, updated_at=utcnow())
        if after.archive_enabled and not after.archive_ready:
            raise ValidationFailedError(
                "To archive, set the endpoint, bucket, access key id and secret access key.",
            )
        values = {key: getattr(after, key) for key in POLICY_FIELDS}
        values |= {"updated_by": by, "updated_at": after.updated_at}
        await self._store.save(values, secret_enc)
        await self._uow.commit()
        self._cache.invalidate()
        return before, after

    async def test_write(self, changes: Mapping[str, Any]) -> WriteCheck:
        """Write a small object to the bucket, read it back and delete it.

        Uses the stored settings overlaid by ``changes``, so the form can be tested before saving.
        """
        stored = await self._store.load()
        policy = self._merge(policy_from(stored, self._default_retention), changes)
        secret = changes.get(SECRET_FIELD) or None
        if not (policy.endpoint and policy.bucket and policy.access_key_id) or not (secret or (stored and stored[1])):
            return WriteCheck(ok=False, error="Set the endpoint, bucket, access key id and secret access key first.")
        started = time.monotonic()
        try:
            store = self._stores.open(self._target(policy, stored[1] if stored else None, secret))
            key = f"{policy.prefix.strip('/')}/" if policy.prefix.strip("/") else ""
            key += f".agnostic-write-test-{secrets.token_hex(6)}"
            payload = f"agnostic audit archive write test {datetime.now().isoformat()}\n".encode()  # noqa: DTZ005
            await store.put(key, payload, content_type="text/plain")
            if await store.get(key) != payload:
                return WriteCheck(ok=False, error="The object read back differs from what was written.")
            await store.delete(key)
        except ObjectStoreError as exc:
            return WriteCheck(ok=False, error=str(exc), latency_ms=int((time.monotonic() - started) * 1000))
        return WriteCheck(ok=True, latency_ms=int((time.monotonic() - started) * 1000))
