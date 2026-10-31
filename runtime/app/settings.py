"""Runtime settings, read from the environment (``RUNTIME_*`` plus agno's own ``JWT_VERIFICATION_KEY``)."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUNTIME_", env_file=".env", extra="ignore")

    id: str = "dev-prod"
    name: str = "dev-prod"
    description: str = "Agnostic reference AgentOS (prototype sample domain)"
    host: str = "127.0.0.1"
    port: int = 7777
    database_url: str = "postgresql+psycopg://agnostic:agnostic@localhost:5432/agentos_prod"
    redis_url: str | None = "redis://localhost:6379/1"
    internal_service_token: str = "dev-internal-service-token"
    user_isolation: bool = True
    max_concurrency: int = 4

    @property
    def jwt_enabled(self) -> bool:
        """AgentOS verifies JWTs (``authorization=True``) only when a verification key is configured."""
        return bool(os.environ.get("JWT_VERIFICATION_KEY") or os.environ.get("JWT_JWKS_FILE"))


@lru_cache
def get_settings() -> RuntimeSettings:
    return RuntimeSettings()
