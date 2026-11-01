"""``AGNOSTIC_APPROVALS__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class ApprovalsSettings(BaseSettings):
    model_config = module_settings_config("approvals")

    poll_seconds: float = Field(default=15.0, ge=0)
    """How often one replica asks each instance for its pending count (``approvals.count`` events); 0 turns it off."""
    continue_retry_delays: list[float] = Field(default_factory=lambda: [0.5, 1.0, 2.0])
    """Backoff between continue attempts while AgentOS answers 409 (a durable ticket still owns the run)."""
