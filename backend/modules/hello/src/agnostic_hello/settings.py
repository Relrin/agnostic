"""``AGNOSTIC_HELLO__*`` settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class HelloSettings(BaseSettings):
    model_config = module_settings_config("hello")

    reply_prefix: str = "Hello"
    heartbeat_cron: str = "*/5 * * * *"
