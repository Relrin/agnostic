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
    max_span_stat_traces: int = Field(default=100, ge=10, le=1000)
    """Newest traces whose spans are read for "Slowest span types"."""
    span_stats_ttl_seconds: float = Field(default=900, ge=0)
    """How long span statistics are reused."""
    max_session_pages: int = Field(default=20, ge=1, le=200)
    """Pages of 100 sessions read for per-component usage on the Metrics page (beyond that: approximate)."""
    comparison_cache_days: int = Field(default=7, ge=0, le=90)
    """Trace comparisons are recomputed after this many days."""
