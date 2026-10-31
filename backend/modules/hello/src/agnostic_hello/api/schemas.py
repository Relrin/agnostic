"""Request and response bodies of ``/api/v1/hello``."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from agnostic_hello.domain.greeting import GREETING_ID_PREFIX, MAX_MESSAGE_LENGTH, Greeting, GreetingStatus
from agnostic_kernel.ids import id_pattern


class GreetingCreate(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH, examples=["Hi from the control plane"])


class GreetingOut(BaseModel):
    id: str = Field(pattern=id_pattern(GREETING_ID_PREFIX), examples=["hel_01JBQ3Z7Y4W5V6X7Y8Z9A0B1C2"])
    message: str
    status: GreetingStatus
    reply: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, greeting: Greeting) -> GreetingOut:
        return cls(
            id=greeting.id,
            message=greeting.message,
            status=greeting.status,
            reply=greeting.reply,
            created_at=greeting.created_at,
            updated_at=greeting.updated_at,
        )
