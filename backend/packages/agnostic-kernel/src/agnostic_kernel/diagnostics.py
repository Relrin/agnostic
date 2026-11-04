"""Results modules report about the endpoints they use and the work they have in flight.

:class:`CheckResult` answers "can this installation reach X?" (``agnostic config check --connect``, ``/readyz``,
the System page). :class:`StatusItem` answers "is background work keeping up?" (delivery backlogs, sync errors) on
the System page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

type StatusState = Literal["ok", "warning", "error"]


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    facts: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True, slots=True)
class StatusItem:
    """One line of the System page, e.g. ``("Notifications", "Email deliveries", "warning", "3 failed in 24 h")``."""

    group: str
    name: str
    state: StatusState
    detail: str = ""
    facts: dict[str, str] = field(default_factory=dict[str, str])
