"""Web sessions: issue, resolve (sliding expiry), revoke; and the principal behind a request."""

from __future__ import annotations

from dataclasses import dataclass, replace

from agnostic_identity.application.ports import SessionRecordRepository, SessionStore
from agnostic_identity.domain.users import SessionPolicy, User, WebSession
from agnostic_kernel.auth import Principal
from agnostic_kernel.context import current_client
from agnostic_kernel.crypto import hash_token, new_token, tokens_equal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import ForbiddenError

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REFRESH_AFTER_SECONDS = 60


class CsrfError(ForbiddenError):
    code = "csrf_failed"
    title = "The request is missing its CSRF token"


@dataclass(frozen=True, slots=True)
class IssuedSession:
    cookie_value: str
    csrf_token: str
    session: WebSession
    ttl: float


class Sessions:
    def __init__(self, store: SessionStore, records: SessionRecordRepository, policy: SessionPolicy) -> None:
        self._store = store
        self._records = records
        self._policy = policy

    async def issue(self, user: User, *, method: str) -> IssuedSession:
        """A fresh session (ids are never reused, so this also rotates). The caller commits the audit copy."""
        cookie_value = new_token(32)
        now = utcnow()
        client = current_client()
        session = WebSession(
            key=hash_token(cookie_value),
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            csrf_token=new_token(24),
            created_at=now,
            last_seen_at=now,
            ip=client.ip,
            user_agent=client.user_agent,
            method=method,
        )
        ttl = self._policy.ttl(now, now)
        await self._store.save(session, ttl)
        await self._records.add(session)
        return IssuedSession(cookie_value=cookie_value, csrf_token=session.csrf_token, session=session, ttl=ttl)

    async def resolve(self, cookie_value: str) -> WebSession | None:
        session = await self._store.load(hash_token(cookie_value))
        if session is None:
            return None
        now = utcnow()
        ttl = self._policy.ttl(now, session.created_at)
        if ttl <= 0:
            await self._store.delete(session.key)
            return None
        if (now - session.last_seen_at).total_seconds() > REFRESH_AFTER_SECONDS:
            session = replace(session, last_seen_at=now)
            await self._store.save(session, ttl)
        return session

    async def revoke(self, *keys: str) -> None:
        await self._store.delete(*keys)
        await self._records.revoke(keys, utcnow())

    async def revoke_user(self, user_id: str) -> None:
        await self.revoke(*await self._records.active_keys(user_id))

    async def update_profile(self, session: WebSession, *, display_name: str) -> None:
        ttl = self._policy.ttl(utcnow(), session.created_at)
        if ttl > 0:
            await self._store.save(replace(session, display_name=display_name), ttl)


class ResolvePrincipal:
    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def __call__(self, cookie_value: str | None, csrf_header: str | None, method: str) -> Principal | None:
        if not cookie_value:
            return None
        session = await self._sessions.resolve(cookie_value)
        if session is None:
            return None
        if method.upper() not in SAFE_METHODS and not tokens_equal(csrf_header or "", session.csrf_token):
            raise CsrfError("Reload the page and try again (the X-CSRF-Token header doesn't match your session).")
        return Principal(
            kind="user",
            id=session.user_id,
            display_name=session.display_name,
            email=session.email,
            session_id=session.key,
        )
