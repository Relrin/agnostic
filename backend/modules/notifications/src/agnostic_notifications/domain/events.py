"""Who may see which realtime event, and the SSE wire format.

Event catalogue (``data`` always carries ``instance_id`` when the event concerns one instance):

========================  ===============================  ======================================
type                      channel                          visible to
========================  ===============================  ======================================
``approvals.count``       ``evt:instance:{id}``            holders of ``approvals:read`` there
``approval.created``      ``evt:instance:{id}``            holders of ``approvals:read`` there
``approval.viewed``       ``evt:instance:{id}``            holders of ``approvals:read`` there
``approval.resolved``     ``evt:instance:{id}``            holders of ``approvals:read`` there
``schedule.failed``       ``evt:instance:{id}``            holders of ``schedules:read`` there
``instance.health``       ``evt:instance:{id}``            anyone with access to the instance
``access.changed``        (synthesised per stream)         the person whose stream it is
``job.progress``          ``evt:user:{id}``                that person
``notification.created``  ``evt:user:{id}``                that person (the bell)
``notification.read``     ``evt:user:{id}``                that person (other tabs clear the badge)
========================  ===============================  ======================================
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

SCOPED_EVENTS: Mapping[str, str] = {
    "approvals.count": "approvals:read",
    "approval.created": "approvals:read",
    "approval.viewed": "approvals:read",
    "approval.resolved": "approvals:read",
    "schedule.failed": "schedules:read",
}


def visible(event_type: str, instance_id: str | None, grants: Mapping[str, frozenset[str]]) -> bool:
    """``grants`` maps instance id → the scopes (from :data:`SCOPED_EVENTS`) the person holds there."""
    if instance_id is None:
        return True
    if instance_id not in grants:
        return False
    required = SCOPED_EVENTS.get(event_type)
    return required is None or required in grants[instance_id]


def frame(event_id: str | None, event_type: str, data: Mapping[str, Any]) -> bytes:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append("data: " + json.dumps(dict(data), separators=(",", ":"), default=str))
    return ("\n".join(lines) + "\n\n").encode()


HEARTBEAT = b": keepalive\n\n"
