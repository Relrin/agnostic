"""The org's authentication policy, cached in the ephemeral store (every request that resolves a session reads it)."""

from __future__ import annotations

from datetime import datetime

import orjson

from agnostic_identity.application.ports import AuthPolicyRepository
from agnostic_identity.domain.policy import AuthPolicy, MfaPolicy
from agnostic_identity.domain.users import SessionPolicy
from agnostic_kernel.ephemeral import EphemeralStore

POLICY_CACHE_KEY = "identity:auth_policy"
POLICY_CACHE_SECONDS = 60


def _encode(policy: AuthPolicy) -> bytes:
    return orjson.dumps(
        {
            "enforce_sso": policy.enforce_sso,
            "break_glass_user_id": policy.break_glass_user_id,
            "session_idle_minutes": policy.session_idle_minutes,
            "session_absolute_hours": policy.session_absolute_hours,
            "mfa_policy": policy.mfa_policy.value,
            "updated_by": policy.updated_by,
            "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
        }
    )


def _decode(raw: bytes) -> AuthPolicy:
    data = orjson.loads(raw)
    return AuthPolicy(
        enforce_sso=bool(data["enforce_sso"]),
        break_glass_user_id=data["break_glass_user_id"],
        session_idle_minutes=data["session_idle_minutes"],
        session_absolute_hours=data["session_absolute_hours"],
        mfa_policy=MfaPolicy(data["mfa_policy"]),
        updated_by=data["updated_by"],
        updated_at=datetime.fromisoformat(data["updated_at"]) if data["updated_at"] else None,
    )


class AuthPolicies:
    def __init__(self, repository: AuthPolicyRepository, store: EphemeralStore, defaults: SessionPolicy) -> None:
        self._repository = repository
        self._store = store
        self._defaults = defaults
        self._current: AuthPolicy | None = None

    @property
    def defaults(self) -> SessionPolicy:
        return self._defaults

    async def current(self) -> AuthPolicy:
        if self._current is not None:
            return self._current
        raw = await self._store.get(POLICY_CACHE_KEY)
        if raw is not None:
            self._current = _decode(raw)
            return self._current
        policy = await self._repository.load()
        await self._store.set(POLICY_CACHE_KEY, _encode(policy), ttl=POLICY_CACHE_SECONDS)
        self._current = policy
        return policy

    async def session_policy(self) -> SessionPolicy:
        return (await self.current()).session_policy(self._defaults)

    async def forget(self) -> None:
        """The policy changed: every replica rereads it on its next request."""
        self._current = None
        await self._store.delete(POLICY_CACHE_KEY)
