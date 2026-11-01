"""Password hashing (argon2id) and the session store on top of the kernel's ephemeral store."""

from __future__ import annotations

import asyncio
from datetime import datetime

import orjson
from argon2 import PasswordHasher as Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from agnostic_identity.domain.users import WebSession
from agnostic_kernel.ephemeral import EphemeralStore


class Argon2PasswordHasher:
    """argon2id with the library's RFC 9106 low-memory profile; hashing runs off the event loop."""

    def __init__(self) -> None:
        self._argon2 = Argon2()
        self._dummy = self._argon2.hash("agnostic-timing-equalizer")

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self._argon2.hash, password)

    async def verify(self, password_hash: str | None, password: str) -> bool:
        try:
            return await asyncio.to_thread(self._argon2.verify, password_hash or self._dummy, password) and (
                password_hash is not None
            )
        except VerifyMismatchError, VerificationError, InvalidHashError:
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._argon2.check_needs_rehash(password_hash)


class EphemeralSessionStore:
    def __init__(self, store: EphemeralStore) -> None:
        self._store = store

    async def save(self, session: WebSession, ttl: float) -> None:
        payload = {
            "user_id": session.user_id,
            "email": session.email,
            "display_name": session.display_name,
            "csrf_token": session.csrf_token,
            "created_at": session.created_at.isoformat(),
            "last_seen_at": session.last_seen_at.isoformat(),
            "ip": session.ip,
            "user_agent": session.user_agent,
            "method": session.method,
        }
        await self._store.set(f"sess:{session.key}", orjson.dumps(payload), ttl=ttl)

    async def load(self, key: str) -> WebSession | None:
        raw = await self._store.get(f"sess:{key}")
        if raw is None:
            return None
        data = orjson.loads(raw)
        return WebSession(
            key=key,
            user_id=data["user_id"],
            email=data["email"],
            display_name=data["display_name"],
            csrf_token=data["csrf_token"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_seen_at=datetime.fromisoformat(data["last_seen_at"]),
            ip=data.get("ip"),
            user_agent=data.get("user_agent"),
            method=data.get("method", "password"),
        )

    async def delete(self, *keys: str) -> None:
        await self._store.delete(*(f"sess:{key}" for key in keys))
