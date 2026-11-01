"""Use cases of the instances module: connect wizard, diagnostics, keys, health and snapshots."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, cast

from agnostic_agentos_client import AgentOSError
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.application.diagnostics import (
    RuntimeAuth,
    diagnose_reachability,
    diagnose_trust,
    probe_capabilities,
)
from agnostic_instances.application.ports import (
    InstanceRepository,
    KeyRepository,
    RuntimeClient,
    Signer,
    SnapshotRepository,
    Target,
)
from agnostic_instances.application.tokens import PrivateKeyCache
from agnostic_instances.domain.instances import (
    INSTANCE_ID_PREFIX,
    Capability,
    Diagnosis,
    Discovery,
    EnvTag,
    Instance,
    InstanceRuleError,
    InstanceStatus,
    JwtKey,
    KeyStatus,
    Step,
    SubClaimMode,
    check_slug,
    clean_endpoint,
    config_snippet,
    minor,
    slug_from,
)
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.crypto import SecretBox
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, bump_access_generation
from agnostic_kernel.errors import AppError, ConflictError, NotFoundError, ValidationFailedError
from agnostic_kernel.ids import new_id
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

READ = "os:read"
WRITE = "os:write"
DELETE = "os:delete"
ROTATE = "os:keys:rotate"


class DiscoveryFailedError(AppError):
    status = 422
    code = "discovery_failed"
    title = "The endpoint couldn't be reached as an AgentOS"


@dataclass(frozen=True, slots=True)
class InstanceContext:
    instances: InstanceRepository
    keys: KeyRepository
    snapshots: SnapshotRepository
    client: RuntimeClient
    signer: Signer
    box: SecretBox
    auth: RuntimeAuth
    cache: PrivateKeyCache
    authorizer: Authorizer
    audit: AuditLog
    store: EphemeralStore
    issuer: str


class _UseCase:
    def __init__(self, context: InstanceContext) -> None:
        self.c = context

    async def _instance(self, ref: str) -> Instance:
        instance = await self.c.instances.get(ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {ref!r}.")
        return instance

    async def _new_key(self, instance_id: str, status: KeyStatus) -> JwtKey:
        generated = self.c.signer.generate()
        now = utcnow()
        key = JwtKey(
            instance_id=instance_id,
            kid=generated.kid,
            alg=self.c.signer.alg,
            public_pem=generated.public_pem,
            status=status,
            created_at=now,
            activated_at=now if status is KeyStatus.ACTIVE else None,
        )
        await self.c.keys.add(key, self.c.box.seal(generated.private_pem.encode()))
        return key

    async def _audit(self, principal: Principal, action: str, instance: Instance, **fields: str) -> None:
        _ = await self.c.audit.record(
            AuditEntry(
                action=action,
                actor=actor_of(principal),
                resource_kind="instance",
                resource_id=instance.id,
                resource_display=instance.display_name,
                instance_id=instance.id,
                fields=fields,
            )
        )


@dataclass(frozen=True, slots=True)
class ProbeResult:
    diagnosis: Diagnosis
    discovery: Discovery | None


class ProbeEndpoint(_UseCase):
    """Wizard step 1: what is at this URL? Nothing is stored."""

    async def __call__(
        self, principal: Principal, endpoint_url: str, *, tls_verify: bool, ca_bundle_pem: str | None
    ) -> ProbeResult:
        _ = await self.c.authorizer.require(principal, WRITE)
        try:
            endpoint = clean_endpoint(endpoint_url)
        except InstanceRuleError as exc:
            raise ValidationFailedError(str(exc)) from exc
        diagnosis = Diagnosis()
        discovery = await diagnose_reachability(self.c.client, Target(endpoint, tls_verify, ca_bundle_pem), diagnosis)
        return ProbeResult(diagnosis, discovery)


@dataclass(frozen=True, slots=True)
class ConnectRequest:
    endpoint_url: str
    display_name: str | None
    slug: str | None
    env_tag: EnvTag
    tls_verify: bool = True
    ca_bundle_pem: str | None = None
    security_key: str | None = None
    sub_claim_mode: SubClaimMode = SubClaimMode.USER_ID


class ConnectInstance(_UseCase):
    """Wizard step 2: discover, register the instance and generate its key pair."""

    async def __call__(self, principal: Principal, request: ConnectRequest) -> tuple[Instance, Diagnosis]:
        _ = await self.c.authorizer.require(principal, WRITE)
        try:
            endpoint = clean_endpoint(request.endpoint_url)
        except InstanceRuleError as exc:
            raise ValidationFailedError(str(exc)) from exc
        diagnosis = Diagnosis()
        discovery = await diagnose_reachability(
            self.c.client, Target(endpoint, request.tls_verify, request.ca_bundle_pem), diagnosis
        )
        if discovery is None or not diagnosis.ok:
            raise DiscoveryFailedError(
                next((s.detail for s in diagnosis.steps if s.status == "failed"), "Discovery failed."),
                extra={"steps": [_step_dict(step) for step in diagnosis.steps]},
            )
        display_name = (request.display_name or discovery.name or discovery.os_id).strip()[:120]
        try:
            slug = check_slug(request.slug or slug_from(display_name))
        except InstanceRuleError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if await self.c.instances.get(slug) is not None:
            raise ConflictError(f"An instance called {slug} already exists.")
        for existing in await self.c.instances.list():
            if existing.os_id == discovery.os_id:
                raise ConflictError(f"{existing.display_name} already points at AgentOS {discovery.os_id}.")

        now = utcnow()
        instance = Instance(
            id=new_id(INSTANCE_ID_PREFIX),
            slug=slug,
            display_name=display_name,
            env_tag=request.env_tag,
            endpoint_url=endpoint,
            os_id=discovery.os_id,
            agno_version=discovery.agno_version,
            os_version=discovery.os_version,
            auth_mode=discovery.auth_mode,
            user_isolation=discovery.user_isolation,
            status=InstanceStatus.PENDING,
            last_seen_at=now,
            latency_ms=None,
            sub_claim_mode=request.sub_claim_mode,
            tls_verify=request.tls_verify,
            ca_bundle_pem=request.ca_bundle_pem,
            has_security_key=request.security_key is not None,
            previous_agno_version=None,
            version_changed_at=None,
            created_at=now,
            updated_at=now,
            version=1,
        )
        sealed = self.c.box.seal(request.security_key.encode()) if request.security_key else None
        await self.c.instances.add(instance, sealed)
        _ = await self._new_key(instance.id, KeyStatus.ACTIVE)
        await self.c.snapshots.save(instance.id, "info", _discovery_dict(discovery), now)
        await self._audit(principal, "instances.create", instance, endpoint=endpoint)
        await self.c.instances.commit()
        return instance, diagnosis


class Rediscover(_UseCase):
    async def __call__(self, principal: Principal, ref: str) -> tuple[Instance, Diagnosis]:
        _ = await self.c.authorizer.require(principal, WRITE)
        instance = await self._instance(ref)
        diagnosis = Diagnosis()
        discovery = await diagnose_reachability(self.c.client, Target.of(instance), diagnosis)
        if discovery is not None:
            instance = await self.apply_discovery(instance, discovery, diagnosis)
            await self.c.instances.commit()
        return instance, diagnosis

    async def apply_discovery(self, instance: Instance, discovery: Discovery, diagnosis: Diagnosis) -> Instance:
        now = utcnow()
        if instance.os_id and discovery.os_id != instance.os_id:
            diagnosis.add(
                _warning(
                    "identity",
                    "AgentOS id",
                    f"This endpoint now serves AgentOS {discovery.os_id}, not {instance.os_id}.",
                    "If the runtime was replaced on purpose, keep going: tokens now carry the new id.",
                )
            )
        drift = instance.agno_version is not None and minor(instance.agno_version) != minor(discovery.agno_version)
        updated = replace(
            instance,
            os_id=discovery.os_id,
            agno_version=discovery.agno_version,
            os_version=discovery.os_version,
            auth_mode=discovery.auth_mode,
            user_isolation=discovery.user_isolation,
            last_seen_at=now,
            previous_agno_version=instance.agno_version if drift else instance.previous_agno_version,
            version_changed_at=now if drift else instance.version_changed_at,
            updated_at=now,
        )
        await self.c.snapshots.save(instance.id, "info", _discovery_dict(discovery), now)
        return await self.c.instances.save(updated)


@dataclass(frozen=True, slots=True)
class TestReport:
    instance: Instance
    diagnosis: Diagnosis
    capabilities: list[Capability]


class TestConnection(Rediscover):
    """Wizard step 4 and Settings > Connection: every step from DNS to "scopes are enforced"."""

    async def __call__(self, principal: Principal, ref: str) -> TestReport:  # pyright: ignore[reportIncompatibleMethodOverride]
        _ = await self.c.authorizer.require(principal, WRITE)
        instance = await self._instance(ref)
        diagnosis = Diagnosis()
        discovery = await diagnose_reachability(self.c.client, Target.of(instance), diagnosis)
        capabilities: list[Capability] = []
        if discovery is not None and diagnosis.ok:
            instance = await self.apply_discovery(instance, discovery, diagnosis)
            sealed = await self.c.instances.security_key(instance.id)
            jwt_rbac = await diagnose_trust(self.c.client, instance, self.c.auth, sealed, diagnosis)
            if diagnosis.ok:
                capabilities = await refresh_snapshots(self.c, instance, sealed, jwt_rbac, discovery)
        status = (
            InstanceStatus.CONNECTED
            if diagnosis.ok
            else (InstanceStatus.UNREACHABLE if discovery is None else InstanceStatus.PENDING)
        )
        instance = await self.c.instances.save(replace(instance, status=status, updated_at=utcnow()))
        _ = await self.c.audit.record(
            AuditEntry(
                action="instances.test",
                actor=actor_of(principal),
                resource_kind="instance",
                resource_id=instance.id,
                resource_display=instance.display_name,
                instance_id=instance.id,
                decision="allowed" if diagnosis.ok else "denied",
                fields={"result": "passed" if diagnosis.ok else "failed"},
                diff={"steps": [_step_dict(step) for step in diagnosis.steps]},
            )
        )
        await self.c.instances.commit()
        return TestReport(instance, diagnosis, capabilities)


async def refresh_snapshots(
    c: InstanceContext,
    instance: Instance,
    sealed_key: str | None,
    jwt_rbac: bool | None,
    discovery: Discovery | None,
) -> list[Capability]:
    """Store ``/config`` and the capability matrix (the caller commits)."""
    now = utcnow()
    target = Target.of(instance)
    headers = await c.auth.headers(instance, sealed_key=sealed_key)
    config: Mapping[str, Any] | None = None
    try:
        raw = await c.client.get_json(target, "/config", headers)
        if isinstance(raw, dict):
            config = cast("dict[str, Any]", raw)
            await c.snapshots.save(instance.id, "config", config, now)
    except AgentOSError as exc:
        log.warning("instances.config_snapshot_failed", instance=instance.id, error=str(exc))
    if jwt_rbac is None:
        previous, _ = await c.snapshots.capabilities(instance.id)
        rbac = next((item for item in previous if item.name == "jwt_rbac"), None)
        jwt_rbac = None if rbac is None or rbac.status == "unknown" else rbac.status == "available"
    capabilities = await probe_capabilities(c.client, instance, headers, config, jwt_rbac)
    if discovery is not None:
        capabilities.append(Capability("mcp", "available" if discovery.mcp_enabled else "disabled"))
    await c.snapshots.save_capabilities(instance.id, capabilities, now)
    return sorted(capabilities, key=lambda item: item.name)


@dataclass(frozen=True, slots=True)
class InstanceChanges:
    display_name: str | None = None
    slug: str | None = None
    env_tag: EnvTag | None = None
    endpoint_url: str | None = None
    sub_claim_mode: SubClaimMode | None = None
    tls_verify: bool | None = None
    ca_bundle_pem: str | None = None
    security_key: str | None = None
    status: Literal["disabled", "enabled"] | None = None


class UpdateInstance(_UseCase):
    async def __call__(  # noqa: C901, PLR0912  (one branch per optional field)
        self, principal: Principal, ref: str, changes: InstanceChanges, expected_version: int | None
    ) -> Instance:
        _ = await self.c.authorizer.require(principal, WRITE)
        instance = await self._instance(ref)
        updated = instance
        try:
            if changes.display_name is not None:
                updated = replace(updated, display_name=changes.display_name.strip()[:120] or instance.display_name)
            if changes.slug is not None and changes.slug != instance.slug:
                slug = check_slug(changes.slug)
                if await self.c.instances.get(slug) is not None:
                    raise ConflictError(f"An instance called {slug} already exists.")
                updated = replace(updated, slug=slug)
            if changes.endpoint_url is not None:
                updated = replace(updated, endpoint_url=clean_endpoint(changes.endpoint_url))
        except InstanceRuleError as exc:
            raise ValidationFailedError(str(exc)) from exc
        if changes.env_tag is not None:
            updated = replace(updated, env_tag=changes.env_tag)
        if changes.sub_claim_mode is not None:
            updated = replace(updated, sub_claim_mode=changes.sub_claim_mode)
        if changes.tls_verify is not None:
            updated = replace(updated, tls_verify=changes.tls_verify)
        if changes.ca_bundle_pem is not None:
            updated = replace(updated, ca_bundle_pem=changes.ca_bundle_pem or None)
        if changes.status == "disabled":
            updated = replace(updated, status=InstanceStatus.DISABLED)
        elif changes.status == "enabled" and instance.status is InstanceStatus.DISABLED:
            updated = replace(updated, status=InstanceStatus.PENDING)
        if changes.security_key is not None:
            sealed = self.c.box.seal(changes.security_key.encode()) if changes.security_key else None
            await self.c.instances.set_security_key(instance.id, sealed)
            updated = replace(updated, has_security_key=sealed is not None)
        fields = ("display_name", "slug", "env_tag", "endpoint_url", "sub_claim_mode", "tls_verify", "status")
        diff = {
            name: {"before": str(getattr(instance, name)), "after": str(getattr(updated, name))}
            for name in fields
            if getattr(instance, name) != getattr(updated, name)
        }
        if changes.ca_bundle_pem is not None and instance.ca_bundle_pem != updated.ca_bundle_pem:
            diff["ca_bundle_pem"] = {"before": "…", "after": "…"}
        if changes.security_key is not None:
            diff["security_key"] = {"before": "***", "after": "***"}
        if not diff:
            return instance
        saved = await self.c.instances.save(replace(updated, updated_at=utcnow()), expected_version=expected_version)
        _ = await self.c.audit.record(
            AuditEntry(
                action="instances.update",
                actor=actor_of(principal),
                resource_kind="instance",
                resource_id=instance.id,
                resource_display=saved.display_name,
                instance_id=instance.id,
                fields={"keys": ", ".join(sorted(diff))},
                diff=diff,
            )
        )
        await self.c.instances.commit()
        await bump_access_generation(self.c.store)
        return saved


class DeleteInstance(_UseCase):
    async def __call__(self, principal: Principal, ref: str, confirm: str) -> None:
        _ = await self.c.authorizer.require(principal, DELETE)
        instance = await self._instance(ref)
        if confirm != instance.slug:
            raise ValidationFailedError(f"Type {instance.slug} to confirm.")
        await self._audit(principal, "instances.delete", instance, endpoint=instance.endpoint_url)
        await self.c.instances.delete(instance.id)
        await self.c.instances.commit()
        self.c.cache.forget(instance.id)
        await bump_access_generation(self.c.store)


class ListInstances(_UseCase):
    async def __call__(self, principal: Principal) -> list[Instance]:
        _ = await self.c.authorizer.require(principal, READ)
        return await self.c.instances.list()


class GetInstance(_UseCase):
    async def __call__(self, principal: Principal, ref: str) -> Instance:
        _ = await self.c.authorizer.require(principal, READ)
        return await self._instance(ref)


@dataclass(frozen=True, slots=True)
class KeysView:
    instance: Instance
    keys: list[JwtKey]
    issuer: str
    env_snippet: str | None
    python_snippet: str | None
    jwks_path: str


class GetKeys(_UseCase):
    async def __call__(self, principal: Principal, ref: str) -> KeysView:
        _ = await self.c.authorizer.require(principal, READ)
        return await self.view(await self._instance(ref))

    async def view(self, instance: Instance) -> KeysView:
        keys = await self.c.keys.list(instance.id, [KeyStatus.ACTIVE, KeyStatus.NEXT])
        active = next((key for key in keys if key.status is KeyStatus.ACTIVE), None)
        env, python = (
            config_snippet(
                os_id=instance.os_id or instance.id,
                issuer=self.c.issuer,
                public_pem=active.public_pem,
                user_isolation=bool(instance.user_isolation)
                if instance.user_isolation is not None
                else instance.env_tag is EnvTag.PRODUCTION,
            )
            if active
            else (None, None)
        )
        return KeysView(
            instance=instance,
            keys=keys,
            issuer=self.c.issuer,
            env_snippet=env,
            python_snippet=python,
            jwks_path=f"/.well-known/agnostic/instances/{instance.id}/jwks.json",
        )


class RotateKeys(GetKeys):
    """Two-step rotation: stage the next key (publish it in JWKS / add it to the runtime), then activate it."""

    async def __call__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, principal: Principal, ref: str, action: Literal["stage", "activate", "cancel"]
    ) -> KeysView:
        _ = await self.c.authorizer.require(principal, ROTATE)
        instance = await self._instance(ref)
        keys = await self.c.keys.list(instance.id, [KeyStatus.ACTIVE, KeyStatus.NEXT])
        active = [key for key in keys if key.status is KeyStatus.ACTIVE]
        staged = [key for key in keys if key.status is KeyStatus.NEXT]
        now = utcnow()
        if action == "stage":
            if staged:
                raise ConflictError("A next key is already staged. Activate or cancel it first.")
            key = await self._new_key(instance.id, KeyStatus.NEXT)
            detail = key.kid
        elif action == "activate":
            if not staged:
                raise ConflictError("Stage a next key before activating it.")
            for key in active:
                await self.c.keys.set_status(instance.id, key.kid, KeyStatus.RETIRED, now)
            await self.c.keys.set_status(instance.id, staged[0].kid, KeyStatus.ACTIVE, now)
            detail = staged[0].kid
        else:
            if not staged:
                raise ConflictError("There is no staged key to cancel.")
            await self.c.keys.set_status(instance.id, staged[0].kid, KeyStatus.RETIRED, now)
            detail = staged[0].kid
        await self._audit(principal, f"instances.keys.{action}", instance, kid=detail)
        await self.c.instances.commit()
        self.c.cache.forget(instance.id)
        await bump_access_generation(self.c.store)
        return await self.view(instance)


class Jwks(_UseCase):
    """Public: current and next keys, for the bridge's JWKS refresh (zero-downtime rotation)."""

    async def __call__(self, ref: str) -> dict[str, list[dict[str, str]]]:
        instance = await self._instance(ref)
        keys = await self.c.keys.list(instance.id, [KeyStatus.ACTIVE, KeyStatus.NEXT])
        return {"keys": [self.c.signer.jwk(key.public_pem, key.kid) for key in keys]}


