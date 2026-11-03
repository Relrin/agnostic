"""``AGNOSTIC_DIRECTORY__*`` settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class DirectorySettings(BaseSettings):
    model_config = module_settings_config("directory")

    google_sync_cron: str = "*/15 * * * *"
    """When Google Workspace groups and users are pulled (only while the sync is turned on); empty turns it off."""
    reconcile_cron: str = "17 * * * *"
    """When group memberships are reconciled with deprovisioned accounts and mapping rules; empty turns it off."""
