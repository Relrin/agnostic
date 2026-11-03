"""The approvals inbox: what a row shows, when an approval expires, who it is routed to, and its timeline.

AgentOS keeps approvals (``agno_approvals``) and never expires them by itself: agent and team approvals carry no
``expires_at``, and a workflow ``HumanReview`` timeout is only checked when someone continues the run. The control
plane therefore computes an *effective* expiry (the approval's own ``expires_at``, else the workflow step's
``timeout_at``, else the org TTL) and, where an instance enforces expiry, acts on it.

How an expired approval is shown:

* AgentOS ``rejected`` with ``resolution_data.expired`` (the control plane enforced it) is ``expired``;
* ``pending`` past its effective expiry is ``expired`` too, with ``enforced=False``: nothing happened to the run yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

type DisplayStatus = Literal["pending", "approved", "rejected", "expired", "cancelled"]
type SourceKind = Literal["agent", "team", "workflow", "schedule"]
type TimelineState = Literal["done", "now", "end"]

STATUSES: tuple[DisplayStatus, ...] = ("pending", "approved", "rejected", "expired", "cancelled")


def _epoch(value: object) -> datetime | None:
    if isinstance(value, bool) or value in {None, ""}:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            try:
                return datetime.fromtimestamp(float(value), tz=UTC)
            except ValueError:
                return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _str(value: object) -> str | None:
    return str(value) if value not in {None, ""} else None


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """An AgentOS ``ApprovalResponse`` with typed timestamps."""

    id: str
    status: str
    approval_type: str
    pause_type: str | None
    tool_name: str | None
    tool_args: Mapping[str, Any]
    run_id: str | None
    session_id: str | None
    user_id: str | None
    agent_id: str | None
    team_id: str | None
    workflow_id: str | None
    schedule_id: str | None
    source_type: str | None
    source_name: str | None
    requirements: Sequence[Mapping[str, Any]]
    resolution_data: Mapping[str, Any]
    resolved_by: str | None
    created_at: datetime | None
    resolved_at: datetime | None
    expires_at: datetime | None
    run_status: str | None
    raw: Mapping[str, Any] = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, body: Mapping[str, Any]) -> ApprovalRecord:
        requirements: Any = body.get("requirements") or []
        if isinstance(requirements, dict):
            requirements = [requirements]
        return cls(
            id=str(body.get("id") or ""),
            status=str(body.get("status") or "pending"),
            approval_type=str(body.get("approval_type") or "required"),
            pause_type=_str(body.get("pause_type")),
            tool_name=_str(body.get("tool_name")),
            tool_args=cast("Mapping[str, Any]", body.get("tool_args") or {}),
            run_id=_str(body.get("run_id")),
            session_id=_str(body.get("session_id")),
            user_id=_str(body.get("user_id")),
            agent_id=_str(body.get("agent_id")),
            team_id=_str(body.get("team_id")),
            workflow_id=_str(body.get("workflow_id")),
            schedule_id=_str(body.get("schedule_id")),
            source_type=_str(body.get("source_type")),
            source_name=_str(body.get("source_name")),
            requirements=[
                cast("Mapping[str, Any]", item) for item in cast("list[Any]", requirements) if isinstance(item, dict)
            ],
            resolution_data=cast("Mapping[str, Any]", body.get("resolution_data") or {}),
            resolved_by=_str(body.get("resolved_by")),
            created_at=_epoch(body.get("created_at")),
            resolved_at=_epoch(body.get("resolved_at")),
            expires_at=_epoch(body.get("expires_at")),
            run_status=_str(body.get("run_status")),
            raw=dict(body),
        )

    @property
    def kind(self) -> Literal["blocking", "audit"]:
        return "audit" if self.approval_type == "audit" else "blocking"

    @property
    def component(self) -> tuple[Literal["agent", "team", "workflow"], str] | None:
        """The paused run's owner (a workflow wins over a team, a team over an agent)."""
        if self.workflow_id:
            return "workflow", self.workflow_id
        if self.team_id:
            return "team", self.team_id
        if self.agent_id:
            return "agent", self.agent_id
        return None

    @property
    def source(self) -> tuple[SourceKind, str] | None:
        if self.schedule_id:
            return "schedule", self.source_name or self.schedule_id
        component = self.component
        if component is None:
            return None
        return component[0], self.source_name if self.source_name and component[0] != "workflow" else component[1]

    def step_timeout(self) -> datetime | None:
        """The earliest ``timeout_at`` of a workflow ``HumanReview`` step this approval waits on."""
        found = [moment for item in self.requirements if (moment := _epoch(item.get("timeout_at"))) is not None]
        return min(found) if found else None


