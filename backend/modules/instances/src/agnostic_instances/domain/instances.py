"""AgentOS instances, their trust keys, diagnostics and capabilities. No I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

INSTANCE_ID_PREFIX = "ins"
MIN_AGNO_VERSION = (3, 1)
SYSTEM_SUBJECT = "agnostic-system"
"""JWT ``sub`` for the control plane's own calls (probes, tests). AgentOS reserves ``sa:``/``__scheduler__``."""
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class EnvTag(StrEnum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class AuthMode(StrEnum):
    NONE = "none"
    SECURITY_KEY = "security_key"
    JWT = "jwt"
    UNKNOWN = "unknown"


class InstanceStatus(StrEnum):
    PENDING = "pending"
    """Created, never passed "Test connection"."""
    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    DISABLED = "disabled"


class SubClaimMode(StrEnum):
    USER_ID = "user_id"
    EMAIL = "email"


class NetworkMode(StrEnum):
    GATEWAY = "gateway"
    """Browsers reach the runtime only through the control plane's gateway (the default)."""
    DIRECT = "direct"
    """Browsers fetch a short-lived token from the control plane and call the runtime themselves."""


class KeyStatus(StrEnum):
    ACTIVE = "active"
    NEXT = "next"
    RETIRED = "retired"


class InstanceRuleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Instance:
    id: str
    slug: str
    display_name: str
    env_tag: EnvTag
    endpoint_url: str
    os_id: str | None
    agno_version: str | None
    os_version: str | None
    auth_mode: AuthMode
    user_isolation: bool | None
    status: InstanceStatus
    last_seen_at: datetime | None
    latency_ms: int | None
    sub_claim_mode: SubClaimMode
    tls_verify: bool
    ca_bundle_pem: str | None
    has_security_key: bool
    previous_agno_version: str | None
    version_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
    elevation_enabled: bool = True
    """Delegated elevation: typed control-plane actions may act as Instance admin for one request."""
    client_cert_pem: str | None = None
    """Certificate chain the control plane presents to the runtime (mutual TLS)."""
    client_key_sealed: str | None = None
    """The client certificate's private key, sealed; opened only when a connection is set up."""
    network_mode: NetworkMode = NetworkMode.GATEWAY
    browser_url: str | None = None
    """Where browsers reach the runtime in direct mode, when that differs from ``endpoint_url`` (which may be a
    cluster-internal address)."""

    @property
    def has_client_certificate(self) -> bool:
        return self.client_cert_pem is not None and self.client_key_sealed is not None

    @property
    def public_url(self) -> str:
        """The runtime's URL as browsers see it (direct mode)."""
        return self.browser_url or self.endpoint_url


def check_direct_mode(instance: Instance, *, allow_http: bool) -> None:
    """Direct mode sends people's tokens from browsers to the runtime: only over https outside development."""
    if (
        instance.network_mode is NetworkMode.DIRECT
        and not allow_http
        and not instance.public_url.startswith("https://")
    ):
        raise InstanceRuleError("Direct mode needs the runtime's browser URL to use https.")


@dataclass(frozen=True, slots=True)
class JwtKey:
    instance_id: str
    kid: str
    alg: str
    public_pem: str
    status: KeyStatus
    created_at: datetime
    activated_at: datetime | None


@dataclass(frozen=True, slots=True)
class Discovery:
    """What ``GET /info`` says about a runtime."""

    os_id: str
    name: str | None
    agno_version: str
    os_version: str | None
    auth_mode: AuthMode
    user_isolation: bool | None
    agent_count: int
    team_count: int
    workflow_count: int
    mcp_enabled: bool


type StepStatus = Literal["ok", "failed", "warning", "skipped"]


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    label: str
    status: StepStatus
    detail: str = ""
    hint: str | None = None


@dataclass(slots=True)
class Diagnosis:
    steps: list[Step] = field(default_factory=list[Step])

    def add(self, step: Step) -> Step:
        self.steps.append(step)
        return step

    @property
    def ok(self) -> bool:
        return all(step.status in {"ok", "warning", "skipped"} for step in self.steps)


type CapabilityStatus = Literal["available", "disabled", "unsupported", "unknown"]


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    status: CapabilityStatus
    detail: str = ""


CAPABILITIES: dict[str, str] = {
    "jwt_rbac": "Per-user permissions (JWT authorization enforced)",
    "user_isolation": "Each person sees only their own sessions and memories",
    "components": "Studio editing (needs a sync database)",
    "registry": "Registry of tools, models and databases",
    "tracing": "Traces",
    "scheduler": "Scheduled runs",
    "approvals": "Approvals (human in the loop)",
    "durable_queue": "Durable run queue",
    "service_accounts": "Native service accounts",
    "authz_store": "AgentOS authorization store and decision log",
    "filesystem": "Agent file systems",
    "memory": "Memory",
    "knowledge": "Knowledge",
    "learnings": "Learnings",
    "evals": "Evaluations",
    "metrics": "Metrics",
    "mcp": "MCP server",
    "bridge": "agnostic-bridge companion",
}


def parse_version(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    numbers = re.findall(r"\d+", value.split("+", 1)[0])
    return tuple(int(number) for number in numbers[:3])


def version_supported(agno_version: str) -> bool:
    return parse_version(agno_version)[:2] >= MIN_AGNO_VERSION


def minor(value: str | None) -> tuple[int, ...]:
    return parse_version(value)[:2]


def clean_endpoint(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    parts = urlsplit(cleaned)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise InstanceRuleError("The endpoint must be an http:// or https:// URL, e.g. https://agentos.internal:7777.")
    if parts.query or parts.fragment:
        raise InstanceRuleError("The endpoint can't have a query string or fragment.")
    return cleaned


def check_slug(slug: str) -> str:
    cleaned = slug.strip().lower()
    if not _SLUG.fullmatch(cleaned):
        raise InstanceRuleError("Use 2–63 lowercase letters, digits and dashes for the slug, e.g. prod-agentos.")
    if cleaned.startswith(("ins-", "ins_")):
        raise InstanceRuleError("Slugs can't start with ins_ (reserved for ids).")
    return cleaned


def slug_from(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:63]
    return slug if len(slug) >= 2 else f"agentos-{slug or 'os'}"  # noqa: PLR2004


def check_auth_mode(env: EnvTag, auth_mode: AuthMode) -> str | None:
    """A warning for risky combinations, or ``None``."""
    if auth_mode is AuthMode.NONE and env is not EnvTag.DEVELOPMENT:
        return "This AgentOS has no authentication. Only development instances may run without it."
    if auth_mode is AuthMode.SECURITY_KEY:
        return "Security-key instances have no per-user permissions; only Instance admins can use them."
    return None


def config_snippet(*, os_id: str, issuer: str, public_pem: str, user_isolation: bool) -> tuple[str, str]:
    """``(environment, python)`` snippets for the AgentOS app."""
    env = "JWT_VERIFICATION_KEY=" + '"' + public_pem.strip().replace("\n", "\\n") + '"'
    python = (
        "from agno.os import AgentOS\n"
        "from agno.os.authz import Authorization\n\n"
        "agent_os = AgentOS(\n"
        "    ...,\n"
        "    authorization=Authorization(\n"
        "        verify_audience=True,\n"
        f'        audience="{os_id}",\n'
        f'        issuer="{issuer}",\n'
        "    ),\n"
        f"    user_isolation={user_isolation},\n"
        ")\n"
        "# JWT_VERIFICATION_KEY (environment) holds the public key above.\n"
    )
    return env, python
