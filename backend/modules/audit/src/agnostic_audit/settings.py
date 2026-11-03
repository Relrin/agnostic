"""``AGNOSTIC_AUDIT__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class AuditSettings(BaseSettings):
    model_config = module_settings_config("audit")

    retention_days: int = Field(default=400, ge=1)
    """Hot retention until someone saves the audit policy (which then decides): events older than this are dropped
    (whole monthly partitions on PostgreSQL), after being archived when the archive is on."""
    maintenance_cron: str = "17 3 * * *"
    deliver_cron: str = "* * * * *"
    """Periodic SIEM delivery (on top of the delivery queued shortly after events are written)."""
    deliver_on_record: bool = True
    """Queue a delivery a few seconds after events are written, for near-live streaming."""
    settle_seconds: float = Field(default=5.0, ge=0)
    """Events younger than this wait for the next delivery, so late-committing transactions aren't skipped."""
    delivery_batch: int = Field(default=500, ge=1, le=5000)
    export_sync_limit: int = Field(default=10_000, ge=1)
    """Above this many events, exports run as a background job."""
