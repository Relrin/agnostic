"""Tables owned by the assistant module (``asst_*``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from agnostic_kernel.db import JsonDocument, TimestampMixin, make_metadata


class AssistantBase(DeclarativeBase):
    metadata = make_metadata()


class SettingsRow(AssistantBase):
    """One row (``id = 1``): the org's AI features."""

    __tablename__ = "asst_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    models: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    endpoint: Mapped[str | None] = mapped_column(String(500))
    api_version: Mapped[str | None] = mapped_column(String(40))
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    """Sealed with the master key; never returned by the API."""
    temperature: Mapped[float] = mapped_column(Float, default=0.1)
    features: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    monthly_token_budget: Mapped[int | None] = mapped_column(Integer)
    user_monthly_tokens: Mapped[int | None] = mapped_column(Integer)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=10)
    redact_tool_args: Mapped[bool] = mapped_column(Boolean, default=False)
    redact_user_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    audit_question_text: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    data_notice: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationRow(TimestampMixin, AssistantBase):
    __tablename__ = "asst_conversations"
    __table_args__ = (Index("ix_asst_conversations_owner", "user_id", "instance_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40))
    instance_id: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))


class MessageRow(AssistantBase):
    __tablename__ = "asst_messages"
    __table_args__ = (
        Index("ix_asst_messages_conversation", "conversation_id", "created_at"),
        Index("ix_asst_messages_reuse", "user_id", "instance_id", "kind", "subject_key"),
        Index("ix_asst_messages_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("asst_conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(String(40))
    instance_id: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(12))
    feature: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(40))
    subject: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    subject_key: Mapped[str | None] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12))
    tool_calls: Mapped[list[Any]] = mapped_column(JsonDocument)
    sources: Mapped[list[Any]] = mapped_column(JsonDocument)
    model: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttachmentRow(AssistantBase):
    __tablename__ = "asst_attachments"
    __table_args__ = (Index("ix_asst_attachments_message", "message_id"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(40), ForeignKey("asst_messages.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    data: Mapped[bytes | None] = mapped_column(LargeBinary)


class UsageRow(AssistantBase):
    """Tokens used per month, person and feature (the budget's source of truth)."""

    __tablename__ = "asst_usage"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    feature: Mapped[str] = mapped_column(String(20), primary_key=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
