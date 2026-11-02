"""``AGNOSTIC_CONTEXT__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class ContextSettings(BaseSettings):
    model_config = module_settings_config("context")

    duplicate_threshold: float = Field(default=0.35, gt=0, le=1)
    """Trigram similarity (0 to 1, as ``pg_trgm``) above which two memories of one user are likely duplicates."""
    max_duplicate_scan: int = Field(default=500, ge=10, le=5000)
    """Memories of one user compared for duplicates (newest first); beyond that the result says it is partial."""
    max_content_pages: int = Field(default=10, ge=1, le=100)
    """Pages of 100 knowledge content rows read to filter by status and type and to count failed and processing rows."""
    provenance_sessions: int = Field(default=10, ge=1, le=100)
    """Sessions of the memory's user and agent searched for the run a memory came from."""
    provenance_traces: int = Field(default=50, ge=1, le=500)
    """Newest traces of the agents holding a filesystem read when looking for file writes without agnostic-bridge."""
