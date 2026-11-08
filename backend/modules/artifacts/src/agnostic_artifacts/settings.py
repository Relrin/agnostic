"""``AGNOSTIC_ARTIFACTS__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class ArtifactsSettings(BaseSettings):
    model_config = module_settings_config("artifacts")

    max_content_mb: int = Field(default=50, ge=1, le=1024)
    """Largest artefact the control plane serves for viewing, download or a share link."""
    max_share_days: int = Field(default=30, ge=1, le=365)
    """Longest a share link may last."""
    public_links: bool = False
    """Allow "anyone with the link" shares. Off: share links need a signed-in member of the organization."""
