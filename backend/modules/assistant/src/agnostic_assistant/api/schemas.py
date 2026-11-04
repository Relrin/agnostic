"""Request and response bodies of the assistant API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from agnostic_assistant.application.configuration import ConnectionCheck, Status
from agnostic_assistant.domain.explainers import EXPLAINERS
from agnostic_assistant.domain.model import Conversation, Message
from agnostic_assistant.domain.settings import PROVIDERS, AiSettings

type FeatureName = Literal["assistant", "summaries", "suggestions"]


class FeatureModels(BaseModel):
    assistant: str | None = Field(None, description="provider:model, e.g. vllm:Qwen/Qwen3-32B or ollama:qwen3:8b")
    summaries: str | None = Field(None, description="Empty: the assistant's model")
    suggestions: str | None = Field(None, description="Empty: the assistant's model")


class FeatureToggles(BaseModel):
    assistant: bool = True
    summaries: bool = True
    suggestions: bool = True


class ModelProviderOut(BaseModel):
    id: str
    label: str


class AiSettingsOut(BaseModel):
    enabled: bool
    models: FeatureModels
    endpoint: str | None
    api_version: str | None
    has_api_key: bool
    """The key itself is never returned."""
    temperature: float
    features: FeatureToggles
    monthly_token_budget: int | None
    user_monthly_tokens: int | None
    requests_per_minute: int
    redact_tool_args: bool
    redact_user_messages: bool
    audit_question_text: bool
    retention_days: int
    data_notice: str | None
    version: int
    updated_by: str | None
    updated_at: datetime | None
    providers: list[ModelProviderOut]

    @classmethod
    def of(cls, settings: AiSettings) -> AiSettingsOut:
        return cls(
            enabled=settings.enabled,
            models=FeatureModels(**dict(settings.models)),
            endpoint=settings.endpoint,
            api_version=settings.api_version,
            has_api_key=settings.has_api_key,
            temperature=settings.temperature,
            features=FeatureToggles(**dict(settings.features)),
            monthly_token_budget=settings.monthly_token_budget,
            user_monthly_tokens=settings.user_monthly_tokens,
            requests_per_minute=settings.requests_per_minute,
            redact_tool_args=settings.redact_tool_args,
            redact_user_messages=settings.redact_user_messages,
            audit_question_text=settings.audit_question_text,
            retention_days=settings.retention_days,
            data_notice=settings.data_notice,
            version=settings.version,
            updated_by=settings.updated_by,
            updated_at=settings.updated_at,
            providers=[ModelProviderOut(id=key, label=label) for key, label in PROVIDERS.items()],
        )


class AiSettingsIn(BaseModel):
    """Only the fields sent change."""

    enabled: bool | None = None
    models: FeatureModels | None = None
    endpoint: str | None = Field(None, max_length=500)
    api_version: str | None = Field(None, max_length=40)
    api_key: str | None = Field(None, max_length=4000, description='Write-only: omit to keep, "" to remove')
    temperature: float | None = Field(None, ge=0, le=2)
    features: FeatureToggles | None = None
    monthly_token_budget: int | None = Field(None, ge=0, description="0 removes the limit")
    user_monthly_tokens: int | None = Field(None, ge=0, description="0 removes the limit")
    requests_per_minute: int | None = Field(None, ge=1, le=600)
    redact_tool_args: bool | None = None
    redact_user_messages: bool | None = None
    audit_question_text: bool | None = None
    retention_days: int | None = Field(None, ge=1, le=3650)
    data_notice: str | None = Field(None, max_length=1000)
    version: int | None = Field(None, description="The version you edited; a newer one is a conflict")

    def changes(self) -> dict[str, Any]:
        sent = self.model_dump(exclude_unset=True, exclude={"api_key", "version"})
        for name in ("monthly_token_budget", "user_monthly_tokens"):
            if name in sent and not sent[name]:
                sent[name] = None
        if "models" in sent:
            models = cast("dict[str, str | None]", sent["models"] or {})
            sent["models"] = {k: v for k, v in models.items() if v is not None}
        if "features" in sent:
            sent["features"] = sent["features"] or {}
        return sent


class ConnectionCheckIn(BaseModel):
    feature: FeatureName = "assistant"


class ConnectionCheckOut(BaseModel):
    ok: bool
    model: str
    latency_ms: int | None
    detail: str

    @classmethod
    def of(cls, check: ConnectionCheck) -> ConnectionCheckOut:
        return cls(ok=check.ok, model=check.model, latency_ms=check.latency_ms, detail=check.detail)


class BudgetOut(BaseModel):
    month: str
    org_tokens: int
    org_limit: int | None
    user_tokens: int
    user_limit: int | None


class AssistantStatusOut(BaseModel):
    features: FeatureToggles
    """Whether each feature works right now (configured, on, and within the master switch)."""
    can_use: bool
    """Whether you hold ``assistant:use``."""
    provider: str | None
    data_notice: str | None
    budget: BudgetOut
    requests_per_minute: int

    @classmethod
    def of(cls, status: Status) -> AssistantStatusOut:
        return cls(
            features=FeatureToggles(**dict(status.features)),
            can_use=status.can_use,
            provider=status.provider,
            data_notice=status.data_notice,
            budget=BudgetOut(
                month=status.month,
                org_tokens=status.org_tokens,
                org_limit=status.org_limit,
                user_tokens=status.user_tokens,
                user_limit=status.user_limit,
            ),
            requests_per_minute=status.requests_per_minute,
        )


class ExplanationIn(BaseModel):
    kind: str = Field(description=f"One of: {', '.join(sorted(EXPLAINERS.kinds))}")
    subject: dict[str, str | int] = Field(default_factory=dict[str, str | int])
    material: Any = Field(None, description="What the page shows that isn't stored yet (a draft, a preview)")
    regenerate: bool = Field(default=False, description="Write a new one instead of reusing the last")


class AcceptedOut(BaseModel):
    message_id: str
    conversation_id: str | None
    reused: bool
    """An earlier explanation of the same thing was reused (no tokens spent)."""


class SourceOut(BaseModel):
    kind: str
    label: str
    path: str


class ToolCallOut(BaseModel):
    id: str
    name: str
    status: Literal["running", "done", "denied", "not_found", "error"]
    duration_ms: int | None
    detail: str | None


class AttachmentOut(BaseModel):
    id: str
    name: str
    media_type: str
    size: int


class MessageOut(BaseModel):
    id: str
    conversation_id: str | None
    role: Literal["user", "assistant"]
    feature: FeatureName
    kind: str
    content: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    tool_calls: list[ToolCallOut]
    sources: list[SourceOut]
    model: str | None
    input_tokens: int
    output_tokens: int
    error: str | None
    created_at: datetime
    completed_at: datetime | None
    attachments: list[AttachmentOut]
    generated: bool
    """True for every assistant message: the text was written by a model."""

    @classmethod
    def of(cls, message: Message) -> MessageOut:
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            feature=message.feature,
            kind=message.kind,
            content=message.content,
            status=message.status,
            tool_calls=[
                ToolCallOut(id=c.id, name=c.name, status=c.status, duration_ms=c.duration_ms, detail=c.detail)
                for c in message.tool_calls
            ],
            sources=[SourceOut(kind=s.kind, label=s.label, path=s.path) for s in message.sources],
            model=message.model,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            error=message.error,
            created_at=message.created_at,
            completed_at=message.completed_at,
            attachments=[
                AttachmentOut(id=a.id, name=a.name, media_type=a.media_type, size=a.size) for a in message.attachments
            ],
            generated=message.role == "assistant",
        )


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, conversation: Conversation) -> ConversationOut:
        return cls(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


class ThreadOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]
