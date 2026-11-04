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
    # Direct mode: the control plane's public origin(s), comma-separated, allowed to call this runtime from browsers.
    cors_origins: str = ""
    # Keep AgentOS's authorization decision log (the control plane ingests it; needed when browsers call directly).
    authz_audit: bool = False
    # Failures to reproduce on purpose, e.g. "web_search=timeout" (comma-separated tool=fault pairs). Development
    # only: it is how the dev stack gets a daily-brief run that fails the way production ones do.
    faults: str = ""

    def fault(self, tool: str) -> str | None:
        """The fault configured for ``tool`` ("timeout"), if any."""
        for item in self.faults.split(","):
            name, _, kind = item.strip().partition("=")
            if name == tool and kind:
                return kind
        return None

    @property
    def user_isolation_enabled(self) -> bool:
        if self.user_isolation is not None:
            return self.user_isolation
        return self.id == PROD_RUNTIME_ID

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def jwt_enabled(self) -> bool:
        """AgentOS verifies JWTs (``authorization=True``) only when a verification key is configured."""
        return bool(os.environ.get("JWT_VERIFICATION_KEY") or os.environ.get("JWT_JWKS_FILE"))


@lru_cache
def get_settings() -> RuntimeSettings:
    return RuntimeSettings()
