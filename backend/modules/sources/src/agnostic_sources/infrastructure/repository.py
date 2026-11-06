"""SQL store of the sources module; secrets are sealed with the master key on the way in."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any, cast

import orjson
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import NotFoundError, VersionConflictError
from agnostic_sources.application.ports import Secrets
from agnostic_sources.domain.merge import MISSING
from agnostic_sources.domain.model import (
    Change,
    ChangeStatus,
    Conflict,
    Connection,
    Delivery,
    Direction,
    FileBinding,
    PathMapping,
    PullRequest,
    Side,
    Source,
    SyncPolicy,
)
from agnostic_sources.infrastructure.tables import (
    ChangeRow,
    ConflictRow,
    ConnectionRow,
    FileBindingRow,
    PathMappingRow,
    PullRequestRow,
    SourceRow,
    SyncPolicyRow,
    WebhookDeliveryRow,
)


class SqlSourceStore:
    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    # ---------------------------------------------------------------- connections

    async def connections(self) -> list[Connection]:
        rows = await self._session.scalars(select(ConnectionRow).order_by(ConnectionRow.name))
        return [_connection(row) for row in rows]

    async def connection(self, connection_id: str) -> Connection | None:
        row = await self._session.get(ConnectionRow, connection_id)
        return _connection(row) if row is not None else None

    async def save_connection(
        self, connection: Connection, secrets: Secrets | None, *, expected_version: int | None = None
    ) -> Connection:
        row = await self._session.get(ConnectionRow, connection.id)
        if row is None:
            row = ConnectionRow(id=connection.id, version=0, created_by=connection.created_by)
            self._session.add(row)
        elif expected_version is not None and row.version != expected_version:
            raise VersionConflictError(f"{row.name} was changed by someone else; reload it.")
        row.name = connection.name
        row.provider = connection.provider
        row.auth_kind = connection.auth_kind
        row.access = connection.access
        row.api_url = connection.api_url
        row.web_url = connection.web_url
        row.app_slug = connection.app_slug
        row.installation_id = connection.installation_id
        row.account = connection.account
        row.status = connection.status
        row.last_error = connection.last_error
        row.last_checked_at = connection.last_checked_at
        if secrets is not None:
            row.config_enc = self._box.seal(orjson.dumps(_secrets_dict(secrets)))
        row.version = (row.version or 0) + 1
        await self._session.flush()
        return _connection(row)

    async def connection_secrets(self, connection_id: str) -> Secrets:
        row = await self._session.get(ConnectionRow, connection_id)
        if row is None or not row.config_enc:
            return Secrets()
        data = cast("dict[str, Any]", orjson.loads(self._box.open(row.config_enc)))
        return Secrets(
            token=data.get("token"),
            private_key=data.get("private_key"),
            app_id=data.get("app_id"),
            webhook_secret=data.get("webhook_secret"),
        )

    async def delete_connection(self, connection_id: str) -> None:
        _ = await self._session.execute(delete(ConnectionRow).where(ConnectionRow.id == connection_id))

    # ---------------------------------------------------------------- sources

    async def sources(self, instance_id: str | None = None) -> list[Source]:
        query = select(SourceRow).order_by(SourceRow.created_at)
        if instance_id is not None:
            query = query.where(SourceRow.instance_id == instance_id)
        return [await self._source(row) for row in await self._session.scalars(query)]

    async def source(self, source_id: str) -> Source | None:
        row = await self._session.get(SourceRow, source_id)
        return await self._source(row) if row is not None else None

    async def _source(self, row: SourceRow) -> Source:
        mappings = await self._session.scalars(
            select(PathMappingRow).where(PathMappingRow.source_id == row.id).order_by(PathMappingRow.position)
        )
        policy = await self._session.get(SyncPolicyRow, row.id)
        return Source(
            id=row.id,
            instance_id=row.instance_id,
            provider=cast("Any", row.provider),
            repo=row.repo,
            branch=row.branch,
            connection_id=row.connection_id,
            clone_url=row.clone_url,
            local_path=row.local_path,
            convention=row.convention,
            mappings=tuple(PathMapping(item.glob, cast("Any", item.target_kind), item.writable) for item in mappings),
            policy=SyncPolicy(
                pull_mode=cast("Any", policy.pull_mode),
                publish_mode=cast("Any", policy.publish_mode),
                branch_template=policy.branch_template,
                commit_template=policy.commit_template,
                block_publish_until_merged=policy.block_publish_until_merged,
            )
            if policy is not None
            else SyncPolicy(),
            status=cast("Any", row.status),
            status_detail=row.status_detail,
            head_sha=row.last_fetched_sha,
            last_fetched_at=aware_or_none(row.last_fetched_at),
            scan_report=row.scan_report,
            webhook_id=row.webhook_id,
            activated_at=aware_or_none(row.activated_at),
            created_by=row.created_by,
            created_at=aware_or_none(row.created_at),
            version=row.version,
        )

    async def save_source(self, source: Source, *, expected_version: int | None = None) -> Source:
        row = await self._session.get(SourceRow, source.id)
        if row is None:
            row = SourceRow(id=source.id, version=0, created_by=source.created_by)
            self._session.add(row)
        elif expected_version is not None and row.version != expected_version:
            raise VersionConflictError("Someone else changed this source meanwhile; reload it.")
        row.instance_id = source.instance_id
        row.connection_id = source.connection_id
        row.provider = source.provider
        row.repo = source.repo
        row.branch = source.branch
        row.clone_url = source.clone_url
        row.local_path = source.local_path
        row.convention = source.convention
        row.status = source.status
        row.status_detail = source.status_detail
        row.last_fetched_sha = source.head_sha
        row.last_fetched_at = source.last_fetched_at
        row.scan_report = source.scan_report
        row.webhook_id = source.webhook_id
        row.activated_at = source.activated_at
        row.version = (row.version or 0) + 1
        _ = await self._session.execute(delete(PathMappingRow).where(PathMappingRow.source_id == source.id))
        for position, mapping in enumerate(source.mappings):
            self._session.add(
                PathMappingRow(
                    source_id=source.id,
                    position=position,
                    glob=mapping.glob,
                    target_kind=mapping.target_kind,
                    writable=mapping.writable,
                )
            )
        policy = await self._session.get(SyncPolicyRow, source.id)
        if policy is None:
            policy = SyncPolicyRow(source_id=source.id)
            self._session.add(policy)
        policy.pull_mode = source.policy.pull_mode
        policy.publish_mode = source.policy.publish_mode
        policy.branch_template = source.policy.branch_template
        policy.commit_template = source.policy.commit_template
        policy.block_publish_until_merged = source.policy.block_publish_until_merged
        await self._session.flush()
        return await self._source(row)

    async def source_secret(self, source_id: str) -> str | None:
        row = await self._session.get(SourceRow, source_id)
        if row is None or not row.webhook_secret_enc:
            return None
        return self._box.open(row.webhook_secret_enc).decode()

    async def set_source_secret(self, source_id: str, secret: str | None) -> None:
        row = await self._session.get(SourceRow, source_id)
        if row is None:
            raise NotFoundError(f"There is no source {source_id}.")
        row.webhook_secret_enc = self._box.seal(secret.encode()) if secret else None

    async def delete_source(self, source_id: str) -> None:
        for table in (PathMappingRow, SyncPolicyRow):
            _ = await self._session.execute(delete(table).where(table.source_id == source_id))
        for table in (FileBindingRow, ChangeRow, ConflictRow, PullRequestRow, WebhookDeliveryRow):
            _ = await self._session.execute(delete(table).where(table.source_id == source_id))
        _ = await self._session.execute(delete(SourceRow).where(SourceRow.id == source_id))

    # ---------------------------------------------------------------- bindings

    async def bindings(self, source_id: str) -> list[FileBinding]:
        rows = await self._session.scalars(
            select(FileBindingRow).where(FileBindingRow.source_id == source_id).order_by(FileBindingRow.path)
        )
        return [_binding(row) for row in rows]

    async def bindings_for_component(self, instance_id: str, component_id: str) -> list[tuple[Source, FileBinding]]:
        rows = await self._session.execute(
            select(FileBindingRow, SourceRow)
            .join(SourceRow, SourceRow.id == FileBindingRow.source_id)
            .where(FileBindingRow.component_id == component_id, SourceRow.instance_id == instance_id)
            .order_by(SourceRow.created_at)
        )
        return [(await self._source(source), _binding(binding)) for binding, source in rows]

    async def save_binding(self, binding: FileBinding) -> None:
        row = await self._session.get(FileBindingRow, binding.id)
        if row is None:
            row = FileBindingRow(id=binding.id)
            self._session.add(row)
        row.source_id = binding.source_id
        row.path = binding.path
        row.component_kind = binding.component_kind
        row.component_id = binding.component_id
        row.last_synced_sha = binding.last_synced_sha
        row.last_synced_version = binding.last_synced_version
        row.content_hash = binding.content_hash
        row.synced_code = binding.synced_code
        row.synced_config = binding.synced_config
        row.updated_at = utcnow()
        await self._session.flush()

    async def delete_binding(self, binding_id: str) -> None:
        _ = await self._session.execute(delete(FileBindingRow).where(FileBindingRow.id == binding_id))

    # ---------------------------------------------------------------- changes

    async def changes(
        self, source_id: str, direction: Direction | None = None, statuses: Sequence[ChangeStatus] | None = None
    ) -> list[Change]:
        query = select(ChangeRow).where(ChangeRow.source_id == source_id)
        if direction is not None:
            query = query.where(ChangeRow.direction == direction)
        if statuses is not None:
            query = query.where(ChangeRow.status.in_(list(statuses)))
        rows = await self._session.scalars(query.order_by(ChangeRow.created_at, ChangeRow.path))
        return [_change(row) for row in rows]

    async def change(self, change_id: str) -> Change | None:
        row = await self._session.get(ChangeRow, change_id)
        return _change(row) if row is not None else None

    async def save_change(self, change: Change) -> None:
        row = await self._session.get(ChangeRow, change.id)
        if row is None:
            row = ChangeRow(id=change.id)
            self._session.add(row)
        for name in (
            "source_id",
            "direction",
            "path",
            "component_kind",
            "component_id",
            "binding_id",
            "base_sha",
            "commit_sha",
            "blob",
            "author_name",
            "author_email",
            "committed_at",
            "message",
            "additions",
            "deletions",
            "before_code",
            "after_code",
            "config",
            "base_config",
            "outcome",
            "diagnostics",
            "incoming_marks",
            "draft_version",
            "summary",
            "included",
            "status",
            "result_version",
        ):
            setattr(row, name, getattr(change, name))
        await self._session.flush()

    # ---------------------------------------------------------------- conflicts

    async def conflicts(self, source_id: str, *, open_only: bool = True) -> list[Conflict]:
        query = select(ConflictRow).where(ConflictRow.source_id == source_id)
        if open_only:
            query = query.where(ConflictRow.status == "open")
        rows = await self._session.scalars(query.order_by(ConflictRow.created_at, ConflictRow.field_path))
        return [_conflict(row) for row in rows]

    async def conflicts_for_change(self, change_id: str) -> list[Conflict]:
        rows = await self._session.scalars(
            select(ConflictRow).where(ConflictRow.change_id == change_id).order_by(ConflictRow.field_path)
        )
        return [_conflict(row) for row in rows]

    async def conflict(self, conflict_id: str) -> Conflict | None:
        row = await self._session.get(ConflictRow, conflict_id)
        return _conflict(row) if row is not None else None

    async def save_conflict(self, conflict: Conflict) -> None:
        row = await self._session.get(ConflictRow, conflict.id)
        if row is None:
            row = ConflictRow(id=conflict.id)
            self._session.add(row)
        row.source_id = conflict.source_id
        row.change_id = conflict.change_id
        row.path = conflict.path
        row.component_id = conflict.component_id
        row.field_path = conflict.field_path
        row.base_value = _wrap(conflict.base_value)
        row.repo_side = _side_dict(conflict.repo_side)
        row.studio_side = _side_dict(conflict.studio_side)
        row.status = conflict.status
        row.resolution = conflict.resolution
        row.resolved_value = _wrap(conflict.resolved_value) if conflict.resolution == "merged" else None
        row.resolved_by = conflict.resolved_by
        row.resolved_by_name = conflict.resolved_by_name
        row.resolved_at = conflict.resolved_at
        await self._session.flush()

    async def open_conflict_count(self, instance_id: str) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(ConflictRow)
            .join(SourceRow, SourceRow.id == ConflictRow.source_id)
            .where(SourceRow.instance_id == instance_id, ConflictRow.status == "open")
        )
        return int(count or 0)

    # ---------------------------------------------------------------- pull requests

    async def pull_requests(self, source_id: str | None = None, *, open_only: bool = False) -> list[PullRequest]:
        query = select(PullRequestRow)
        if source_id is not None:
            query = query.where(PullRequestRow.source_id == source_id)
        if open_only:
            query = query.where(PullRequestRow.status == "open")
        rows = await self._session.scalars(query.order_by(PullRequestRow.created_at.desc()))
        return [_pull_request(row) for row in rows]

    async def pull_request(self, pull_request_id: str) -> PullRequest | None:
        row = await self._session.get(PullRequestRow, pull_request_id)
        return _pull_request(row) if row is not None else None

    async def save_pull_request(self, pull_request: PullRequest) -> None:
        row = await self._session.get(PullRequestRow, pull_request.id)
        if row is None:
            row = PullRequestRow(id=pull_request.id)
            self._session.add(row)
        row.source_id = pull_request.source_id
        row.number = pull_request.number
        row.url = pull_request.url
        row.branch = pull_request.branch
        row.base_branch = pull_request.base_branch
        row.head_sha = pull_request.head_sha
        row.status = pull_request.status
        row.merge_sha = pull_request.merge_sha
        row.components = [dict(item) for item in pull_request.components]
        row.review_requirement = pull_request.review_requirement
        row.title = pull_request.title
        row.opened_by = pull_request.opened_by
        row.opened_by_name = pull_request.opened_by_name
        row.merged_at = pull_request.merged_at
        row.last_checked_at = pull_request.last_checked_at
        await self._session.flush()

    # ---------------------------------------------------------------- webhook deliveries

    async def record_delivery(self, delivery: Delivery) -> bool:
        existing = await self._session.scalar(
            select(WebhookDeliveryRow.id).where(
                WebhookDeliveryRow.source_id == delivery.source_id,
                WebhookDeliveryRow.delivery_id == delivery.delivery_id,
            )
        )
        if existing is not None:
            return False
        try:
            async with self._session.begin_nested():
                self._session.add(
                    WebhookDeliveryRow(
                        id=delivery.id,
                        source_id=delivery.source_id,
                        provider=delivery.provider,
                        delivery_id=delivery.delivery_id,
                        event=delivery.event[:60],
                        received_at=delivery.received_at,
                    )
                )
        except IntegrityError:
            return False
        return True

    async def finish_delivery(self, delivery_id: str, error: str | None) -> None:
        row = await self._session.get(WebhookDeliveryRow, delivery_id)
        if row is not None:
            row.processed_at = utcnow()
            row.error = error

    async def deliveries(self, source_id: str, limit: int = 50) -> list[Delivery]:
        rows = await self._session.scalars(
            select(WebhookDeliveryRow)
            .where(WebhookDeliveryRow.source_id == source_id)
            .order_by(WebhookDeliveryRow.received_at.desc())
            .limit(limit)
        )
        return [
            Delivery(
                id=row.id,
                source_id=row.source_id,
                provider=cast("Any", row.provider),
                delivery_id=row.delivery_id,
                event=row.event,
                received_at=aware(row.received_at),
                processed_at=aware_or_none(row.processed_at),
                error=row.error,
            )
            for row in rows
        ]

    async def prune_deliveries(self, older_than_days: int) -> int:
        cutoff = utcnow() - timedelta(days=older_than_days)
        result = await self._session.execute(delete(WebhookDeliveryRow).where(WebhookDeliveryRow.received_at < cutoff))
        return int(getattr(result, "rowcount", 0) or 0)

    async def commit(self) -> None:
        await self._session.commit()


# ---------------------------------------------------------------- mapping


def _secrets_dict(secrets: Secrets) -> dict[str, str]:
    values = {
        "token": secrets.token,
        "private_key": secrets.private_key,
        "app_id": secrets.app_id,
        "webhook_secret": secrets.webhook_secret,
    }
    return {key: value for key, value in values.items() if value}


def _connection(row: ConnectionRow) -> Connection:
    return Connection(
        id=row.id,
        name=row.name,
        provider=cast("Any", row.provider),
        auth_kind=cast("Any", row.auth_kind),
        access=cast("Any", row.access),
        api_url=row.api_url,
        web_url=row.web_url,
        app_slug=row.app_slug,
        installation_id=row.installation_id,
        account=row.account,
        status=row.status,
        last_error=row.last_error,
        last_checked_at=aware_or_none(row.last_checked_at),
        created_by=row.created_by,
        created_at=aware_or_none(row.created_at),
        version=row.version,
    )


def _binding(row: FileBindingRow) -> FileBinding:
    return FileBinding(
        id=row.id,
        source_id=row.source_id,
        path=row.path,
        component_kind=cast("Any", row.component_kind),
        component_id=row.component_id,
        last_synced_sha=row.last_synced_sha,
        last_synced_version=row.last_synced_version,
        content_hash=row.content_hash,
        synced_code=row.synced_code,
        synced_config=row.synced_config,
    )


def _change(row: ChangeRow) -> Change:
    return Change(
        id=row.id,
        source_id=row.source_id,
        direction=cast("Any", row.direction),
        path=row.path,
        component_kind=cast("Any", row.component_kind),
        component_id=row.component_id,
        binding_id=row.binding_id,
        base_sha=row.base_sha,
        commit_sha=row.commit_sha,
        blob=row.blob,
        author_name=row.author_name,
        author_email=row.author_email,
        committed_at=aware_or_none(row.committed_at),
        message=row.message,
        additions=row.additions,
        deletions=row.deletions,
        before_code=row.before_code,
        after_code=row.after_code,
        config=row.config,
        base_config=row.base_config,
        outcome=dict(row.outcome or {}),
        diagnostics=list(row.diagnostics or []),
        incoming_marks=dict(row.incoming_marks or {}),
        draft_version=row.draft_version,
        summary=row.summary,
        included=row.included,
        status=cast("Any", row.status),
        result_version=row.result_version,
        created_at=aware_or_none(row.created_at),
        updated_at=aware_or_none(row.updated_at),
    )


def _wrap(value: object) -> dict[str, Any]:
    return {"present": False} if value is MISSING else {"present": True, "value": value}


def _unwrap(data: dict[str, Any] | None) -> object:
    if not data or not data.get("present"):
        return MISSING
    return data.get("value")


def _side_dict(side: Side) -> dict[str, Any]:
    return {
        "present": side.present and side.value is not MISSING,
        "value": None if side.value is MISSING else side.value,
        "author": side.author,
        "reference": side.reference,
    }


def _side(data: dict[str, Any]) -> Side:
    present = bool(data.get("present", True))
    return Side(
        value=data.get("value") if present else MISSING,
        author=data.get("author"),
        reference=data.get("reference"),
        present=present,
    )


def _conflict(row: ConflictRow) -> Conflict:
    return Conflict(
        id=row.id,
        source_id=row.source_id,
        change_id=row.change_id,
        path=row.path,
        component_id=row.component_id,
        field_path=row.field_path,
        base_value=_unwrap(row.base_value),
        repo_side=_side(row.repo_side),
        studio_side=_side(row.studio_side),
        status=cast("Any", row.status),
        resolution=cast("Any", row.resolution),
        resolved_value=_unwrap(row.resolved_value) if row.resolved_value else None,
        resolved_by=row.resolved_by,
        resolved_by_name=row.resolved_by_name,
        resolved_at=aware_or_none(row.resolved_at),
        created_at=aware_or_none(row.created_at),
    )


def _pull_request(row: PullRequestRow) -> PullRequest:
    return PullRequest(
        id=row.id,
        source_id=row.source_id,
        number=row.number,
        url=row.url,
        branch=row.branch,
        base_branch=row.base_branch,
        head_sha=row.head_sha,
        status=cast("Any", row.status),
        merge_sha=row.merge_sha,
        components=tuple(row.components or ()),
        review_requirement=row.review_requirement,
        title=row.title,
        opened_by=row.opened_by,
        opened_by_name=row.opened_by_name,
        created_at=aware_or_none(row.created_at),
        merged_at=aware_or_none(row.merged_at),
        last_checked_at=aware_or_none(row.last_checked_at),
    )
