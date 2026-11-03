"""What can be notified, through which channels, and who decides.

Personal channels reach one person: ``in_app`` (the bell), ``email`` (their address) and ``slack`` (a direct message
from the org's Slack bot). Org channels (a Slack channel, a shared mailbox, a webhook) get one message per event,
when they subscribe to its type or when an approval route names them.

A person's preference for an event type wins over the org default, which wins over the catalogue default. Quiet
hours hold back email and Slack, never the bell.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

type PersonalChannel = Literal["in_app", "email", "slack"]
type ChannelKind = Literal["slack", "email", "webhook"]

PERSONAL_CHANNELS: tuple[PersonalChannel, ...] = ("in_app", "email", "slack")
CHANNEL_KINDS: tuple[ChannelKind, ...] = ("slack", "email", "webhook")


@dataclass(frozen=True, slots=True)
class EventType:
    name: str
    label: str
    description: str
    defaults: tuple[PersonalChannel, ...]


EVENT_TYPES: tuple[EventType, ...] = (
    EventType("approval.created", "Approval requested", "A run paused for an approval routed to you.", ("in_app",)),
    EventType(
        "approval.expiring", "Approval expiring", "An approval routed to you expires within the hour.", ("in_app",)
    ),
    EventType("approval.resolved", "Approval resolved", "Someone decided an approval you requested.", ("in_app",)),
    EventType("schedule.failed", "Schedule failed", "A scheduled run failed.", ("in_app",)),
    EventType("evals.regression", "Eval regression", "An evaluation you started found regressions.", ("in_app",)),
    EventType("conflict.detected", "Conflict detected", "A component changed in the instance and in git.", ("in_app",)),
    EventType(
        "access.privileged_grant",
        "Privileged access granted",
        "Someone got admin-level access (Owners and Administrators).",
        ("in_app", "email"),
    ),
    EventType(
        "access.request_created",
        "Access requested",
        "Someone asked for temporary access you can approve.",
        ("in_app", "email"),
    ),
    EventType(
        "access.request_decided",
        "Access request decided",
        "Your temporary access request was approved or denied.",
        ("in_app", "email"),
    ),
    EventType(
        "service_accounts.privileged_created",
        "Privileged service account",
        "A service account with write, delete or admin scopes was created (Owners).",
        ("in_app", "email"),
    ),
    EventType(
        "identity.break_glass_used",
        "Break-glass sign-in",
        "The break-glass account signed in with a password while SSO is enforced (Owners).",
        ("in_app", "email"),
    ),
    EventType(
        "audit.archive_failed",
        "Audit archive failed",
        "A month of audit events couldn't be archived; it stays in the database (Owners and Administrators).",
        ("in_app", "email"),
    ),
    EventType(
        "audit.sink_failing",
        "SIEM delivery failing",
        "Audit events can't be delivered to a SIEM destination (Owners and Administrators).",
        ("in_app", "email"),
    ),
)

EVENTS_BY_NAME: Mapping[str, EventType] = {event.name: event for event in EVENT_TYPES}


class UnknownEventTypeError(ValueError):
    pass


def event_type(name: str) -> EventType:
    try:
        return EVENTS_BY_NAME[name]
    except KeyError as exc:
        raise UnknownEventTypeError(f"Unknown notification event {name!r}.") from exc


@dataclass(frozen=True, slots=True)
class QuietHours:
    """From ``start`` to ``end`` in the person's timezone; wraps past midnight when ``end`` <= ``start``."""

    start: time
    end: time
    timezone: str = "UTC"

    def contains(self, moment: datetime) -> bool:
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError, ValueError:
            zone = ZoneInfo("UTC")
        local = moment.astimezone(zone).time().replace(tzinfo=None)
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end


def personal_channels(
    event: str,
    *,
    preference: Sequence[str] | None,
    org_default: Sequence[str] | None,
    quiet: QuietHours | None = None,
    now: datetime | None = None,
    forced: Collection[str] = (),
) -> tuple[PersonalChannel, ...]:
    """The personal channels one event reaches a person through.

    ``forced`` channels come from routing (an approval route that says "Slack + control plane") and add to what the
    person chose; quiet hours still hold them back.
    """
    chosen = preference if preference is not None else org_default
    if chosen is None:
        chosen = event_type(event).defaults
    wanted: list[PersonalChannel] = [channel for channel in PERSONAL_CHANNELS if channel in set(chosen) | set(forced)]
    if quiet is not None and now is not None and quiet.contains(now):
        wanted = [channel for channel in wanted if channel == "in_app"]
    return tuple(wanted)


def valid_channels(channels: Sequence[str]) -> tuple[PersonalChannel, ...]:
    unknown = [channel for channel in channels if channel not in PERSONAL_CHANNELS]
    if unknown:
        raise ValueError(f"Unknown channels: {', '.join(unknown)}.")
    return tuple(channel for channel in PERSONAL_CHANNELS if channel in channels)
