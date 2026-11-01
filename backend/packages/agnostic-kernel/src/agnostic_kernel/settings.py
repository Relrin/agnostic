"""Control-plane settings.

Every external dependency is an *endpoint* the operator configures: the database, the cache and the
OTLP collector each get a URL plus TLS options. Settings come from, in priority order: init kwargs, environment
variables (``AGNOSTIC_`` prefix, ``__`` as the nesting delimiter), a ``.env`` file, and an optional TOML file
named by ``AGNOSTIC_CONFIG_FILE``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal, override
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

ENV_PREFIX = "AGNOSTIC_"
CONFIG_FILE_ENV = "AGNOSTIC_CONFIG_FILE"

type SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
type DatabaseBackend = Literal["postgresql", "sqlite"]
type JobMode = Literal["worker", "embedded"]
type CacheBackend = Literal["redis", "memory"]


def _split_csv(value: object) -> object:
    """Accept ``a,b,c`` from the environment as well as real lists."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class TlsOptions(BaseModel):
    """TLS material for an endpoint. Paths are read when the connection is created."""

    ca_file: Path | None = None
    cert_file: Path | None = None
    key_file: Path | None = None


class DatabaseSettings(BaseModel):
    """Database endpoint.

    PostgreSQL 17/18 (with ``citext`` and ``pg_trgm``) is the production backend. SQLite (``sqlite:///agnostic.db``)
    is supported for local development, evaluation and fast tests; TLS and pool options don't apply to it.
    """

    url: SecretStr = SecretStr("postgresql://agnostic:agnostic@localhost:5432/agnostic")
    sslmode: SslMode = "prefer"
    tls: TlsOptions = TlsOptions()
    pool_size: int = Field(default=10, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    connect_timeout: float = Field(default=5.0, gt=0)
    echo: bool = False

    @field_validator("url")
    @classmethod
    def _known_backend(cls, value: SecretStr) -> SecretStr:
        _ = backend_of(value.get_secret_value())
        return value

    @property
    def backend(self) -> DatabaseBackend:
        return backend_of(self.url.get_secret_value())


def backend_of(url: str) -> DatabaseBackend:
    """Database backend named by a URL scheme (driver suffixes such as ``+asyncpg`` are ignored)."""
    scheme = url.partition(":")[0].partition("+")[0].lower()
    if scheme in {"postgresql", "postgres"}:
        return "postgresql"
    if scheme == "sqlite":
        return "sqlite"
    msg = f"unsupported database URL scheme {scheme!r}; use postgresql:// or sqlite://"
    raise ValueError(msg)


class RedisSettings(BaseModel):
    """Redis endpoint (Redis 7.4+/8, or the compatible Valkey 8+ / DragonflyDB 1.x)."""

    url: SecretStr = SecretStr("redis://localhost:6379/0")
    sentinels: Annotated[list[str], NoDecode] = []
    sentinel_master: str | None = None
    tls: TlsOptions = TlsOptions()
    socket_timeout: float = Field(default=5.0, gt=0)

    _split_sentinels = field_validator("sentinels", mode="before")(_split_csv)


class OtelSettings(BaseModel):
    """OpenTelemetry export. Tracing is off unless an OTLP/HTTP endpoint is set."""

    endpoint: str | None = None
    headers: dict[str, SecretStr] = {}
    service_name: str = "agnostic"
    tls: TlsOptions = TlsOptions()


class LogSettings(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "console"] = "json"


class HttpSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: Annotated[list[str], NoDecode] = []
    public_url: str | None = None
    """The URL people open in their browser (behind the reverse proxy). Used for links in emails, SSO redirect
    URIs and the JWT issuer. Defaults to ``http://{host}:{port}``."""
    secure_cookies: bool | None = None
    """Mark session cookies ``Secure``. Defaults to on unless ``public_url`` is plain ``http://``."""

    _split_origins = field_validator("cors_origins", mode="before")(_split_csv)


class ModulesSettings(BaseModel):
    """``AGNOSTIC_MODULES__DISABLED=assistant,sources`` turns modules off for minimal installs."""

    disabled: Annotated[list[str], NoDecode] = []

    _split_disabled = field_validator("disabled", mode="before")(_split_csv)


class JobsSettings(BaseModel):
    """Background jobs.

    ``mode="worker"`` runs jobs in separate ``agnostic worker`` processes; ``"embedded"`` runs them inside the API
    process. ``"auto"`` picks ``worker`` on PostgreSQL and ``embedded`` on SQLite, where jobs live in an in-memory
    queue (Procrastinate needs PostgreSQL for durable jobs) and are lost when the process stops.
    """

    mode: Literal["auto", "worker", "embedded"] = "auto"
    concurrency: int = Field(default=10, ge=1)
    queues: Annotated[list[str], NoDecode] = []
    """Queues the worker listens to; empty means all queues."""

    _split_queues = field_validator("queues", mode="before")(_split_csv)


class CacheSettings(BaseModel):
    """Where ephemeral state (sessions, caches, rate limits) lives.

    ``"auto"`` picks Redis on PostgreSQL and an in-process store on SQLite, mirroring :class:`JobsSettings`. The
    in-process store is for single-process development and evaluation only: it is lost on restart and not shared
    between replicas.
    """

    mode: Literal["auto", "redis", "memory"] = "auto"


class SecretsSettings(BaseModel):
    """Key-encryption key for secrets at rest (envelope encryption, AES-256-GCM).

    ``master_key`` (or the file it is read from) holds 32 random bytes, base64-encoded:
    ``python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"``. Outside production a fixed
    development key is used when neither is set, with a warning.
    """

    master_key: SecretStr | None = None
    master_key_file: Path | None = None


class SmtpSettings(BaseModel):
    """Outgoing email (invitations, password resets). Without a URL, emails are written to the log instead.

    ``smtp://user:pass@host:587`` uses STARTTLS when the server offers it; ``smtps://host:465`` is implicit TLS.
    """

    url: SecretStr | None = None
    sender: str = "Agnostic <agnostic@localhost>"
    tls: TlsOptions = TlsOptions()
    timeout: float = Field(default=10.0, gt=0)


class Settings(BaseSettings):
    """Root settings object; module settings live in their own ``AGNOSTIC_<MODULE>__*`` namespaces."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "production"
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    otel: OtelSettings = OtelSettings()
    log: LogSettings = LogSettings()
    http: HttpSettings = HttpSettings()
    modules: ModulesSettings = ModulesSettings()
    jobs: JobsSettings = JobsSettings()
    cache: CacheSettings = CacheSettings()
    secrets: SecretsSettings = SecretsSettings()
    smtp: SmtpSettings = SmtpSettings()

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, dotenv_settings]
        config_file = os.environ.get(CONFIG_FILE_ENV)
        if config_file:
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=Path(config_file)))
        sources.append(file_secret_settings)
        return tuple(sources)

    def job_mode(self) -> JobMode:
        if self.jobs.mode != "auto":
            return self.jobs.mode
        return "embedded" if self.database.backend == "sqlite" else "worker"

    def cache_backend(self) -> CacheBackend:
        if self.cache.mode != "auto":
            return self.cache.mode
        return "memory" if self.database.backend == "sqlite" else "redis"

    def public_url(self) -> str:
        """Base URL of the web app as browsers see it, without a trailing slash."""
        return (self.http.public_url or f"http://{self.http.host}:{self.http.port}").rstrip("/")

    def secure_cookies(self) -> bool:
        if self.http.secure_cookies is not None:
            return self.http.secure_cookies
        return not self.public_url().startswith("http://")

    def redacted(self) -> dict[str, Any]:
        """Effective configuration with secrets removed, for ``agnostic config check``."""
        data = self.model_dump(mode="json")
        data["database"]["url"] = redact_url(self.database.url.get_secret_value())
        data["redis"]["url"] = redact_url(self.redis.url.get_secret_value())
        if self.smtp.url is not None:
            data["smtp"]["url"] = redact_url(self.smtp.url.get_secret_value())
        return data


def module_settings_config(module_name: str) -> SettingsConfigDict:
    """Settings config for a module's own ``BaseSettings`` subclass (``AGNOSTIC_<MODULE>__*``)."""
    return SettingsConfigDict(
        env_prefix=f"{ENV_PREFIX}{module_name.upper()}__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def redact_url(url: str) -> str:
    """Replace the password in a URL with ``***``; leave everything else intact."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    user = parts.username or ""
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{user}:***@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
