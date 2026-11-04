"""What the assistant needs from storage, from the agent framework and from the event bus."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from agnostic_assistant.domain.model import (
    Attachment,
    Conversation,
    Message,
    Role,
    SourceRef,
    Status,
    ToolCallRecord,
)
from agnostic_assistant.domain.settings import AiSettings, Feature


@dataclass(frozen=True, slots=True)
class NewMessage:
    conversation_id: str | None
    user_id: str
    instance_id: str
    role: Role
    feature: Feature
    kind: str
    subject: Mapping[str, Any]
    content: str
    status: Status
    subject_key: str | None = None
    attachments: Sequence[Attachment] = ()


@dataclass(frozen=True, slots=True)
class Outcome:
    status: Status
    content: str
    tool_calls: Sequence[ToolCallRecord]
    sources: Sequence[SourceRef]
    model: str | None
    input_tokens: int
    output_tokens: int
    error: str | None = None


class AssistantStore(Protocol):
    async def settings(self) -> AiSettings: ...
    async def api_key(self) -> str | None: ...
    async def save_settings(
        self, settings: AiSettings, *, api_key: str | None, key_changed: bool, by: str
    ) -> AiSettings:
        """Optimistic: raises ``VersionConflictError`` when ``settings.version`` is no longer current."""
        ...

    async def conversation(self, conversation_id: str) -> Conversation | None: ...
    async def conversations(self, user_id: str, instance_id: str, limit: int) -> list[Conversation]: ...
    async def create_conversation(self, user_id: str, instance_id: str, title: str) -> Conversation: ...
    async def touch_conversation(self, conversation_id: str) -> None: ...
    async def delete_conversation(self, conversation_id: str) -> None: ...
    async def messages(self, conversation_id: str) -> list[Message]: ...
    async def message(self, message_id: str, *, attachments: bool = False) -> Message | None: ...
    async def add_message(self, message: NewMessage) -> Message: ...
    async def start(self, message_id: str, model: str) -> bool:
        """Queued → running; ``False`` when another worker already took it or it was cancelled."""
        ...

    async def finish(self, message_id: str, outcome: Outcome) -> None: ...
    async def cancel(self, message_id: str) -> bool:
        """Queued → cancelled at once; a running answer is cancelled by its worker."""
        ...

    async def reusable(self, user_id: str, instance_id: str, kind: str, subject_key: str) -> Message | None:
        """The newest completed explanation of the same subject for this person."""
        ...

    async def add_usage(
        self, month: str, user_id: str, feature: Feature, input_tokens: int, output_tokens: int
    ) -> None: ...
    async def spent(self, month: str, user_id: str) -> tuple[int, int]:
        """Tokens used this month: ``(org, user)``."""
        ...

    async def prune(self, before: datetime) -> int: ...
    async def fail_stale(self, before: datetime, reason: str) -> int: ...
    async def commit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Connection:
    """Where the model is: everything except the model string."""

    endpoint: str | None
    api_key: str | None
    api_version: str | None
    temperature: float


@dataclass(frozen=True, slots=True)
class BoundTool:
    """A module's tool, ready to run as the asking person on the instance being asked about."""

    name: str
    description: str
    parameters: Mapping[str, Any]
    """JSON schema of the arguments."""
    run: Callable[[Mapping[str, Any]], Awaitable[str]]
    """Returns the quoted result the model reads; never raises."""


@dataclass(frozen=True, slots=True)
class Turn:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class EngineRequest:
    model: str
    connection: Connection
    instructions: str
    question: str
    history: Sequence[Turn] = ()
    images: Sequence[Attachment] = ()
    tools: Sequence[BoundTool] = ()
    max_tool_calls: int = 12


@dataclass(frozen=True, slots=True)
class ToolStarted:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class ToolFinished:
    id: str
    name: str
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class ContentDelta:
    text: str


@dataclass(frozen=True, slots=True)
class Finished:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class Failed:
    reason: str


type EngineEvent = ToolStarted | ToolFinished | ContentDelta | Finished | Failed


class AnswerEngine(Protocol):
    def run(self, request: EngineRequest) -> AsyncIterator[EngineEvent]:
        """Streams one answer; ends with ``Finished`` or ``Failed`` (provider errors become ``Failed``)."""
        ...

    async def check(self, model: str, connection: Connection) -> str:
        """One tiny completion; returns the reply, raises ``EngineError`` with a sentence on failure."""
        ...


class EngineError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RelayedEvent:
    id: str
    type: str
    data: Mapping[str, Any] = field(default_factory=dict[str, Any])


class Relay(Protocol):
    """Answer events from the worker to every tab following the answer, with replay for reconnects."""

    async def publish(self, message_id: str, event_type: str, data: Mapping[str, Any]) -> None: ...
    def follow(self, message_id: str, after_id: str | None, wait: float) -> AsyncIterator[RelayedEvent | None]:
        """Missed events first, then live ones; yields ``None`` every ``wait`` seconds without news."""
        ...

    async def request_cancel(self, message_id: str) -> None: ...
    async def cancel_requested(self, message_id: str) -> bool: ...
