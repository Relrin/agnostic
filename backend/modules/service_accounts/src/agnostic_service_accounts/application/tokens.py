"""Gateway tokens (``agn_pat_…``): who is calling with an ``Authorization: Bearer`` header."""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_service_accounts.application.ports import ServiceAccountRepository
from agnostic_service_accounts.domain.accounts import hash_token, looks_like_gateway_token

GATEWAY_VIA = "gateway-pat"


@dataclass(frozen=True, slots=True)
class TokenHashing:
    pepper: str
    touch_every_seconds: float = 60.0
    """``last_used_at`` is written at most this often per token."""
    previous_peppers: tuple[str, ...] = ()
    """Peppers derived from retired master keys: tokens hashed with them still resolve and are re-hashed."""

    def hash(self, token: str) -> str:
        return hash_token(self.pepper, token)

    def previous_hashes(self, token: str) -> list[str]:
        return [hash_token(pepper, token) for pepper in self.previous_peppers if pepper != self.pepper]


class GatewayTokenResolver:
    """Identity's ``BearerPrincipalResolver``: valid tokens (rotated ones during their grace) of live accounts."""

    def __init__(self, accounts: ServiceAccountRepository, hashing: TokenHashing, store: EphemeralStore) -> None:
        self._accounts = accounts
        self._hashing = hashing
        self._store = store

    async def resolve(self, token: str, *, ip: str | None) -> Principal | None:
        if not looks_like_gateway_token(token):
            return None
        now = utcnow()
        current = self._hashing.hash(token)
        found = await self._accounts.gateway_token_by_hash(current)
        if found is None:
            for previous in self._hashing.previous_hashes(token):
                found = await self._accounts.gateway_token_by_hash(previous)
                if found is not None:
                    await self._accounts.rehash_gateway(found.id, current)
                    break
        if found is None or not found.valid(now):
            return None
        account = await self._accounts.get(found.account_id)
        if account is None or not account.usable(now):
            return None
        if await self._store.set_if_absent(f"sa:used:{found.id}", b"1", ttl=self._hashing.touch_every_seconds):
            await self._accounts.touch_gateway(found.id, at=now, ip=ip)
        return Principal(
            kind="service_account",
            id=account.id,
            display_name=account.principal,
            via=GATEWAY_VIA,
            forwards_user_id=account.forwards_user_id,
        )