@dataclass(frozen=True, slots=True)
class Expiry:
    at: datetime | None
    source: Literal["approval", "step_timeout", "ttl"] | None


def effective_expiry(record: ApprovalRecord, ttl_hours: int) -> Expiry:
    if record.expires_at is not None:
        return Expiry(record.expires_at, "approval")
    step = record.step_timeout()
    if step is not None:
        return Expiry(step, "step_timeout")
    if ttl_hours > 0 and record.created_at is not None:
        return Expiry(record.created_at + timedelta(hours=ttl_hours), "ttl")
    return Expiry(None, None)


def expired_by_agnostic(record: ApprovalRecord) -> bool:
    return bool(record.resolution_data.get("expired"))


def display_status(record: ApprovalRecord, expiry: Expiry, now: datetime, *, enforced: bool = False) -> DisplayStatus:
    if record.status == "rejected" and expired_by_agnostic(record):
        return "expired"
    if record.status == "pending":
        if enforced or (expiry.at is not None and expiry.at <= now):
            return "expired"
        return "pending"
    if record.status in {"approved", "rejected", "expired", "cancelled"}:
        return cast("DisplayStatus", record.status)
    return "pending"


@dataclass(frozen=True, slots=True)
class Route:
    """An approval routing rule: who hears about which approvals, through which channels.

    Routing is advisory: AgentOS (through the person's scopes) decides who can resolve.
    """

    id: str
    instance_id: str | None
    name: str
    tool_name: str | None
    component_kind: Literal["agent", "team", "workflow"] | None
    component_ids: tuple[str, ...]
    member_ids: tuple[str, ...]
    role_ids: tuple[str, ...]
    channels: tuple[str, ...]
    """Personal channels added for the routed people (``in_app``, ``slack``, ``email``)."""
    channel_ids: tuple[str, ...]
    """Org notification channels the approval is posted to."""
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    def matches(self, record: ApprovalRecord) -> bool:
        if self.tool_name and self.tool_name != record.tool_name:
            return False
        component = record.component
        if self.component_kind and (component is None or component[0] != self.component_kind):
            return False
        return not self.component_ids or (component is not None and component[1] in self.component_ids)

    @property
    def specificity(self) -> int:
        return (2 if self.tool_name else 0) + (1 if self.component_ids or self.component_kind else 0)


def matching_routes(routes: Iterable[Route], record: ApprovalRecord, instance_id: str) -> list[Route]:
    """Routes that apply: the instance's own rules when any matches, otherwise the org-wide ones."""
    candidates = [route for route in routes if route.matches(record)]
    own = [route for route in candidates if route.instance_id == instance_id]
    chosen = own or [route for route in candidates if route.instance_id is None]
    return sorted(chosen, key=lambda route: (-route.specificity, route.name))


@dataclass(frozen=True, slots=True)
class ApprovalEvent:
    """Something the control plane did or saw: ``routed``, ``notified``, ``expiring``, ``expired``, ``continued``."""

    kind: str
    at: datetime
    detail: Mapping[str, Any]
    actor: str | None = None


@dataclass(frozen=True, slots=True)
class View:
    user_id: str
    name: str
    at: datetime


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    text: str
    at: datetime | None
    detail: str | None
    state: TimelineState


