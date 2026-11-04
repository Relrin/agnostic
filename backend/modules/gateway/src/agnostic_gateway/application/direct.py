"""Direct mode: browsers call a runtime themselves with a short-lived token minted here.

The token carries the person's effective runtime scopes for that instance, exactly what the gateway would put in
its own token, so AgentOS enforces the same permissions. The gateway's extras (scope explanations, response
cache, delegated elevation, per-call audit) don't apply: auditing relies on ingesting AgentOS's authorization
decisions instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from agnostic_access.facade import AccessFacade, compress
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_gateway.domain.policies import MAX_TOKEN_SCOPE_BYTES
from agnostic_instances.facade import AuthMode, Instance, InstancesFacade, InstanceStatus, NetworkMode, SubClaimMode
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore, access_generation
from agnostic_kernel.errors import ConflictError, ForbiddenError, NotFoundError, RateLimitedError

DIRECT_VIA = "direct"
TOKENS_PER_MINUTE = 30
REFRESH_MARGIN = 30.0
"""Seconds before expiry a cached token is no longer handed out (the browser refreshes ahead of time too)."""


class DirectModeOffError(ConflictError):
    code = "direct_mode_off"
    title = "Direct mode is off for this instance"


@dataclass(frozen=True, slots=True)
class DirectToken:
    token: str
    expires_at: datetime
    base_url: str
    """Where the browser sends its calls (the runtime's browser URL)."""


def _check_eligible(principal: Principal, instance: Instance) -> None:
    if instance.network_mode is not NetworkMode.DIRECT:
        raise DirectModeOffError(f"{instance.display_name} is reached through the gateway; use /os/… instead.")
    if instance.status is InstanceStatus.DISABLED:
        raise ConflictError(f"{instance.display_name} is disabled.")
    if principal.kind != "user":
        raise ForbiddenError("Direct-mode tokens are for people in a browser; service accounts use their tokens.")
    if instance.auth_mode is not AuthMode.JWT:
        raise ConflictError(f"{instance.display_name} doesn't verify control-plane JWTs, so it can't run direct.")


class DirectTokens:
    def __init__(
        self, instances: InstancesFacade, access: AccessFacade, store: EphemeralStore, audit: AuditLog
    ) -> None:
        self._instances = instances
        self._access = access
        self._store = store
        self._audit = audit

    async def issue(self, principal: Principal, instance_ref: str) -> DirectToken:
        instance = await self._instances.get(instance_ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {instance_ref!r}.")
        _check_eligible(principal, instance)

        window = int(time.time() // 60)
        if await self._store.incr(f"rl:direct:{principal.id}:{instance.id}:{window}", ttl=70) > TOKENS_PER_MINUTE:
            raise RateLimitedError("Too many token requests. Slow down.", extra={"retry_after": 60})

        access = await self._access.access_for("user", principal.id, instance.id)
        scopes = compress(access.runtime_scopes())
        if not scopes:
            raise ForbiddenError(f"You have no access to {instance.display_name}.")
        if sum(len(scope) + 3 for scope in scopes) > MAX_TOKEN_SCOPE_BYTES:
            raise ConflictError("Your permissions don't fit in a browser token; ask for gateway mode on this instance.")
        subject = principal.email if instance.sub_claim_mode is SubClaimMode.EMAIL and principal.email else principal.id

        generation = await access_generation(self._store)
        key = f"jwt:direct:{generation}:{principal.id}:{instance.id}"
        cached = await self._store.get(key)
        if cached is not None:
            token, _, expires = cached.decode().partition(" ")
            return DirectToken(token, datetime.fromisoformat(expires), instance.public_url)

        minted = await self._instances.mint(
            instance, subject=subject, scopes=scopes, name=principal.display_name, via=DIRECT_VIA
        )
        ttl = (minted.expires_at - utcnow()).total_seconds() - REFRESH_MARGIN
        if ttl > 0:
            await self._store.set(key, f"{minted.token} {minted.expires_at.isoformat()}".encode(), ttl=ttl)
        _ = await self._audit.record_now(
            AuditEntry(
                action="gateway.direct_token",
                actor=actor_of(principal),
                resource_kind="instance",
                resource_id=instance.id,
                resource_display=instance.display_name,
                instance_id=instance.id,
                via=DIRECT_VIA,
                fields={"instance": instance.display_name, "expires_at": minted.expires_at.isoformat()},
            )
        )
        return DirectToken(minted.token, minted.expires_at, instance.public_url)
