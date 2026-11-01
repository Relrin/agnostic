"""``AGNOSTIC_SEARCH__*`` settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class SearchSettings(BaseSettings):
    model_config = module_settings_config("search")

    reindex_cron: str | None = "*/5 * * * *"
    """Rebuild the palette index from every module's documents; empty turns the schedule off."""
