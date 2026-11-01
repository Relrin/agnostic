"""``AGNOSTIC_OBSERVE__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class ObserveSettings(BaseSettings):
    model_config = module_settings_config("observe")

    max_trace_pages: int = Field(default=10, ge=1, le=100)
    """Pages of 100 traces scanned per overview (p95 latency and per-component counts come from this sample)."""
    warm_cron: str | None = "* * * * *"
    """Recompute the 7-day overview of every connected instance in the background; empty turns it off."""
