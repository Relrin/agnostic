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
    # Where run media (artefacts included) is stored, one folder per runtime id; served by AgentOS's media route.
    media_dir: str = "var/media"
    # Per-session working folders of the agents that write files (the report writer's workspace).
    workspace_dir: str = "var/workspaces"
    # Coding agents (Pi, OpenCode) in a sandbox per session; registered when their sandbox provider is available.
    coding_enabled: bool = True
    # Where sandboxes reach this runtime; unset: host.docker.internal on this runtime's port (Docker Desktop).
    coding_callback_url: str | None = None
    coding_sandbox: str = "docker"
    coding_image: str = "agnostic-coding:0.1.0"
    # E2B template built from runtime/sandbox/coding/Dockerfile, when coding_sandbox is "e2b".
    coding_template: str | None = None
    coding_network: str = "isolated"
    # The model the sample coding agents think with: "mock" (offline), or "<provider>:<model id>" such as
    # "ollama:qwen3:8b", "openai:gpt-5.2" or "anthropic:claude-sonnet-4-6" (keys from the provider's usual env var).
    coding_model: str = "mock"
    # Average pause between the words the mock model streams, in milliseconds. 0 (the default) streams a reply at
    # once; a few dozen make it arrive in uneven bursts like a provider's stream, to try how chat renders it.
    mock_stream_delay_ms: int = 0

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
    def coding_callback(self) -> str:
        return self.coding_callback_url or f"http://host.docker.internal:{self.port}"

    @property
    def jwt_enabled(self) -> bool:
        """AgentOS verifies JWTs (``authorization=True``) only when a verification key is configured."""
        return bool(os.environ.get("JWT_VERIFICATION_KEY") or os.environ.get("JWT_JWKS_FILE"))


@lru_cache
def get_settings() -> RuntimeSettings:
    return RuntimeSettings()
