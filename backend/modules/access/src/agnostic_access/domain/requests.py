"""Temporary access: someone asks for a role (or scopes) on an instance for a while; an approver grants it.

Approval creates a binding that expires; the expiry job removes it. Owners and Administrators can also grant
temporary access directly, without a request.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

REQUEST_ID_PREFIX = "areq"
DEFAULT_MAX_HOURS = 168

type RequestStatus = Literal["pending", "approved", "denied", "cancelled", "expired"]


class InvalidRequestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AccessRequest:
    id: str
    requester_id: str
    instance_id: str | None
    role_id: str | None
    scopes: tuple[str, ...]
    reason: str
    duration_hours: int
    status: RequestStatus
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    binding_id: str | None = None
    expires_at: datetime | None = None

    @property
    def open(self) -> bool:
        return self.status == "pending"

    def approve(self, *, by: str, at: datetime, binding_id: str, note: str | None) -> AccessRequest:
        self._check_open()
        if by == self.requester_id:
            raise InvalidRequestError("You can't approve your own request.")
        return replace(
            self,
            status="approved",
            decided_by=by,
            decided_at=at,
            note=note,
            binding_id=binding_id,
            expires_at=at + timedelta(hours=self.duration_hours),
        )

    def deny(self, *, by: str, at: datetime, note: str | None) -> AccessRequest:
        self._check_open()
        return replace(self, status="denied", decided_by=by, decided_at=at, note=note)

    def cancel(self, *, by: str, at: datetime) -> AccessRequest:
        self._check_open()
        if by != self.requester_id:
            raise InvalidRequestError("Only the person who asked can cancel a request.")
        return replace(self, status="cancelled", decided_by=by, decided_at=at)

    def expire(self) -> AccessRequest:
        return replace(self, status="expired")

    def _check_open(self) -> None:
        if not self.open:
            raise InvalidRequestError(f"This request is already {self.status}.")


def check_duration(hours: int, *, max_hours: int) -> int:
    if hours < 1:
        raise InvalidRequestError("Temporary access lasts at least an hour.")
    if hours > max_hours:
        raise InvalidRequestError(f"Temporary access lasts at most {max_hours} hours here.")
    return hours


def check_reason(reason: str) -> str:
    cleaned = " ".join(reason.split())
    if not cleaned:
        raise InvalidRequestError("Say why you need the access; approvers see it, and so does the audit log.")
    return cleaned[:500]
