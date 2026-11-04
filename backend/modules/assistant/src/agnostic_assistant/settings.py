"""``AGNOSTIC_ASSISTANT__*`` settings: operator limits. The model, the budget and redaction are org settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class AssistantSettings(BaseSettings):
    model_config = module_settings_config("assistant")

    answer_timeout_seconds: float = Field(default=120.0, gt=0, le=1800)
    """An answer still being written after this long is stopped and marked failed."""
    tool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    """Tool calls per answer; the model has to answer with what it found once it runs out."""
    max_tool_result_chars: int = Field(default=12_000, ge=1_000, le=200_000)
    """A tool result longer than this is cut before the model reads it."""
    history_messages: int = Field(default=10, ge=0, le=50)
    """Earlier messages of a conversation sent along with a follow-up question."""
    max_attachments: int = Field(default=4, ge=0, le=20)
    max_attachment_bytes: int = Field(default=2_000_000, ge=1_000, le=20_000_000)
    max_attachment_chars: int = Field(default=20_000, ge=1_000, le=200_000)
    """Text kept from each text attachment (logs keep their end, where errors usually are)."""
    max_question_chars: int = Field(default=4_000, ge=100, le=50_000)
    prune_cron: str = "23 4 * * *"
    """When conversations past the org's retention are deleted; empty turns it off."""