@dataclass(frozen=True, slots=True)
class TokenCheck:
    valid: bool
    kid: str | None
    key_status: str | None
    claims: dict[str, Any] | None
    error: str | None


class VerifyToken(_UseCase):
    """Settings > Authorization: decode a pasted token against this instance's keys."""

    async def __call__(self, principal: Principal, ref: str, token: str) -> TokenCheck:
        _ = await self.c.authorizer.require(principal, READ)
        instance = await self._instance(ref)
        keys = await self.c.keys.list(instance.id)
        kid, claims, error = self.c.signer.verify(
            token, {key.kid: key.public_pem for key in keys}, instance.os_id or instance.id
        )
        status = next((key.status.value for key in keys if key.kid == kid), None)
        return TokenCheck(valid=error is None, kid=kid, key_status=status, claims=claims, error=error)


@dataclass(frozen=True, slots=True)
class HealthView:
    instance: Instance
    capabilities: list[Capability]
    probed_at: datetime | None


class GetHealth(_UseCase):
    async def __call__(self, principal: Principal, ref: str) -> HealthView:
        _ = await self.c.authorizer.require(principal, READ)
        instance = await self._instance(ref)
        capabilities, probed_at = await self.c.snapshots.capabilities(instance.id)
        return HealthView(instance, capabilities, probed_at)


