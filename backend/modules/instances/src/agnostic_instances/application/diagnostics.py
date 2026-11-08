"""Step-by-step connection diagnostics and capability probes.

Each step says exactly what failed and what to do about it: DNS, TCP/TLS, "is this AgentOS?", version, then the
trust setup (key mismatch, audience mismatch, scopes not enforced).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from agnostic_agentos_client import AgentOSError, InstanceUnreachableError
from agnostic_instances.application.ports import RuntimeClient, Target
from agnostic_instances.application.tokens import TokenService
from agnostic_instances.domain.instances import (
    SYSTEM_SUBJECT,
    AuthMode,
    Capability,
    CapabilityStatus,
    Diagnosis,
    Discovery,
    EnvTag,
    Instance,
    Step,
    check_auth_mode,
    version_supported,
)
from agnostic_kernel.crypto import SecretBox

ADMIN_SCOPE = "agent_os:admin"


def _transport_step(exc: InstanceUnreachableError, endpoint: str) -> Step:
    text = str(exc)
    lowered = text.lower()
    if "certificate" in lowered or "ssl" in lowered or "tls" in lowered:
        return Step(
            "tls",
            "TLS",
            "failed",
            f"The TLS handshake with {endpoint} failed: {text}",
            "Add the runtime's CA certificate to the instance (CA bundle), or fix the certificate.",
        )
    if "timeout" in lowered or "timed out" in lowered:
        return Step(
            "connect",
            "Connect",
            "failed",
            f"{endpoint} didn't answer in time.",
            "Check firewalls between the control plane and the runtime, and that the AgentOS is running.",
        )
    return Step(
        "connect",
        "Connect",
        "failed",
        f"Nothing answered at {endpoint}: {text}",
        "Check the port, and that the AgentOS listens on an address the control plane can reach.",
    )


async def diagnose_reachability(client: RuntimeClient, target: Target, diagnosis: Diagnosis) -> Discovery | None:
    parts = urlsplit(target.endpoint_url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = await client.resolve(host, port)
    except OSError as exc:
        diagnosis.add(
            Step(
                "dns",
                "DNS",
                "failed",
                f"Can't resolve {host}: {exc}",
                "Check the hostname. It must resolve from the control plane's network, not just your laptop.",
            )
        )
        return None
    diagnosis.add(Step("dns", "DNS", "ok", f"{host} → {', '.join(addresses[:3])}"))

    try:
        latency = await client.health(target)
    except InstanceUnreachableError as exc:
        diagnosis.add(_transport_step(exc, target.endpoint_url))
        return None
    except AgentOSError as exc:
        diagnosis.add(
            Step(
                "connect",
                "Connect",
                "failed",
                f"GET /health answered HTTP {exc.status}.",
                "Is this the AgentOS base URL? AgentOS routes sit at the root (no /api prefix).",
            )
        )
        return None
    diagnosis.add(Step("connect", "Connect", "ok", f"/health answered in {latency:.0f} ms"))

    try:
        discovery = await client.info(target)
    except AgentOSError as exc:
        diagnosis.add(
            Step(
                "info",
                "AgentOS",
                "failed",
                f"GET /info didn't return AgentOS metadata ({exc}).",
                "Point the endpoint at an Agno AgentOS (agno 3.1 or later).",
            )
        )
        return None
    if not version_supported(discovery.agno_version):
        diagnosis.add(
            Step(
                "version",
                "Version",
                "failed",
                f"agno {discovery.agno_version} is too old.",
                "Upgrade the runtime to agno 3.1 or later.",
            )
        )
        return discovery
    label = discovery.name or discovery.os_id
    diagnosis.add(
        Step(
            "info",
            "AgentOS",
            "ok",
            f"{label} · agno {discovery.agno_version} · auth {discovery.auth_mode.value}"
            + (" · user isolation" if discovery.user_isolation else ""),
        )
    )
    return discovery


class RuntimeAuth:
    """Credentials for the control plane's own calls to a runtime (tests, probes, snapshots)."""

    def __init__(self, tokens: TokenService, box: SecretBox) -> None:
        self._tokens = tokens
        self._box = box

    async def headers(
        self, instance: Instance, scopes: tuple[str, ...] = (ADMIN_SCOPE,), sealed_key: str | None = None
    ) -> dict[str, str]:
        if instance.auth_mode is AuthMode.SECURITY_KEY:
            if sealed_key is None:
                return {}
            return {"Authorization": f"Bearer {self._box.open(sealed_key).decode()}"}
        if instance.auth_mode is AuthMode.NONE:
            return {}
        minted = await self._tokens.mint(instance, subject=SYSTEM_SUBJECT, scopes=scopes, name="Agnostic", via="system")
        return {"Authorization": f"Bearer {minted.token}"}


