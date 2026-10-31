"""Greeting aggregate. Pure Python: no I/O, no framework imports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

GREETING_ID_PREFIX = "hel"
MAX_MESSAGE_LENGTH = 280


class GreetingStatus(StrEnum):
    PENDING = "pending"
    REPLIED = "replied"


class InvalidGreetingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Greeting:
    id: str
    message: str
    status: GreetingStatus
    reply: str | None
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def validate_message(message: str) -> str:
        cleaned = " ".join(message.split())
        if not cleaned:
            raise InvalidGreetingError("A greeting needs some text.")
        if len(cleaned) > MAX_MESSAGE_LENGTH:
            raise InvalidGreetingError(f"Keep greetings under {MAX_MESSAGE_LENGTH} characters.")
        return cleaned

    def with_reply(self, reply: str, at: datetime) -> Greeting:
        return replace(self, reply=reply, status=GreetingStatus.REPLIED, updated_at=at)


def compose_reply(message: str, prefix: str) -> str:
    """The deterministic reply the background job writes back."""
    return f"{prefix}! You said: “{message}” ({len(message.split())} words)."
