"""The only import surface other modules may use: accounts, sessions, and the membership port org implements."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from fastapi import Response

from agnostic_identity.application.account import CreateLocalAccount
from agnostic_identity.application.ports import (
    Admission,
    BearerPrincipalResolver,
    ExternalGroupsSync,
    Membership,
    MembershipDirectory,
    UserRepository,
)
from agnostic_identity.application.sessions import (
    InteractiveSessionRequiredError,
    IssuedSession,
    ReauthRequiredError,
    RecentAuth,
    Sessions,
)
from agnostic_identity.domain.users import CreatedVia, User, UserStatus, clean_display_name, normalize_email
from agnostic_kernel.auth import Principal

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "Admission",
    "BearerPrincipalResolver",
    "CreatedVia",
    "ExternalGroupsSync",
    "IdentityFacade",
    "IdentityFacadeImpl",
    "InteractiveSessionRequiredError",
    "IssuedSession",
    "Membership",
    "MembershipDirectory",
    "ReauthRequiredError",
    "SessionCookies",
    "User",
    "UserStatus",
    "clear_session_cookies",
    "normalize_email",
    "set_session_cookies",
]

SESSION_COOKIE = "agnostic_session"
CSRF_COOKIE = "agnostic_csrf"
CSRF_HEADER = "X-CSRF-Token"


class IdentityFacade(Protocol):
    async def get_user(self, user_id: str) -> User | None: ...
    async def get_users(self, user_ids: Sequence[str]) -> list[User]: ...
    async def find_user_by_email(self, email: str) -> User | None: ...
    async def create_local_account(self, email: str, display_name: str | None, password: str, via: CreatedVia) -> User:
        """Validates the password policy; the caller commits."""
        ...

    async def issue_session(self, user: User, *, method: str) -> IssuedSession:
        """Sign ``user`` in (e.g. right after accepting an invitation); the caller commits."""
        ...

    async def revoke_sessions(self, user_id: str) -> None: ...
    async def set_status(self, user_id: str, status: UserStatus) -> User: ...
    async def provision_user(self, email: str, display_name: str | None, *, via: CreatedVia) -> User:
        """An account without a password (SCIM, directory sync): it signs in through SSO. The caller commits."""
        ...

    async def update_user(self, user_id: str, *, display_name: str | None = None) -> User: ...
    async def require_recent_auth(self, principal: Principal) -> None:
        """Guard for sensitive changes: the person signed in or stepped up (``POST /auth/step-up``) < 10 min ago.

        Raises a 403 problem with code ``reauth_required`` (the web app opens its re-authentication dialog and
        retries), or ``interactive_session_required`` for service accounts and other principals without a web
        session: those can't re-authenticate, so they can't make these changes at all.
        """
        ...


class IdentityFacadeImpl:
    def __init__(
        self, users: UserRepository, sessions: Sessions, create_account: CreateLocalAccount, recent: RecentAuth
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._create_account = create_account
        self._recent = recent

    async def require_recent_auth(self, principal: Principal) -> None:
        await self._recent.require(principal)

    async def get_user(self, user_id: str) -> User | None:
        return await self._users.get(user_id)

    async def get_users(self, user_ids: Sequence[str]) -> list[User]:
        return await self._users.get_many(user_ids)

    async def find_user_by_email(self, email: str) -> User | None:
        return await self._users.find_by_email(normalize_email(email))

    async def create_local_account(self, email: str, display_name: str | None, password: str, via: CreatedVia) -> User:
        return await self._create_account(email, display_name, password, via)

    async def issue_session(self, user: User, *, method: str) -> IssuedSession:
        return await self._sessions.issue(user, method=method)

    async def revoke_sessions(self, user_id: str) -> None:
        await self._sessions.revoke_user(user_id)

    async def set_status(self, user_id: str, status: UserStatus) -> User:
        return await self._users.update(user_id, status=status)

    async def provision_user(self, email: str, display_name: str | None, *, via: CreatedVia) -> User:
        address = normalize_email(email)
        existing = await self._users.find_by_email(address)
        if existing is not None:
            return existing
        return await self._users.add(
            email=address, display_name=clean_display_name(display_name, address), created_via=via
        )

    async def update_user(self, user_id: str, *, display_name: str | None = None) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise LookupError(user_id)
        name = clean_display_name(display_name, user.email) if display_name is not None else None
        return await self._users.update(user_id, display_name=name)


class SessionCookies:
    """Sets and clears the session + CSRF cookies with the installation's cookie policy."""

    def __init__(self, *, secure: bool, max_age: int) -> None:
        self.secure = secure
        self.max_age = max_age

    def set(self, response: Response, issued: IssuedSession) -> None:
        set_session_cookies(response, issued, secure=self.secure, max_age=issued.max_age or self.max_age)

    def clear(self, response: Response) -> None:
        clear_session_cookies(response, secure=self.secure)


def set_session_cookies(response: Response, issued: IssuedSession, *, secure: bool, max_age: int) -> None:
    response.set_cookie(
        SESSION_COOKIE, issued.cookie_value, max_age=max_age, httponly=True, secure=secure, samesite="lax", path="/"
    )
    # Readable by the web app, which echoes it in the X-CSRF-Token header (double submit).
    response.set_cookie(
        CSRF_COOKIE, issued.csrf_token, max_age=max_age, httponly=False, secure=secure, samesite="lax", path="/"
    )


def clear_session_cookies(response: Response, *, secure: bool) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, samesite="lax")