def _names(values: Iterable[object]) -> str:
    items = [str(value) for value in values if value]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def timeline(  # noqa: C901, PLR0912  (one narrative, one branch per kind of entry)
    record: ApprovalRecord,
    *,
    status: DisplayStatus,
    expiry: Expiry,
    events: Sequence[ApprovalEvent],
    views: Sequence[View],
    resolver_name: str | None,
    run_status: str | None,
) -> list[TimelineEntry]:
    """The narrative under an approval: paused, routed, viewed, then decided, expired or still waiting."""
    entries: list[TimelineEntry] = []
    paused = "Run paused" if record.kind == "blocking" else "Confirmation recorded"
    entries.append(
        TimelineEntry(
            f"{paused} at {record.tool_name or 'a step'}"
            + (" · run_status PAUSED" if record.kind == "blocking" else ""),
            record.created_at,
            None,
            "done",
        )
    )
    for event in sorted(events, key=lambda e: e.at):
        if event.kind == "routed":
            groups = cast("list[str]", event.detail.get("routed_to") or [])
            channels = cast("list[str]", event.detail.get("channels") or [])
            if groups:
                entries.append(TimelineEntry(f"Routed to {_names(groups)}", event.at, _names(channels) or None, "done"))
        elif event.kind == "expiring":
            entries.append(TimelineEntry("Expiry reminder sent", event.at, None, "done"))
    entries.extend(TimelineEntry(f"Viewed by {view.name}", view.at, None, "done") for view in views)
    entries.sort(key=lambda entry: entry.at or datetime.min.replace(tzinfo=UTC))

    expired_event = next((e for e in events if e.kind == "expired"), None)
    if status == "pending":
        detail = f"Expires {expiry.at.strftime('%a %d %b %H:%M UTC')}" if expiry.at else "No expiry"
        entries.append(TimelineEntry("Waiting for a decision", None, detail, "now"))
    elif status == "expired":
        if expired_event is not None:
            what = str(expired_event.detail.get("outcome") or "The run was stopped.")
            entries.append(TimelineEntry("Expired without a decision", expired_event.at, what, "end"))
        else:
            entries.append(
                TimelineEntry(
                    "Expired without a decision",
                    expiry.at,
                    "Expiry isn't enforced on this instance: the run stays paused until someone continues it.",
                    "end",
                )
            )
    else:
        verb = {"approved": "Approved", "rejected": "Rejected", "cancelled": "Cancelled"}.get(status, status.title())
        if record.kind == "audit" and status == "approved":
            verb = "Confirmed"
        who = f" by {resolver_name}" if resolver_name else ""
        entries.append(TimelineEntry(f"{verb}{who}", record.resolved_at, record.resolution_data.get("note"), "done"))
        continued = next((e for e in events if e.kind == "continued"), None)
        if continued is not None:
            state = str(continued.detail.get("continue_state") or "continued")
            text = {
                "continued": "Run continued",
                "pending_admin": "Run waits for an admin to continue it",
                "conflict": "Run resumes when the current continuation finishes",
                "failed": "Continuing the run failed",
            }.get(state, "Run continued")
            entries.append(TimelineEntry(text, continued.at, continued.detail.get("detail"), "done"))
        if run_status:
            entries.append(TimelineEntry(f"Run is {run_status.lower()}", None, None, "end"))
        elif entries:
            last = entries[-1]
            entries[-1] = TimelineEntry(last.text, last.at, last.detail, "end")
    return entries


@dataclass(frozen=True, slots=True)
class ContextExcerpt:
    user_message: str | None
    agent_message: str | None


def _text(content: object) -> str | None:
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        parts = [
            str(cast("dict[str, Any]", part).get("text") or "")
            for part in cast("list[Any]", content)
            if isinstance(part, dict)
        ]
        joined = " ".join(part for part in parts if part).strip()
        return joined or None
    return None


def context_excerpt(run: Mapping[str, Any] | None, limit: int = 600) -> ContextExcerpt:
    """The person's ask and the agent's last words before it paused, from an AgentOS run."""
    if not run:
        return ContextExcerpt(None, None)
    user = _text(run.get("run_input"))
    agent: str | None = None
    for message in reversed(cast("list[Any]", run.get("messages") or [])):
        if not isinstance(message, dict):
            continue
        item = cast("dict[str, Any]", message)
        if item.get("role") == "assistant" and (text := _text(item.get("content"))):
            agent = text
            break
        if user is None and item.get("role") == "user":
            user = _text(item.get("content"))
    if agent is None:
        agent = _text(run.get("content"))

    def clip(value: str | None) -> str | None:
        return value if value is None or len(value) <= limit else value[: limit - 1] + "…"

    return ContextExcerpt(clip(user), clip(agent))


def search_matches(record: ApprovalRecord, query: str, names: Mapping[str, str]) -> bool:
    """``q`` over tool, run, session, approval id, user id and the user's name."""
    needle = query.strip().lower()
    if not needle:
        return True
    haystack = [
        record.id,
        record.tool_name,
        record.run_id,
        record.session_id,
        record.user_id,
        names.get(record.user_id or ""),
        record.source_name,
    ]
    return any(needle in value.lower() for value in haystack if value)
