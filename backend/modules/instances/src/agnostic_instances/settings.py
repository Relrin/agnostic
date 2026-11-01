"""``AGNOSTIC_INSTANCES__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class InstancesSettings(BaseSettings):
    model_config = module_settings_config("instances")

    issuer: str | None = None
    """``iss`` of minted JWTs. Defaults to the public URL of the control plane."""
    token_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    health_cron: str = "* * * * *"
    snapshot_cron: str = "*/5 * * * *"
