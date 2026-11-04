"""Request and response bodies of ``/api/v1/instances``. Secrets (security keys, private keys) never appear."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agnostic_instances.application.use_cases import (
    ConfigView,
    HealthView,
    KeysView,
    ProbeResult,
    TestReport,
    TokenCheck,
)
from agnostic_instances.domain.instances import CAPABILITIES, Capability, Diagnosis, Discovery, Instance, JwtKey

type EnvTagName = Literal["production", "staging", "development"]


class InstanceOut(BaseModel):
    id: str
    slug: str
    display_name: str
    env_tag: EnvTagName
    endpoint_url: str
    os_id: str | None
    agno_version: str | None
    os_version: str | None
    auth_mode: Literal["none", "security_key", "jwt", "unknown"]
    user_isolation: bool | None
    status: Literal["pending", "connected", "unreachable", "disabled"]
    last_seen_at: datetime | None
    latency_ms: int | None
    sub_claim_mode: Literal["user_id", "email"]
    tls_verify: bool
    elevation_enabled: bool = Field(
        description="Typed actions (inline approval decisions) may act as Instance admin for one audited request"
    )
    has_ca_bundle: bool
    has_security_key: bool
    has_client_certificate: bool = Field(description="A client certificate is presented to the runtime (mutual TLS)")
    network_mode: Literal["gateway", "direct"] = Field(
        description="gateway: browsers go through the control plane; direct: browsers call the runtime with a token"
    )
    browser_url: str = Field(description="Where browsers reach the runtime in direct mode")
    version_drift: str | None = Field(description='e.g. "agno 3.1.12 → 3.2.0", when the minor version changed')
    created_at: datetime
    updated_at: datetime
    version: int

    @classmethod
    def from_domain(cls, instance: Instance) -> InstanceOut:
        drift = (
            f"agno {instance.previous_agno_version} → {instance.agno_version}"
            if instance.previous_agno_version and instance.previous_agno_version != instance.agno_version
            else None
        )
        return cls(
            id=instance.id,
            slug=instance.slug,
            display_name=instance.display_name,
            env_tag=instance.env_tag.value,
            endpoint_url=instance.endpoint_url,
            os_id=instance.os_id,
            agno_version=instance.agno_version,
            os_version=instance.os_version,
            auth_mode=instance.auth_mode.value,
            user_isolation=instance.user_isolation,
            status=instance.status.value,
            last_seen_at=instance.last_seen_at,
            latency_ms=instance.latency_ms,
            sub_claim_mode=instance.sub_claim_mode.value,
            tls_verify=instance.tls_verify,
            elevation_enabled=instance.elevation_enabled,
            has_ca_bundle=instance.ca_bundle_pem is not None,
            has_security_key=instance.has_security_key,
            has_client_certificate=instance.has_client_certificate,
            network_mode=instance.network_mode.value,
            browser_url=instance.public_url,
            version_drift=drift,
            created_at=instance.created_at,
            updated_at=instance.updated_at,
            version=instance.version,
        )


class StepOut(BaseModel):
    id: str
    label: str
    status: Literal["ok", "failed", "warning", "skipped"]
    detail: str
    hint: str | None


class DiscoveryOut(BaseModel):
    os_id: str
    name: str | None
    agno_version: str
    os_version: str | None
    auth_mode: Literal["none", "security_key", "jwt", "unknown"]
    user_isolation: bool | None
    agent_count: int
    team_count: int
    workflow_count: int
    mcp_enabled: bool

    @classmethod
    def from_domain(cls, discovery: Discovery) -> DiscoveryOut:
        return cls(
            os_id=discovery.os_id,
            name=discovery.name,
            agno_version=discovery.agno_version,
            os_version=discovery.os_version,
            auth_mode=discovery.auth_mode.value,
            user_isolation=discovery.user_isolation,
            agent_count=discovery.agent_count,
            team_count=discovery.team_count,
            workflow_count=discovery.workflow_count,
            mcp_enabled=discovery.mcp_enabled,
        )


def _steps(diagnosis: Diagnosis) -> list[StepOut]:
    return [
        StepOut(id=step.id, label=step.label, status=step.status, detail=step.detail, hint=step.hint)
        for step in diagnosis.steps
    ]


class ProbeIn(BaseModel):
    endpoint_url: str = Field(max_length=2048, examples=["http://127.0.0.1:7777"])
    tls_verify: bool = True
    ca_bundle_pem: str | None = Field(default=None, max_length=65536)
    client_cert_pem: str | None = Field(
        default=None, max_length=65536, description="Client certificate chain (PEM) for mutual TLS"
    )
    client_key_pem: str | None = Field(
        default=None, max_length=65536, description="Its private key (PEM, unencrypted); stored sealed, never returned"
    )


class ProbeOut(BaseModel):
    ok: bool
    steps: list[StepOut]
    discovery: DiscoveryOut | None

    @classmethod
    def from_result(cls, result: ProbeResult) -> ProbeOut:
        return cls(
            ok=result.diagnosis.ok and result.discovery is not None,
            steps=_steps(result.diagnosis),
            discovery=DiscoveryOut.from_domain(result.discovery) if result.discovery else None,
        )


class ConnectIn(ProbeIn):
    display_name: str | None = Field(default=None, max_length=120)
    slug: str | None = Field(default=None, max_length=63, examples=["prod-agentos"])
    env_tag: EnvTagName = "development"
    security_key: str | None = Field(default=None, max_length=4096, description="Only for OS_SECURITY_KEY runtimes")
    sub_claim_mode: Literal["user_id", "email"] = "user_id"


class ConnectedOut(BaseModel):
    instance: InstanceOut
    steps: list[StepOut]


class InstanceUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    slug: str | None = Field(default=None, max_length=63)
    env_tag: EnvTagName | None = None
    endpoint_url: str | None = Field(default=None, max_length=2048)
    sub_claim_mode: Literal["user_id", "email"] | None = None
    tls_verify: bool | None = None
    ca_bundle_pem: str | None = Field(default=None, max_length=65536, description="Empty string removes it")
    security_key: str | None = Field(default=None, max_length=4096, description="Empty string removes it")
    status: Literal["disabled", "enabled"] | None = None
    elevation_enabled: bool | None = None
    client_cert_pem: str | None = Field(
        default=None, max_length=65536, description="With client_key_pem; empty strings remove the client certificate"
    )
    client_key_pem: str | None = Field(default=None, max_length=65536, description="Write-only")
    network_mode: Literal["gateway", "direct"] | None = None
    browser_url: str | None = Field(
        default=None, max_length=2048, description="Direct mode: the runtime's URL for browsers; empty string resets it"
    )
    version: int | None = Field(default=None, description="Expected version (optimistic concurrency)")


class CapabilityOut(BaseModel):
    name: str
    label: str
    status: Literal["available", "disabled", "unsupported", "unknown"]
    detail: str

    @classmethod
    def from_domain(cls, capability: Capability) -> CapabilityOut:
        return cls(
            name=capability.name,
            label=CAPABILITIES.get(capability.name, capability.name),
            status=capability.status,
            detail=capability.detail,
        )


class TestReportOut(BaseModel):
    ok: bool
    instance: InstanceOut
    steps: list[StepOut]
    capabilities: list[CapabilityOut]

    @classmethod
    def from_report(cls, report: TestReport) -> TestReportOut:
        return cls(
            ok=report.diagnosis.ok,
            instance=InstanceOut.from_domain(report.instance),
            steps=_steps(report.diagnosis),
            capabilities=[CapabilityOut.from_domain(item) for item in report.capabilities],
        )


class KeyOut(BaseModel):
    kid: str
    alg: str
    status: Literal["active", "next", "retired"]
    public_pem: str
    created_at: datetime
    activated_at: datetime | None

    @classmethod
    def from_domain(cls, key: JwtKey) -> KeyOut:
        return cls(
            kid=key.kid,
            alg=key.alg,
            status=key.status.value,
            public_pem=key.public_pem,
            created_at=key.created_at,
            activated_at=key.activated_at,
        )


class KeysOut(BaseModel):
    keys: list[KeyOut]
    issuer: str
    audience: str
    env_snippet: str | None
    python_snippet: str | None
    jwks_path: str
    rotation_note: str

    @classmethod
    def from_view(cls, view: KeysView) -> KeysOut:
        staged = any(key.status.value == "next" for key in view.keys)
        note = (
            "A next key is staged. The runtime loads its keys only at startup: save the JWKS document (active and "
            "next key) as the file JWT_JWKS_FILE points to and restart the runtime. Then activate the next key here; "
            "activating first makes the runtime refuse every token."
            if staged
            else "Rotate in two steps: stage a next key, restart the runtime trusting both keys, then activate it."
        )
        return cls(
            keys=[KeyOut.from_domain(key) for key in view.keys],
            issuer=view.issuer,
            audience=view.instance.os_id or view.instance.id,
            env_snippet=view.env_snippet,
            python_snippet=view.python_snippet,
            jwks_path=view.jwks_path,
            rotation_note=note,
        )


class RotateIn(BaseModel):
    action: Literal["stage", "activate", "cancel"]


class VerifyTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=16384)


class TokenCheckOut(BaseModel):
    valid: bool
    kid: str | None
    key_status: str | None
    claims: dict[str, Any] | None
    error: str | None

    @classmethod
    def from_check(cls, check: TokenCheck) -> TokenCheckOut:
        return cls(
            valid=check.valid, kid=check.kid, key_status=check.key_status, claims=check.claims, error=check.error
        )


class HealthOut(BaseModel):
    instance_id: str
    status: Literal["pending", "connected", "unreachable", "disabled"]
    latency_ms: int | None
    last_seen_at: datetime | None
    agno_version: str | None
    version_drift: str | None
    capabilities: list[CapabilityOut]
    probed_at: datetime | None

    @classmethod
    def from_view(cls, view: HealthView) -> HealthOut:
        out = InstanceOut.from_domain(view.instance)
        return cls(
            instance_id=out.id,
            status=out.status,
            latency_ms=out.latency_ms,
            last_seen_at=out.last_seen_at,
            agno_version=out.agno_version,
            version_drift=out.version_drift,
            capabilities=[CapabilityOut.from_domain(item) for item in view.capabilities],
            probed_at=view.probed_at,
        )


class ConfigOut(BaseModel):
    """``GET /config`` of the runtime, as last fetched; sections are passed through as AgentOS returns them."""

    instance_id: str
    fetched_at: datetime | None
    os_id: str | None
    name: str | None
    description: str | None
    available_models: list[Any]
    databases: list[Any]
    os_database: Any
    interfaces: list[Any]
    agents: list[Any]
    teams: list[Any]
    workflows: list[Any]
    sections: dict[str, Any] = Field(description="traces, queue, memory, knowledge, learning, session, …")

    @classmethod
    def from_view(cls, view: ConfigView) -> ConfigOut:
        config = dict(view.config or {})
        listed = ("available_models", "databases", "interfaces", "agents", "teams", "workflows")
        scalars = ("os_id", "name", "description", "os_database")
        return cls(
            instance_id=view.instance.id,
            fetched_at=view.fetched_at,
            os_id=config.get("os_id"),
            name=config.get("name"),
            description=config.get("description"),
            available_models=list(config.get("available_models") or []),
            databases=list(config.get("databases") or []),
            os_database=config.get("os_database"),
            interfaces=list(config.get("interfaces") or []),
            agents=list(config.get("agents") or []),
            teams=list(config.get("teams") or []),
            workflows=list(config.get("workflows") or []),
            sections={key: value for key, value in config.items() if key not in listed and key not in scalars},
        )
