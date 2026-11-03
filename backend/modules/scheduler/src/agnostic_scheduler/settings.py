"""``AGNOSTIC_SCHEDULER__*`` settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class SchedulerSettings(BaseSettings):
    model_config = module_settings_config("scheduler")

    watch_cron: str = "* * * * *"
    """When the failure watcher looks for failed scheduled runs; empty turns it off."""
