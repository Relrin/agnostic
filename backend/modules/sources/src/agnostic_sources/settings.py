"""``AGNOSTIC_SOURCES__*`` settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class SourcesSettings(BaseSettings):
    model_config = module_settings_config("sources")

    git_binary: str = "git"
    """The git executable the worker runs (it needs git 2.36 or newer)."""
    mirrors_dir: Path = Path("var/sources/mirrors")
    """Where bare mirrors of source repositories live; give it its own volume."""
    mirror_quota_mb: int = Field(default=512, ge=1)
    total_quota_mb: int = Field(default=10_240, ge=1)
    git_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    fetch_timeout_seconds: float = Field(default=180.0, gt=0, le=3600)
    provider_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    max_changed_files: int = Field(default=500, ge=1)
    """A fetch bringing more changed mapped files than this reports them instead of reading them all."""
    max_file_bytes: int = Field(default=256_000, ge=1)
    allow_file_remotes: bool = False
    """Accept ``file://`` clone URLs (tests and air-gapped mirrors only)."""
    local_roots: list[Path] = Field(default_factory=list[Path])
    """Folders local sources may point into (only for development instances); empty turns local sources off."""
    watch_local: bool = True
    watch_debounce_ms: int = Field(default=800, ge=50)
    fetch_cron: str = "*/15 * * * *"
    """Periodic fetch for sources without a webhook; empty turns it off."""
    pull_request_cron: str = "*/5 * * * *"
    gc_cron: str = "41 3 * * *"
    webhook_base_url: str | None = None
    """Where git hosts reach Agnostic for webhooks, when that isn't ``AGNOSTIC_HTTP__PUBLIC_URL`` (a host in a
    container reaching the API on the host machine, a separate ingress for ``/hooks``)."""
    webhook_max_bytes: int = Field(default=5_000_000, ge=1024)
    delivery_retention_days: int = Field(default=30, ge=1)
    committer_name: str = "Agnostic Studio"
    committer_email: str = "studio@agnostic.invalid"
    github_api_url: str = "https://api.github.com"
    github_web_url: str = "https://github.com"
    github_app_slug: str | None = None
    """The GitHub App people install for read & write sources (``agnostic-northwind``)."""
