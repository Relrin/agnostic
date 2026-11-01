"""Minting per-instance JWTs. Private keys are decrypted only here and only kept in this process's memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from agnostic_instances.application.ports import KeyRepository, Signer
from agnostic_instances.domain.instances import AuthMode, Instance, KeyStatus
from agnostic_kernel.crypto import SecretBox, new_token
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ConflictError

DEFAULT_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class TokenPolicy:
    issuer: str
    ttl: timedelta = DEFAULT_TTL


@dataclass(frozen=True, slots=True)
class MintedToken:
    token: str
    kid: str
    jti: str
    expires_at: datetime


class PrivateKeyCache:
    """Decrypted signing keys by ``(instance, kid)``; APP-scoped so decryption happens once per process."""

    def __init__(self) -> None:
        self._keys: dict[tuple[str, str], str] = {}

    def get(self, instance_id: str, kid: str) -> str | None:
        return self._keys.get((instance_id, kid))

    def put(self, instance_id: str, kid: str, pem: str) -> None:
        self._keys[(instance_id, kid)] = pem

    def forget(self, instance_id: str) -> None:
        for key in [key for key in self._keys if key[0] == instance_id]:
            del self._keys[key]


class NoSigningKeyError(ConflictError):
    code = "no_signing_key"
    title = "This instance has no active signing key"


class TokenService:
    def __init__(
        self, keys: KeyRepository, signer: Signer, box: SecretBox, cache: PrivateKeyCache, policy: TokenPolicy
    ) -> None:
        self._keys = keys
        self._signer = signer
        self._box = box
        self._cache = cache
        self._policy = policy

    async def _active(self, instance: Instance) -> tuple[str, str]:
        active = await self._keys.list(instance.id, [KeyStatus.ACTIVE])
        if not active:
            raise NoSigningKeyError(f"{instance.display_name} has no active key pair. Rotate keys to create one.")
        kid = active[0].kid
        pem = self._cache.get(instance.id, kid)
        if pem is None:
            sealed = await self._keys.private(instance.id, kid)
            if sealed is None:
                raise NoSigningKeyError(f"The private key {kid} of {instance.display_name} is missing.")
            pem = self._box.open(sealed).decode()
            self._cache.put(instance.id, kid, pem)
        return kid, pem

    async def mint(
        self,
        instance: Instance,
        *,
        subject: str,
        scopes: Sequence[str],
        name: str | None = None,
        via: str = "gateway",
        ttl: timedelta | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> MintedToken:
        if instance.auth_mode not in {AuthMode.JWT, AuthMode.UNKNOWN, AuthMode.NONE}:
            raise ConflictError(f"{instance.display_name} doesn't use JWT authorization.")
        kid, pem = await self._active(instance)
        now = utcnow()
        expires_at = now + (ttl or self._policy.ttl)
        jti = new_token(12)
        claims: dict[str, Any] = {
            "iss": self._policy.issuer,
            "aud": instance.os_id or instance.id,
            "sub": subject,
            "scopes": list(scopes),
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": jti,
            "agnostic": {"via": via, "instance": instance.id, **({"name": name} if name else {})},
            **(extra or {}),
        }
        return MintedToken(token=self._signer.sign(pem, kid, claims), kid=kid, jti=jti, expires_at=expires_at)