@dataclass(frozen=True, slots=True)
class ConfigView:
    instance: Instance
    config: dict[str, Any] | None
    fetched_at: datetime | None


class GetConfig(_UseCase):
    """The latest ``/config`` snapshot (Settings pages). Needs ``config:read`` on the instance."""

    async def __call__(self, principal: Principal, ref: str, *, refresh: bool) -> ConfigView:
        instance = await self._instance(ref)
        _ = await self.c.authorizer.require(principal, "config:read", instance_id=instance.id)
        if refresh and instance.status is not InstanceStatus.DISABLED:
            sealed = await self.c.instances.security_key(instance.id)
            _ = await refresh_snapshots(self.c, instance, sealed, None, None)
            await self.c.instances.commit()
        latest = await self.c.snapshots.latest(instance.id, "config")
        if latest is None:
            return ConfigView(instance, None, None)
        payload, fetched_at = latest
        return ConfigView(instance, payload if isinstance(payload, dict) else None, fetched_at)  # pyright: ignore[reportUnknownArgumentType]


class CheckHealth(_UseCase):
    """Periodic job: ``/health`` + ``/info`` of every instance, latency, version drift."""

    async def __call__(self) -> dict[str, str]:
        results: dict[str, str] = {}
        instances = [i for i in await self.c.instances.list() if i.status is not InstanceStatus.DISABLED]
        outcomes = await asyncio.gather(*(self._one(instance) for instance in instances), return_exceptions=True)
        for instance, outcome in zip(instances, outcomes, strict=True):
            results[instance.slug] = outcome if isinstance(outcome, str) else f"error: {outcome}"
        await self.c.instances.commit()
        return results

    async def _one(self, instance: Instance) -> str:
        target = Target.of(instance)
        now = utcnow()
        try:
            latency = await self.c.client.health(target)
            discovery = await self.c.client.info(target)
        except AgentOSError as exc:
            await self.c.instances.record_health(
                instance.id, status=InstanceStatus.UNREACHABLE, latency_ms=None, seen_at=None
            )
            await self.c.store.set(f"health:{instance.id}", b"unreachable", ttl=120)
            return f"unreachable: {exc}"
        status = InstanceStatus.PENDING if instance.status is InstanceStatus.PENDING else InstanceStatus.CONNECTED
        await self.c.instances.record_health(instance.id, status=status, latency_ms=round(latency), seen_at=now)
        if (discovery.agno_version, discovery.os_id, discovery.auth_mode, discovery.user_isolation) != (
            instance.agno_version,
            instance.os_id,
            instance.auth_mode,
            instance.user_isolation,
        ):
            fresh = await self.c.instances.get(instance.id)
            if fresh is not None:
                _ = await Rediscover(self.c).apply_discovery(fresh, discovery, Diagnosis())
        await self.c.store.set(f"health:{instance.id}", f"ok:{round(latency)}".encode(), ttl=120)
        return f"ok {latency:.0f} ms"


