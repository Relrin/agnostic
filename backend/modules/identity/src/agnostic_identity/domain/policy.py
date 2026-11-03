"""The org's authentication policy: enforced SSO with a break-glass Owner, session lifetimes, MFA. Pure Python.

MFA policy semantics (second factors only apply to email + password sign-in; SSO sign-ins rely on the IdP's MFA):

- ``off``: nobody can enroll a new factor. Factors people already enrolled keep being asked for, so turning the
  policy off never silently weakens an account.
- ``optional`` (default): anyone may enroll; a person with a factor is always asked for it.
- ``required_local``: every password sign-in needs a second factor; people without one enroll before they get a
  session.
- ``required_admins``: like ``required_local``, for Owners and Administrators only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from agnostic_identity.domain.users import SessionPolicy

REAUTH_WINDOW = timedelta(minutes=10)
"""Sensitive changes need a sign-in or step-up this recent."""
ADMIN_ROLES = frozenset({"owner", "administrator"})
MIN_IDLE_MINUTES = 5
MAX_IDLE_MINUTES = 30 * 24 * 60
MIN_ABSOLUTE_HOURS = 1
MAX_ABSOLUTE_HOURS = 90 * 24


class MfaPolicy(StrEnum):
    OFF = "off"
    OPTIONAL = "optional"
    REQUIRED_LOCAL = "required_local"
    REQUIRED_ADMINS = "required_admins"


class InvalidPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AuthPolicy:
    enforce_sso: bool = False
    break_glass_user_id: str | None = None
    session_idle_minutes: int | None = None
    """``None``: the installation default (``AGNOSTIC_IDENTITY__SESSION_IDLE_HOURS``)."""
    session_absolute_hours: int | None = None
    """``None``: the installation default (``AGNOSTIC_IDENTITY__SESSION_ABSOLUTE_DAYS``)."""
    mfa_policy: MfaPolicy = MfaPolicy.OPTIONAL
    updated_by: str | None = None
    updated_at: datetime | None = None

    def session_policy(self, default: SessionPolicy) -> SessionPolicy:
        return SessionPolicy(
            idle=timedelta(minutes=self.session_idle_minutes) if self.session_idle_minutes else default.idle,
            absolute=timedelta(hours=self.session_absolute_hours) if self.session_absolute_hours else default.absolute,
        )

    def is_break_glass(self, user_id: str) -> bool:
        return self.break_glass_user_id is not None and self.break_glass_user_id == user_id

    def password_allowed(self, user_id: str) -> bool:
        """With SSO enforced, only the break-glass account may still sign in with a password."""
        return not self.enforce_sso or self.is_break_glass(user_id)

    @property
    def enrollment_allowed(self) -> bool:
        return self.mfa_policy is not MfaPolicy.OFF

    def mfa_required_for(self, org_role: str | None) -> bool:
        if self.mfa_policy is MfaPolicy.REQUIRED_LOCAL:
            return True
        return self.mfa_policy is MfaPolicy.REQUIRED_ADMINS and org_role in ADMIN_ROLES

    def updated(
        self,
        *,
        enforce_sso: bool,
        break_glass_user_id: str | None,
        session_idle_minutes: int | None,
        session_absolute_hours: int | None,
        mfa_policy: MfaPolicy,
    ) -> AuthPolicy:
        check_lifetimes(session_idle_minutes, session_absolute_hours)
        if enforce_sso and not break_glass_user_id:
            raise InvalidPolicyError("Enforcing SSO needs a break-glass Owner who can still sign in with a password.")
        return replace(
            self,
            enforce_sso=enforce_sso,
            break_glass_user_id=break_glass_user_id,
            session_idle_minutes=session_idle_minutes,
            session_absolute_hours=session_absolute_hours,
            mfa_policy=mfa_policy,
        )


def check_lifetimes(idle_minutes: int | None, absolute_hours: int | None) -> None:
    if idle_minutes is not None and not MIN_IDLE_MINUTES <= idle_minutes <= MAX_IDLE_MINUTES:
        raise InvalidPolicyError(f"The idle timeout must be {MIN_IDLE_MINUTES} minutes to 30 days.")
    if absolute_hours is not None and not MIN_ABSOLUTE_HOURS <= absolute_hours <= MAX_ABSOLUTE_HOURS:
        raise InvalidPolicyError("The absolute session lifetime must be 1 hour to 90 days.")
    if idle_minutes is not None and absolute_hours is not None and idle_minutes > absolute_hours * 60:
        raise InvalidPolicyError("The idle timeout can't be longer than the absolute session lifetime.")


def is_recent(authenticated_at: datetime | None, now: datetime, window: timedelta = REAUTH_WINDOW) -> bool:
    return authenticated_at is not None and now - authenticated_at <= window
