"""``AGNOSTIC_EVALS__*`` settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class EvalsSettings(BaseSettings):
    model_config = module_settings_config("evals")

    concurrency: int = Field(default=4, ge=1, le=32)
    """Eval runs in flight per batch; batches on one instance run one after another."""
