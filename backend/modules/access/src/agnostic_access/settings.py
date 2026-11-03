"""``AGNOSTIC_ACCESS__*`` settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class AccessSettings(BaseSettings):
    model_config = module_settings_config("access")

    expiry_cron: str = "*/5 * * * *"
    """When expired bindings (temporary access, invitations with an end date) are removed; empty turns it off."""