class RefreshAllSnapshots(_UseCase):
    """Periodic job: ``/config`` and the capability matrix of every connected instance."""

    async def __call__(self) -> int:
        count = 0
        for instance in await self.c.instances.list():
            if instance.status is not InstanceStatus.CONNECTED:
                continue
            try:
                sealed = await self.c.instances.security_key(instance.id)
                _ = await refresh_snapshots(self.c, instance, sealed, None, None)
                count += 1
            except (AgentOSError, AppError) as exc:
                log.warning("instances.snapshot_failed", instance=instance.id, error=str(exc))
        await self.c.instances.commit()
        return count


def _warning(step_id: str, label: str, detail: str, hint: str) -> Step:
    return Step(step_id, label, "warning", detail, hint)


def _step_dict(step: Step) -> dict[str, Any]:
    return {"id": step.id, "label": step.label, "status": step.status, "detail": step.detail, "hint": step.hint}


def _discovery_dict(discovery: Discovery) -> dict[str, Any]:
    return {
        "os_id": discovery.os_id,
        "name": discovery.name,
        "agno_version": discovery.agno_version,
        "os_version": discovery.os_version,
        "auth_mode": discovery.auth_mode.value,
        "user_isolation": discovery.user_isolation,
        "agent_count": discovery.agent_count,
        "team_count": discovery.team_count,
        "workflow_count": discovery.workflow_count,
        "mcp_enabled": discovery.mcp_enabled,
    }
