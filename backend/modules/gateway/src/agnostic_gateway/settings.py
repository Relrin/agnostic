"""``AGNOSTIC_GATEWAY__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class GatewaySettings(BaseSettings):
    model_config = module_settings_config("gateway")

    read_sample_rate: float = Field(default=0.05, ge=0, le=1)
    """Share of allowed reads written to the audit log (writes and denials are always written)."""
    rate_read_per_minute: int = Field(default=1200, ge=0)
    rate_write_per_minute: int = Field(default=240, ge=0)
    rate_run_per_minute: int = Field(default=120, ge=0)
    """Per person and instance; 0 turns a bucket off."""
    max_body_mb: int = Field(default=100, ge=1)
    max_upload_mb: int = Field(default=1024, ge=1)
    """Limit for file uploads (knowledge content); they stream through without being buffered."""
    heartbeat_seconds: float = Field(default=15.0, gt=0)
    upstream_read_timeout: float = Field(default=600.0, gt=0)
    circuit_failures: int = Field(default=5, ge=1)
    circuit_cooldown_seconds: float = Field(default=30.0, gt=0)
    ingest_cron: str = "* * * * *"
    """How often AgentOS authorization trails (decisions and role changes) are copied into the audit log."""
