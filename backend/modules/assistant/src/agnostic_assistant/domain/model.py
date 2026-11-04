"""Conversations, answers and what an answer was built from."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from agnostic_assistant.domain.settings import Feature

type Role = Literal["user", "assistant"]
type Status = Literal["queued", "running", "completed", "failed", "cancelled"]
type ToolStatus = Literal["running", "done", "denied", "not_found", "error"]

SETTLED: frozenset[Status] = frozenset({"completed", "failed", "cancelled"})
TITLE_LENGTH = 80


@dataclass(frozen=True, slots=True)
class SourceRef:
    """An in-app page an answer used: ``("trace", "Trace daily-brief · 8f3a01c2", "/i/prod/traces/8f3a…")``."""

    kind: str
    label: str
    path: str


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    id: str
    name: str
    status: ToolStatus
    duration_ms: int | None = None
    detail: str | None = None
    """Why it didn't return data (a missing scope, a missing trace)."""


@dataclass(frozen=True, slots=True)
class Attachment:
    id: str
    name: str
    media_type: str
    size: int
    text: str | None
    """Extracted text of text-like files; images carry ``data`` instead."""
    data: bytes | None = None

    @property
    def is_image(self) -> bool:
        return self.media_type.startswith("image/")


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    user_id: str
    instance_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str | None
    """``None`` for one-off explanations next to a page's deterministic text."""
    user_id: str
    instance_id: str
    role: Role
    feature: Feature
    kind: str
    """``ask`` for questions; an explanation kind (``trace.diagnosis``) otherwise."""
    subject: Mapping[str, Any]
    content: str
    status: Status
    created_at: datetime
    tool_calls: Sequence[ToolCallRecord] = ()
    sources: Sequence[SourceRef] = ()
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    completed_at: datetime | None = None
    attachments: Sequence[Attachment] = field(default_factory=tuple[Attachment, ...])

    @property
    def settled(self) -> bool:
        return self.status in SETTLED


def title_of(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_LENGTH else f"{text[: TITLE_LENGTH - 1]}…"


def merge_sources(sources: Sequence[SourceRef]) -> list[SourceRef]:
    """In first-use order, each page once."""
    seen: set[str] = set()
    merged: list[SourceRef] = []
    for source in sources:
        if source.path not in seen:
            seen.add(source.path)
            merged.append(source)
    return merged