async def diagnose_trust(  # noqa: C901, PLR0911
    client: RuntimeClient, instance: Instance, auth: RuntimeAuth, sealed_key: str | None, diagnosis: Diagnosis
) -> bool | None:
    """Check that the runtime trusts our credentials. Returns whether per-user scopes are enforced."""
    target = Target.of(instance)
    warning = check_auth_mode(instance.env_tag, instance.auth_mode)
    if instance.auth_mode is AuthMode.NONE:
        status = "warning" if instance.env_tag is EnvTag.DEVELOPMENT else "failed"
        diagnosis.add(
            Step(
                "auth",
                "Authentication",
                status,
                warning or "No authentication.",
                "Enable JWT authorization: authorization=Authorization(...) and JWT_VERIFICATION_KEY.",
            )
        )
        return False
    if instance.auth_mode is AuthMode.SECURITY_KEY:
        if sealed_key is None:
            diagnosis.add(
                Step(
                    "auth",
                    "Security key",
                    "failed",
                    "This AgentOS uses OS_SECURITY_KEY and no key is stored for it.",
                    "Add the security key in Settings › Connection, or switch the runtime to JWT authorization.",
                )
            )
            return False
        status_code, _ = await client.probe(target, "/config", await auth.headers(instance, sealed_key=sealed_key))
        if status_code == 200:  # noqa: PLR2004
            diagnosis.add(Step("auth", "Security key", "warning", warning or "", None))
            return False
        diagnosis.add(
            Step(
                "auth",
                "Security key",
                "failed",
                f"AgentOS rejected the stored security key (HTTP {status_code}).",
                "Update the key in Settings › Connection.",
            )
        )
        return False

    headers = await auth.headers(instance, ("config:read",))
    status_code, body = await client.probe(target, "/config", headers)
    lowered = body.lower()
    if status_code == 401:  # noqa: PLR2004
        if "audience" in lowered or '"aud"' in lowered:
            diagnosis.add(
                Step(
                    "auth",
                    "Token",
                    "failed",
                    "AgentOS rejected the token's audience.",
                    f'Set audience="{instance.os_id}" in Authorization(...) — the audience is the AgentOS id.',
                )
            )
        elif "issuer" in lowered:
            diagnosis.add(
                Step(
                    "auth",
                    "Token",
                    "failed",
                    "AgentOS rejected the token's issuer.",
                    "Use the issuer shown in the snippet, or remove issuer= from Authorization(...).",
                )
            )
        else:
            diagnosis.add(
                Step(
                    "auth",
                    "Token",
                    "failed",
                    "AgentOS rejected the token (401): the public key isn't configured or doesn't match.",
                    "Paste the public key into JWT_VERIFICATION_KEY on the runtime and restart it.",
                )
            )
        return None
    if status_code == 403:  # noqa: PLR2004
        diagnosis.add(
            Step(
                "auth",
                "Token",
                "failed",
                "AgentOS accepted the token but refused config:read.",
                "Check custom scope_mappings on the runtime; GET /config must require config:read.",
            )
        )
        return None
    if status_code != 200:  # noqa: PLR2004
        diagnosis.add(Step("auth", "Token", "failed", f"GET /config answered HTTP {status_code}: {body[:200]}"))
        return None
    diagnosis.add(Step("auth", "Token", "ok", "AgentOS accepted a config:read token signed by this control plane."))

    scopeless = await auth.headers(instance, ())
    status_code, _ = await client.probe(target, "/config", scopeless)
    if status_code == 403:  # noqa: PLR2004
        diagnosis.add(Step("rbac", "Permissions", "ok", "Per-user scopes are enforced."))
        return True
    diagnosis.add(
        Step(
            "rbac",
            "Permissions",
            "warning",
            "A token without scopes could read /config: scopes aren't enforced on this runtime.",
            "Pass authorization=Authorization(...) (or authorization=True) to AgentOS to enforce scopes.",
        )
    )
    return False


_PROBES: Mapping[str, tuple[str, Mapping[str, str | int] | None]] = {
    "components": ("/components", {"limit": 1}),
    "registry": ("/registry", {"limit": 1}),
    "scheduler": ("/schedules", {"limit": 1}),
    "approvals": ("/approvals/count", None),
    "durable_queue": ("/queue/stats", None),
    "service_accounts": ("/service-accounts", {"limit": 1}),
    "authz_store": ("/authz/scopes", None),
    "tracing": ("/traces", {"limit": 1}),
    "bridge": ("/agnostic/v1/capabilities", None),
    "artifacts": ("/agnostic/v1/artifacts/recent", {"sessions": 1, "limit": 1}),
}
_CONFIG_SECTIONS = {
    "memory": "memory",
    "knowledge": "knowledge",
    "learnings": "learning",
    "evals": "evals",
    "metrics": "metrics",
    "filesystem": "filesystem",
}


def _status(code: int) -> CapabilityStatus:
    if 200 <= code < 300:  # noqa: PLR2004
        return "available"
    if code == 503:  # noqa: PLR2004
        return "disabled"
    if code in {404, 405}:
        return "unsupported"
    return "unknown"


async def probe_capabilities(
    client: RuntimeClient,
    instance: Instance,
    headers: Mapping[str, str],
    config: Mapping[str, Any] | None,
    jwt_rbac: bool | None,
) -> list[Capability]:
    target = Target.of(instance)

    async def one(name: str, path: str, params: Mapping[str, str | int] | None) -> Capability:
        try:
            code, body = await client.probe(target, path, headers, params)
        except AgentOSError as exc:
            return Capability(name, "unknown", str(exc))
        status = _status(code)
        if name == "durable_queue" and status == "unknown" and code == 403:  # noqa: PLR2004
            return Capability(name, "unknown", "Needs an admin token to check.")
        return Capability(name, status, body[:200] if status == "disabled" else "")

    results = list(await asyncio.gather(*(one(name, *probe) for name, probe in _PROBES.items())))
    sections = config or {}
    for name, section in _CONFIG_SECTIONS.items():
        present = bool(sections.get(section))
        results.append(Capability(name, "available" if present else "disabled"))
    if not sections.get("traces"):
        results = [
            Capability("tracing", "disabled", "tracing=False") if item.name == "tracing" else item for item in results
        ]
    results.append(Capability("jwt_rbac", "available" if jwt_rbac else ("unknown" if jwt_rbac is None else "disabled")))
    results.append(Capability("user_isolation", "available" if instance.user_isolation else "disabled"))
    return sorted(results, key=lambda item: item.name)
