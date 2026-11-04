"""The scope vocabulary and how scopes satisfy each other.

AgentOS scopes are sent to runtimes in JWTs; control-plane scopes are enforced by Agnostic and
never leave it. Matching follows AgentOS ``scopes.py``: ``agent_os:admin`` passes every AgentOS check, a global
``agents:run`` covers ``agents:<id>:run``, ``agents:*:run`` is the same as global, and ``system:*`` is a legacy alias
of ``config:*``. There are no action wildcards and no deny rules.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

ADMIN_SCOPE = "agent_os:admin"
PER_COMPONENT = frozenset({"agents", "teams", "workflows"})
LEGACY_ALIASES: Mapping[str, str] = {"system": "config"}

type Source = Literal["agentos", "control_plane"]


@dataclass(frozen=True, slots=True)
class ScopeSpec:
    scope: str
    family: str
    action: str
    source: Source
    description: str
    resource_kind: Literal["global", "per_component"] = "global"
    privileged: bool = False
    agentos_min_version: str | None = None
    hidden: bool = False


def _agentos(family: str, actions: Iterable[str], label: str, *, hidden: bool = False) -> list[ScopeSpec]:
    verbs = {"read": "See", "write": "Create and change", "delete": "Delete", "run": "Run"}
    return [
        ScopeSpec(
            scope=f"{family}:{action}",
            family=family,
            action=action,
            source="agentos",
            description=f"{verbs.get(action, action.title())} {label}",
            resource_kind="per_component" if family in PER_COMPONENT else "global",
            privileged=action in {"write", "delete"},
            agentos_min_version="3.1.0",
            hidden=hidden,
        )
        for action in actions
    ]


AGENTOS_SCOPES: tuple[ScopeSpec, ...] = (
    ScopeSpec(
        ADMIN_SCOPE, "agent_os", "admin", "agentos", "Everything on the instance, past user isolation", privileged=True
    ),
    *_agentos("config", ("read", "write"), "the OS configuration (write: database migrations)"),
    *_agentos("registry", ("read",), "the code-defined registry"),
    *_agentos("filesystem", ("read",), "agent file systems"),
    *_agentos("components", ("read", "write", "delete"), "Studio components and versions"),
    *_agentos("agents", ("read", "run", "write", "delete"), "agents"),
    *_agentos("teams", ("read", "run", "write", "delete"), "agent teams"),
    *_agentos("workflows", ("read", "run", "write", "delete"), "workflows"),
    *_agentos("sessions", ("read", "write", "delete"), "sessions"),
    *_agentos("memories", ("read", "write", "delete"), "memories"),
    *_agentos("learnings", ("read", "write", "delete"), "learnings"),
    *_agentos("knowledge", ("read", "write", "delete"), "knowledge"),
    *_agentos("traces", ("read",), "traces"),
    *_agentos("metrics", ("read", "write"), "metrics (write: refresh)"),
    *_agentos("evals", ("read", "write", "delete"), "evaluation runs"),
    *_agentos("schedules", ("read", "write", "delete"), "schedules"),
    *_agentos("approvals", ("read", "write", "delete"), "approvals"),
    *_agentos("service_accounts", ("read", "write", "delete"), "native service accounts"),
    *(
        spec
        for family in ("products", "projects", "tasks", "sources", "routines")
        for spec in _agentos(family, ("read", "write", "delete"), f"Company {family}", hidden=True)
    ),
    *_agentos("wiki", ("read", "write"), "the Company wiki", hidden=True),
    *_agentos("decisions", ("read", "write"), "Company decisions", hidden=True),
)

CONTROL_PLANE_EXTRA: tuple[tuple[str, str], ...] = (
    ("service_accounts:manage", "Manage org service accounts"),
    ("studio:promote", "Promote components between instances"),
    ("evals:gates:write", "Change publish gates"),
    ("queue:operate", "Requeue and resume queued runs"),
)
"""Control-plane scopes named in whose modules arrive in later phases."""


def split(scope: str) -> tuple[str, str | None, str]:
    """Split a scope into ``(resource, middle, action)``, e.g. ``agents:triage:run`` → agents, triage, run."""
    parts = scope.split(":")
    if len(parts) == 2:  # noqa: PLR2004
        resource, action = parts
        return LEGACY_ALIASES.get(resource, resource), None, action
    if len(parts) == 3:  # noqa: PLR2004
        resource, middle, action = parts
        return LEGACY_ALIASES.get(resource, resource), middle, action
    return scope, None, ""


def satisfies(held: str, required: str, *, control_plane: bool = False) -> bool:
    """Whether holding ``held`` passes a check for ``required``."""
    if held == required:
        return True
    if not control_plane and held == ADMIN_SCOPE:
        return True
    h_resource, h_id, h_action = split(held)
    r_resource, r_id, r_action = split(required)
    if (h_resource, h_action) != (r_resource, r_action):
        return False
    if control_plane or r_resource not in PER_COMPONENT:
        return h_id == r_id
    if r_id is None or r_id == "*":
        return h_id is None or h_id == "*"
    return h_id in {None, "*", r_id}


def granting(held: Iterable[str], required: str, *, control_plane: bool = False) -> str | None:
    """The held scope that grants ``required`` (the most specific one wins in explanations)."""
    matches = [scope for scope in held if satisfies(scope, required, control_plane=control_plane)]
    if not matches:
        return None
    return min(matches, key=lambda scope: (scope == ADMIN_SCOPE, scope != required))


def compress(scopes: Iterable[str]) -> list[str]:
    """Drop scopes another scope in the set already covers (06 §3.4); keeps tokens small, never widens access."""
    unique = set(scopes)
    if ADMIN_SCOPE in unique:
        return [ADMIN_SCOPE]
    kept = [
        scope
        for scope in unique
        if not any(other != scope and satisfies(other, scope) for other in unique if split(other)[1] is None)
    ]
    return sorted(kept)
