"""``AGNOSTIC_NOTIFICATIONS__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class NotificationsSettings(BaseSettings):
    model_config = module_settings_config("notifications")

    heartbeat_seconds: float = Field(default=15.0, gt=0)
    max_stream_seconds: float = Field(default=1800.0, gt=0)
    """Streams end after this long; browsers reconnect with Last-Event-ID (spreads load across replicas)."""
    slack_api_base: str = "https://slack.com/api"
    """Slack Web API base URL (a channel can override it, e.g. to point at the development Slack mock)."""
    http_timeout_seconds: float = Field(default=10.0, gt=0)
    """Timeout of one Slack or webhook request."""
    delivery_retries: int = Field(default=4, ge=0, le=20)
    """Retries of a failed email, Slack or webhook delivery before it is marked failed."""
