"""``AGNOSTIC_STUDIO__*`` settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class StudioSettings(BaseSettings):
    model_config = module_settings_config("studio")

    source_isolation: Literal["process", "inline"] = "process"
    """Where code parsing, edits and CEL run: worker processes (each job with a timeout), or this process."""
    source_workers: int = Field(default=2, ge=1, le=16)
    source_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
