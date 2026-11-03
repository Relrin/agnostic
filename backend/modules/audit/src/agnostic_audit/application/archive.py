"""Retention: monthly partitions, the archive tier (S3-compatible storage), restores, and chain verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from compression import zstd
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from agnostic_audit.application.policy import PolicyService
from agnostic_audit.application.ports import (
    ArchiveRepository,
    AuditRepository,
    EventQuery,
    ObjectStoreError,
    ObjectStores,
    PartitionMaintenance,
    PolicyStore,
    Position,
    UnitOfWork,
)
from agnostic_audit.domain.archive import (
    RESTORE_DAYS,
    ArchiveTarget,
    ArchiveVerificationError,
    Manifest,
    month_bounds,
    object_keys,
    parse_month,
)
from agnostic_audit.domain.chain import ChainResult, ChainVerifier
from agnostic_audit.domain.events import AuditEvent, event_document, event_from_document
from agnostic_audit.domain.governance import ArchivedMonth
from agnostic_kernel.db import utcnow
from agnostic_kernel.domain_events import DomainEvents
from agnostic_kernel.errors import NotFoundError, ValidationFailedError
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

RESTORE_TASK = "audit.restore"
ARCHIVE_FAILED_EVENT = "audit.archive_failed"
_INSERT_BATCH = 500
MONTHS_AHEAD = 2


@dataclass(frozen=True, slots=True)
class MaintenanceReport:
    created: list[str]
    dropped: list[str]
    archived: list[str]
    failed: list[str]


def _encode(event: AuditEvent) -> bytes:
    return (
        json.dumps(event_document(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


class MaintainPartitions:
    """Monthly retention.

    Creates the next months' partitions, archives months past hot retention (when the archive is on), and only then
    drops them; drops restored months once their window ends (they are never archived twice).
    """

    def __init__(
        self,
        maintenance: PartitionMaintenance,
        policies: PolicyService,
        policy_store: PolicyStore,
        archives: ArchiveRepository,
        stores: ObjectStores,
        uow: UnitOfWork,
        domain_events: DomainEvents,
    ) -> None:
        self._maintenance = maintenance
        self._policies = policies
        self._policy_store = policy_store
        self._archives = archives
        self._stores = stores
        self._uow = uow
        self._domain_events = domain_events

    async def __call__(self, now: datetime | None = None) -> MaintenanceReport:  # noqa: C901  (one step per case)
        now = now or utcnow()
        policy = await self._policies.current()
        created = await self._maintenance.ensure_partitions(now, MONTHS_AHEAD)
        dropped: list[str] = []
        archived: list[str] = []
        failed: list[str] = []
        known = {archive.month: archive for archive in await self._archives.list()}

        for archive in known.values():
            if archive.restore_expires_at is not None and archive.restore_expires_at <= now:
                await self._maintenance.drop_month(archive.month)
                await self._archives.save(replace(archive, restored_at=None, restore_expires_at=None))
                await self._uow.commit()
                dropped.append(archive.month)
        active_restores = any(archive.restored(now) for archive in known.values())

        if not policy.archive_enabled and not active_restores:
            dropped.extend(await self._maintenance.drop_expired(now, policy.hot_retention_days))
        else:
            for month in await self._maintenance.expired_months(now, policy.hot_retention_days):
                archive = known.get(month)
                if archive is not None:
                    if not archive.restored(now):
                        await self._maintenance.drop_month(month)  # archived and verified on an earlier run
                        dropped.append(month)
                    continue
                if not policy.archive_enabled or await self._maintenance.month_count(month) == 0:
                    await self._maintenance.drop_month(month)
                    dropped.append(month)
                    continue
                error = await self._archive(month, now)
                if error is None:
                    archived.append(month)
                    dropped.append(month)
                else:
                    failed.append(month)
            if archived and not failed:
                await self._policy_store.record_archive_run(now, None)
                await self._uow.commit()
        if created or dropped or archived or failed:
            log.info("audit.partitions", created=created, dropped=dropped, archived=archived, failed=failed)
        return MaintenanceReport(created=created, dropped=dropped, archived=archived, failed=failed)

    async def _archive(self, month: str, now: datetime) -> str | None:
        """Archive one month and drop it; on failure keep it, note the error and tell admins."""
        try:
            await self.archive_month(month, await self._target(), now)
        except (ObjectStoreError, ArchiveVerificationError, OSError) as exc:
            error = str(exc) or type(exc).__name__
            log.warning("audit.archive_failed", month=month, error=error)
            await self._uow.rollback()
            await self._policy_store.record_archive_run(now, f"{month}: {error}")
            await self._uow.commit()
            await self._domain_events.publish(ARCHIVE_FAILED_EVENT, {"month": month, "error": error})
            return error
        return None

    async def _target(self) -> ArchiveTarget:
        target = await self._policies.target()
        if target is None:
            raise ObjectStoreError("The archive is on, but its bucket settings are incomplete.")
        return target

    async def archive_month(self, month: str, target: ArchiveTarget, now: datetime) -> ArchivedMonth | None:
        compressor = zstd.ZstdCompressor()
        chunks: list[bytes] = []
        count = 0
        chain_head: str | None = None
        async for event in self._maintenance.month_events(month):
            chunks.append(compressor.compress(_encode(event)))
            count += 1
            chain_head = event.hash or chain_head
        if count == 0:
            await self._maintenance.drop_month(month)
            return None
        chunks.append(compressor.flush())
        data = b"".join(chunks)
        digest = hashlib.sha256(data).hexdigest()
        data_key, manifest_key = object_keys(target.prefix, month)
        locked = target.object_lock_mode != "off" and target.retention_days is not None
        retain_until = now + timedelta(days=target.retention_days or 0) if locked else None
        manifest = Manifest(
            month=month, event_count=count, sha256=digest, bytes=len(data), chain_head=chain_head, created_at=now
        )
        store = self._stores.open(target)
        await store.put(data_key, data, content_type="application/zstd", retain_until=retain_until)
        await store.put(manifest_key, manifest.to_json(), content_type="application/json", retain_until=retain_until)

        # Read everything back before anything is dropped.
        head = await store.head(data_key)
        if head.size != len(data):
            raise ArchiveVerificationError(f"{data_key}: stored {head.size} bytes, wrote {len(data)}")
        if hashlib.sha256(await store.get(data_key)).hexdigest() != digest:
            raise ArchiveVerificationError(f"{data_key}: the stored object's SHA-256 differs from what was written")
        stored_manifest = Manifest.parse(await store.get(manifest_key))
        if (stored_manifest.sha256, stored_manifest.event_count) != (digest, count):
            raise ArchiveVerificationError(f"{manifest_key}: the stored manifest differs from what was written")
        if await self._maintenance.month_count(month) != count:
            raise ArchiveVerificationError(f"{month}: events arrived while archiving; trying again next run")

        archive = ArchivedMonth(
            month=month,
            object_key=data_key,
            manifest_key=manifest_key,
            bytes=len(data),
            event_count=count,
            sha256=digest,
            chain_head=chain_head,
            archived_at=now,
            purge_after=now + timedelta(days=target.retention_days) if target.retention_days else None,
            restored_at=None,
            restore_expires_at=None,
        )
        await self._archives.save(archive)
        await self._uow.commit()
        await self._maintenance.drop_month(month)
        return archive


class Archives:
    def __init__(
        self,
        archives: ArchiveRepository,
        maintenance: PartitionMaintenance,
        policies: PolicyService,
        stores: ObjectStores,
        uow: UnitOfWork,
    ) -> None:
        self._archives = archives
        self._maintenance = maintenance
        self._policies = policies
        self._stores = stores
        self._uow = uow

    async def list(self) -> list[ArchivedMonth]:
        return await self._archives.list()

    async def get(self, month: str) -> ArchivedMonth:
        try:
            _ = parse_month(month)
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc
        archive = await self._archives.get(month)
        if archive is None:
            raise NotFoundError(f"No archive for {month}.")
        return archive

    async def restore(self, month: str, now: datetime | None = None) -> ArchivedMonth:
        """Download, verify against the manifest, and re-insert the month's events for 7 days of searching."""
        now = now or utcnow()
        archive = await self.get(month)
        if archive.restored(now):
            return archive
        target = await self._policies.target()
        if target is None:
            raise ValidationFailedError("Configure the archive bucket before restoring.")
        store = self._stores.open(target)
        manifest = Manifest.parse(await store.get(archive.manifest_key))
        data = await store.get(archive.object_key)
        digest = hashlib.sha256(data).hexdigest()
        if digest != manifest.sha256 or digest != archive.sha256:
            raise ArchiveVerificationError(f"{archive.object_key}: SHA-256 doesn't match the manifest")
        events = [event_from_document(json.loads(line)) for line in zstd.decompress(data).splitlines() if line.strip()]
        if len(events) != manifest.event_count:
            raise ArchiveVerificationError(
                f"{archive.object_key}: {len(events)} events, the manifest says {manifest.event_count}"
            )
        start, end = month_bounds(month)
        if any(not start <= event.occurred_at < end for event in events):
            raise ArchiveVerificationError(f"{archive.object_key}: events outside {month}")
        await self._maintenance.drop_month(month)  # leftovers of an interrupted restore
        await self._maintenance.ensure_month(month)
        try:
            for index in range(0, len(events), _INSERT_BATCH):
                await self._maintenance.insert_events(events[index : index + _INSERT_BATCH])
        except Exception:
            await self._maintenance.drop_month(month)
            raise
        restored = replace(archive, restored_at=now, restore_expires_at=now + timedelta(days=RESTORE_DAYS))
        await self._archives.save(restored)
        await self._uow.commit()
        return restored


class VerifyChain:
    def __init__(self, events: AuditRepository) -> None:
        self._events = events

    async def __call__(self, since: datetime | None = None, until: datetime | None = None) -> ChainResult:
        verifier = ChainVerifier()
        query = EventQuery(since=since, until=until)
        after: Position | None = None
        while True:
            page: Sequence[AuditEvent] = await self._events.ascending(query, 1000, after)
            for event in page:
                if not verifier.feed(event):
                    return verifier.result()
            if len(page) < 1000:  # noqa: PLR2004
                return verifier.result()
            after = (page[-1].occurred_at, page[-1].id)
