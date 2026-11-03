"""``AGNOSTIC_SERVICE_ACCOUNTS__*`` settings."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings

from agnostic_kernel.settings import module_settings_config


class ServiceAccountsSettings(BaseSettings):
    model_config = module_settings_config("service_accounts")

    token_pepper: SecretStr | None = None
    """Mixed into gateway token hashes. Unset: derived from the installation's master key (stable without config).
    Changing it invalidates every gateway token."""
    poll_cron: str = "*/5 * * * *"
    """When native tokens' last use is read from each instance and expired accounts are swept; empty turns it off."""
    last_used_write_seconds: float = 60.0
    """A gateway token's ``last_used_at`` is written at most this often."""
