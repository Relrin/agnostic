"""Delegated elevation: one typed action, one audited request as Instance admin.

Under ``user_isolation`` AgentOS answers 404 when a non-admin resolves an approval or continues a run that belongs to
someone else. For an allow-listed set of typed control-plane actions (never the passthrough), the control plane checks
the person's permission itself, then sends exactly one request with a fresh 60-second ``agent_os:admin`` token whose
``sub`` is still that person. The token's ``jti`` is registered in the ephemeral store and consumed before the call,
so a token is never reused (retries mint a new one), and every use is audited as ``gateway.elevated``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
import orjson

from agnostic_access.facade import ADMIN_SCOPE
from agnostic_agentos_client import InstanceUnreachableError
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_gateway.application.ports import Upstream
from agnostic_gateway.application.proxy import (
    GatewayUnreachableError,
    InstanceAuthFailedError,
    InstanceDisabledError,
)
from agnostic_instances.facade import AuthMode, Instance, InstancesFacade, InstanceStatus, SubClaimMode
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.context import current_request_id
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, ForbiddenError, NotFoundError

ELEVATED_TTL = timedelta(seconds=60)
JTI_KEY = "elev:{jti}"


class ElevationDisabledError(ForbiddenError):
    code = "elevation_disabled"
    title = "Delegated elevation is turned off for this instance"


class ElevationFailedError(AppError):
    status = 502
    code = "elevation_failed"
    title = "The elevated request could not be sent"


@dataclass(frozen=True, slots=True)
class ElevatedResponse:
    status: int
    body: Any
    """Decoded JSON, the raw text when the body isn't JSON, or ``None`` when empty."""

    @property
    def ok(self) -> bool:
        return self.status < 400  # noqa: PLR2004


class Elevation:
    def __init__(
        self,
        instances: InstancesFacade,
        authorizer: Authorizer,
        audit: AuditLog,
        store: EphemeralStore,
        upstream: Upstream,
    ) -> None:
        self._instances = instances
        self._authorizer = authorizer
        self._audit = audit
        self._store = store
        self._upstream = upstream

    async def instance(self, ref: str) -> Instance:
        # Not the passthrough's 15 s instance cache: turning elevation off must apply to the very next decision.
        instance = await self._instances.get(ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {ref!r}.")
        if instance.status is InstanceStatus.DISABLED:
            raise InstanceDisabledError(f"{instance.display_name} is disabled. Enable it in Settings › Connection.")
        return instance

    async def send(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        *,
        justification: str,
        action_label: str,
        params: Mapping[str, str] | None = None,
        json: Any = None,  # noqa: ANN401
        form: Mapping[str, str] | None = None,
    ) -> ElevatedResponse:
        """Send one request as Instance admin on behalf of ``principal``, who must hold ``justification``.

        Statuses are returned as they are; only transport failures and a rejected token raise.
        """
        if not instance.elevation_enabled:
            raise ElevationDisabledError(
                f"Only Instance admins can {action_label} on {instance.display_name}: delegated elevation is turned "
                "off for this instance (Settings › Connection).",
                extra={"instance_id": instance.id},
            )
        _ = await self._authorizer.require(principal, justification, instance_id=instance.id)

        headers, jti = await self._credentials(principal, instance)
        headers["X-Request-Id"] = current_request_id() or ""
        content: bytes | None = None
        if json is not None:
            content = orjson.dumps(json)
            headers["Content-Type"] = "application/json"
        elif form is not None:
            content = _urlencode(form)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            response = await self._upstream.send(
                instance,
                method,
                path,
                params=list((params or {}).items()),
                headers=headers,
                body=_once(content) if content is not None else None,
            )
        except InstanceUnreachableError as exc:
            await self._record(principal, instance, method, path, justification, jti, 502)
            raise GatewayUnreachableError(f"{instance.display_name} didn't answer: {exc}") from exc
        try:
            raw = await response.aread()
        finally:
            await response.aclose()
        await self._record(principal, instance, method, path, justification, jti, response.status_code)
        if response.status_code == 401:  # noqa: PLR2004
            raise InstanceAuthFailedError(
                f"{instance.display_name} rejected the elevated token. Run Test connection in Settings › Connection.",
                extra={"instance_id": instance.id, "upstream_status": 401},
            )
        return ElevatedResponse(response.status_code, _decode(raw))

    async def _credentials(self, principal: Principal, instance: Instance) -> tuple[dict[str, str], str | None]:
        if instance.auth_mode is AuthMode.NONE:
            return {}, None
        if instance.auth_mode is AuthMode.SECURITY_KEY:
            key = await self._instances.security_key(instance)
            return ({"Authorization": f"Bearer {key}"} if key else {}), None
        subject = principal.email if instance.sub_claim_mode is SubClaimMode.EMAIL and principal.email else principal.id
        minted = await self._instances.mint(
            instance,
            subject=subject,
            scopes=[ADMIN_SCOPE],
            name=principal.display_name,
            via="elevated",
            ttl=ELEVATED_TTL,
        )
        key = JTI_KEY.format(jti=minted.jti)
        registered = await self._store.set_if_absent(key, b"issued", ttl=ELEVATED_TTL.total_seconds())
        # Single use: the marker is consumed right before the one request that carries the token.
        if not registered or await self._store.pop(key) is None:
            raise ElevationFailedError("The elevated token was already used; try again.")
        return {"Authorization": f"Bearer {minted.token}"}, minted.jti

    async def _record(
        self,
        principal: Principal,
        instance: Instance,
        method: str,
        path: str,
        justification: str,
        jti: str | None,
        status: int,
    ) -> None:
        _ = await self._audit.record_now(
            AuditEntry(
                action="gateway.elevated",
                actor=actor_of(principal),
                resource_kind="route",
                resource_id=f"{method} {path}",
                resource_display=f"{method} {path}",
                instance_id=instance.id,
                decision="allowed",
                scope_checked=justification,
                response_status=status,
                via="gateway",
                fields={
                    "route": f"{method} {path}",
                    "instance": instance.display_name,
                    "scope": justification,
                    "jti": jti or "",
                },
            )
        )


def _urlencode(form: Mapping[str, str]) -> bytes:
    return str(httpx.QueryParams(dict(form))).encode()


async def _once(content: bytes) -> AsyncIterator[bytes]:
    yield content


def _decode(raw: bytes) -> Any:  # noqa: ANN401
    if not raw:
        return None
    try:
        return orjson.loads(raw)
    except orjson.JSONDecodeError:
        return raw.decode(errors="replace")[:2000]
