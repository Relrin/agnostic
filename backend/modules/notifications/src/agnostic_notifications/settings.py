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
