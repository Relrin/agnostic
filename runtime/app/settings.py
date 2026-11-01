"""Runtime settings, read from the environment (``RUNTIME_*`` plus agno's own ``JWT_VERIFICATION_KEY``)."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# The runtime that plays "production" in the dev stack (`just runtimes`). It isolates per-user data by default.
PROD_RUNTIME_ID = "dev-prod"


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUNTIME_", env_file=".env", extra="ignore")

    id: str = PROD_RUNTIME_ID
    name: str = PROD_RUNTIME_ID
    description: str = "Agnostic reference AgentOS (prototype sample domain)"
    host: str = "127.0.0.1"
    port: int = 7777
    database_url: str = "postgresql+psycopg://agnostic:agnostic@localhost:5432/agentos_prod"
    redis_url: str | None = "redis://localhost:6379/1"
    internal_service_token: str = "dev-internal-service-token"
    # Unset: on for the prod runtime (dev-prod), off for the others.
    user_isolation: bool | None = None
    # When set, tokens must carry this `iss` (the control plane's public URL, AGNOSTIC_HTTP__PUBLIC_URL).
    jwt_issuer: str | None = None
    max_concurrency: int = 4

    @property
    def user_isolation_enabled(self) -> bool:
        if self.user_isolation is not None:
            return self.user_isolation
        return self.id == PROD_RUNTIME_ID

    @property
    def jwt_enabled(self) -> bool:
        """AgentOS verifies JWTs (``authorization=True``) only when a verification key is configured."""
        return bool(os.environ.get("JWT_VERIFICATION_KEY") or os.environ.get("JWT_JWKS_FILE"))


@lru_cache
def get_settings() -> RuntimeSettings:
    return RuntimeSettings()
