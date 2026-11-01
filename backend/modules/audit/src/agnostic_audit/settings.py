"""``AGNOSTIC_AUDIT__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class AuditSettings(BaseSettings):
    model_config = module_settings_config("audit")

    retention_days: int = Field(default=400, ge=1)
    """Events older than this are dropped (whole monthly partitions on PostgreSQL)."""
    maintenance_cron: str = "17 3 * * *"
