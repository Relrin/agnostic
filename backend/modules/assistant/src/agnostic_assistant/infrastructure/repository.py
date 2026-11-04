"""SQLAlchemy implementation of the assistant's store."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Result, delete, func, null, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_assistant.application.ports import NewMessage, Outcome
from agnostic_assistant.domain.model import (
    Attachment,
    Conversation,
    Message,
    Role,
    SourceRef,
    Status,
    ToolCallRecord,
    ToolStatus,
)
from agnostic_assistant.domain.settings import FEATURES, AiSettings, Feature
from agnostic_assistant.infrastructure.tables import (
    AttachmentRow,
    ConversationRow,
    MessageRow,
    SettingsRow,
    UsageRow,
)
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import aware, aware_or_none, utcnow
from agnostic_kernel.errors import VersionConflictError
from agnostic_kernel.ids import new_id

SETTINGS_ID = 1


def _count(result: Result[Any]) -> int:
    return cast("CursorResult[Any]", result).rowcount or 0


def _settings(row: SettingsRow | None) -> AiSettings:
    if row is None:
        return AiSettings()
    toggles = row.features or {}
    return AiSettings(
        enabled=row.enabled,
        models={k: str(v) for k, v in (row.models or {}).items() if k in FEATURES and v},
        endpoint=row.endpoint,
        api_version=row.api_version,
        has_api_key=row.api_key_enc is not None,
        temperature=row.temperature,
        features={feature: bool(toggles.get(feature, True)) for feature in FEATURES},
        monthly_token_budget=row.monthly_token_budget,
        user_monthly_tokens=row.user_monthly_tokens,
        requests_per_minute=row.requests_per_minute,
        redact_tool_args=row.redact_tool_args,
        redact_user_messages=row.redact_user_messages,
        audit_question_text=row.audit_question_text,
        retention_days=row.retention_days,
        data_notice=row.data_notice,
        version=row.version,
        updated_by=row.updated_by,
        updated_at=aware_or_none(row.updated_at),
    )


def _conversation(row: ConversationRow) -> Conversation:
    return Conversation(
        id=row.id,
        user_id=row.user_id,
        instance_id=row.instance_id,
        title=row.title,
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
    )


def _message(row: MessageRow, attachments: Sequence[Attachment] = ()) -> Message:
    calls = cast("list[dict[str, Any]]", row.tool_calls or [])
    sources = cast("list[dict[str, Any]]", row.sources or [])
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        user_id=row.user_id,
        instance_id=row.instance_id,
        role=cast("Role", row.role),
        feature=cast("Feature", row.feature),
        kind=row.kind,
        subject=row.subject or {},
        content=row.content,
        status=cast("Status", row.status),
        created_at=aware(row.created_at),
        tool_calls=[
            ToolCallRecord(
                str(c["id"]), str(c["name"]), cast("ToolStatus", c["status"]), c.get("duration_ms"), c.get("detail")
            )
            for c in calls
        ],
        sources=[SourceRef(str(s["kind"]), str(s["label"]), str(s["path"])) for s in sources],
        model=row.model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        error=row.error,
        completed_at=aware_or_none(row.completed_at),
        attachments=tuple(attachments),
    )


class SqlAssistantStore:
    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    # ---------------------------------------------------------------- settings

    async def _settings_row(self) -> SettingsRow | None:
        return await self._session.get(SettingsRow, SETTINGS_ID)

    async def settings(self) -> AiSettings:
        return _settings(await self._settings_row())

    async def api_key(self) -> str | None:
        row = await self._settings_row()
        if row is None or row.api_key_enc is None:
            return None
        return self._box.open(row.api_key_enc).decode()

    async def save_settings(
        self, settings: AiSettings, *, api_key: str | None, key_changed: bool, by: str
    ) -> AiSettings:
        row = await self._settings_row()
        if row is None:
            row = SettingsRow(id=SETTINGS_ID, version=0, models={}, features={})
            self._session.add(row)
        elif row.version != settings.version:
            raise VersionConflictError("Someone else changed the AI settings; reload and try again.")
        row.enabled = settings.enabled
        row.models = {str(k): v for k, v in settings.models.items()}
        row.endpoint = settings.endpoint
        row.api_version = settings.api_version
        row.temperature = settings.temperature
        row.features = {str(k): v for k, v in settings.features.items()}
        row.monthly_token_budget = settings.monthly_token_budget
        row.user_monthly_tokens = settings.user_monthly_tokens
        row.requests_per_minute = settings.requests_per_minute
        row.redact_tool_args = settings.redact_tool_args
        row.redact_user_messages = settings.redact_user_messages
        row.audit_question_text = settings.audit_question_text
        row.retention_days = settings.retention_days
        row.data_notice = settings.data_notice
        if key_changed:
            row.api_key_enc = self._box.seal(api_key.encode()) if api_key else None
        row.version = (row.version or 0) + 1
        row.updated_by = by
        row.updated_at = utcnow()
        await self._session.flush()
        return _settings(row)

    # ---------------------------------------------------------------- conversations

    async def conversation(self, conversation_id: str) -> Conversation | None:
        row = await self._session.get(ConversationRow, conversation_id)
        return _conversation(row) if row else None

    async def conversations(self, user_id: str, instance_id: str, limit: int) -> list[Conversation]:
        rows = await self._session.scalars(
            select(ConversationRow)
            .where(ConversationRow.user_id == user_id, ConversationRow.instance_id == instance_id)
            .order_by(ConversationRow.updated_at.desc(), ConversationRow.id.desc())
            .limit(limit)
        )
        return [_conversation(row) for row in rows]

    async def create_conversation(self, user_id: str, instance_id: str, title: str) -> Conversation:
        now = utcnow()
        row = ConversationRow(
            id=new_id("conv"), user_id=user_id, instance_id=instance_id, title=title, created_at=now, updated_at=now
        )
        self._session.add(row)
        await self._session.flush()
        return _conversation(row)

    async def touch_conversation(self, conversation_id: str) -> None:
        _ = await self._session.execute(
            update(ConversationRow).where(ConversationRow.id == conversation_id).values(updated_at=utcnow())
        )

    async def delete_conversation(self, conversation_id: str) -> None:
        ids = select(MessageRow.id).where(MessageRow.conversation_id == conversation_id)
        _ = await self._session.execute(delete(AttachmentRow).where(AttachmentRow.message_id.in_(ids)))
        _ = await self._session.execute(delete(MessageRow).where(MessageRow.conversation_id == conversation_id))
        _ = await self._session.execute(delete(ConversationRow).where(ConversationRow.id == conversation_id))

    # ---------------------------------------------------------------- messages

    async def messages(self, conversation_id: str) -> list[Message]:
        rows = list(
            await self._session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.created_at, MessageRow.id)
            )
        )
        attachments = await self._attachments([row.id for row in rows if row.role == "user"], with_data=False)
        return [_message(row, attachments.get(row.id, ())) for row in rows]

    async def _attachments(self, message_ids: Sequence[str], *, with_data: bool) -> dict[str, list[Attachment]]:
        if not message_ids:
            return {}
        data = AttachmentRow.data if with_data else null()
        query = (
            select(
                AttachmentRow.id,
                AttachmentRow.message_id,
                AttachmentRow.name,
                AttachmentRow.media_type,
                AttachmentRow.size,
                AttachmentRow.text,
                data,
            )
            .where(AttachmentRow.message_id.in_(message_ids))
            .order_by(AttachmentRow.id)
        )
        found: dict[str, list[Attachment]] = {}
        for attachment_id, message_id, name, media_type, size, text, content in await self._session.execute(query):
            found.setdefault(message_id, []).append(Attachment(attachment_id, name, media_type, size, text, content))
        return found

    async def message(self, message_id: str, *, attachments: bool = False) -> Message | None:
        row = await self._session.get(MessageRow, message_id, populate_existing=True)
        if row is None:
            return None
        files = (await self._attachments([row.id], with_data=True)).get(row.id, []) if attachments else []
        return _message(row, files)

    async def add_message(self, message: NewMessage) -> Message:
        row = MessageRow(
            id=new_id("msg"),
            conversation_id=message.conversation_id,
            user_id=message.user_id,
            instance_id=message.instance_id,
            role=message.role,
            feature=message.feature,
            kind=message.kind,
            subject=dict(message.subject),
            subject_key=message.subject_key,
            content=message.content,
            status=message.status,
            tool_calls=[],
            sources=[],
            input_tokens=0,
            output_tokens=0,
            created_at=utcnow(),
        )
        self._session.add(row)
        await self._session.flush()
        for attachment in message.attachments:
            self._session.add(
                AttachmentRow(
                    id=attachment.id,
                    message_id=row.id,
                    name=attachment.name,
                    media_type=attachment.media_type,
                    size=attachment.size,
                    text=attachment.text,
                    data=attachment.data,
                )
            )
        await self._session.flush()
        return _message(row)

    async def start(self, message_id: str, model: str) -> bool:
        result = await self._session.execute(
            update(MessageRow)
            .where(MessageRow.id == message_id, MessageRow.status == "queued")
            .values(status="running", model=model, started_at=utcnow())
        )
        return bool(_count(result))

    async def finish(self, message_id: str, outcome: Outcome) -> None:
        _ = await self._session.execute(
            update(MessageRow)
            .where(MessageRow.id == message_id)
            .values(
                status=outcome.status,
                content=outcome.content,
                tool_calls=[
                    {"id": c.id, "name": c.name, "status": c.status, "duration_ms": c.duration_ms, "detail": c.detail}
                    for c in outcome.tool_calls
                ],
                sources=[{"kind": s.kind, "label": s.label, "path": s.path} for s in outcome.sources],
                model=outcome.model,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                error=outcome.error,
                completed_at=utcnow(),
            )
        )

    async def cancel(self, message_id: str) -> bool:
        result = await self._session.execute(
            update(MessageRow)
            .where(MessageRow.id == message_id, MessageRow.status == "queued")
            .values(status="cancelled", completed_at=utcnow())
        )
        return bool(_count(result))

    async def reusable(self, user_id: str, instance_id: str, kind: str, subject_key: str) -> Message | None:
        row = await self._session.scalar(
            select(MessageRow)
            .where(
                MessageRow.user_id == user_id,
                MessageRow.instance_id == instance_id,
                MessageRow.kind == kind,
                MessageRow.subject_key == subject_key,
                MessageRow.status.in_(("queued", "running", "completed")),
            )
            .order_by(MessageRow.created_at.desc())
            .limit(1)
        )
        return _message(row) if row else None

    # ---------------------------------------------------------------- usage

    async def add_usage(
        self, month: str, user_id: str, feature: Feature, input_tokens: int, output_tokens: int
    ) -> None:
        values = {
            "month": month,
            "user_id": user_id,
            "feature": feature,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        changes = {
            "input_tokens": UsageRow.input_tokens + input_tokens,
            "output_tokens": UsageRow.output_tokens + output_tokens,
        }
        keys = [UsageRow.month, UsageRow.user_id, UsageRow.feature]
        if self._session.get_bind().dialect.name == "postgresql":
            statement = (
                postgresql.insert(UsageRow).values(**values).on_conflict_do_update(index_elements=keys, set_=changes)
            )
        else:
            statement = (
                sqlite.insert(UsageRow).values(**values).on_conflict_do_update(index_elements=keys, set_=changes)
            )
        _ = await self._session.execute(statement)

    async def spent(self, month: str, user_id: str) -> tuple[int, int]:
        total = UsageRow.input_tokens + UsageRow.output_tokens
        org = await self._session.scalar(select(func.coalesce(func.sum(total), 0)).where(UsageRow.month == month))
        mine = await self._session.scalar(
            select(func.coalesce(func.sum(total), 0)).where(UsageRow.month == month, UsageRow.user_id == user_id)
        )
        return int(org or 0), int(mine or 0)

    # ---------------------------------------------------------------- retention

    async def prune(self, before: datetime) -> int:
        old = select(ConversationRow.id).where(ConversationRow.updated_at < before)
        old_messages = select(MessageRow.id).where(
            (MessageRow.conversation_id.in_(old))
            | (MessageRow.conversation_id.is_(None) & (MessageRow.created_at < before))
        )
        _ = await self._session.execute(delete(AttachmentRow).where(AttachmentRow.message_id.in_(old_messages)))
        _ = await self._session.execute(
            delete(MessageRow).where(
                (MessageRow.conversation_id.in_(old))
                | (MessageRow.conversation_id.is_(None) & (MessageRow.created_at < before))
            )
        )
        result = await self._session.execute(delete(ConversationRow).where(ConversationRow.updated_at < before))
        return _count(result)

    async def fail_stale(self, before: datetime, reason: str) -> int:
        result = await self._session.execute(
            update(MessageRow)
            .where(MessageRow.status.in_(("queued", "running")), MessageRow.created_at < before)
            .values(status="failed", error=reason, completed_at=utcnow())
        )
        return _count(result)

    async def commit(self) -> None:
        await self._session.commit()
