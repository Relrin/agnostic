"""Access roles (per instance) and the control-plane scopes org roles carry."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from agnostic_access.domain.scopes import ADMIN_SCOPE

ROLE_ID_PREFIX = "rol"
BINDING_ID_PREFIX = "bnd"

type RunScope = Literal["all"] | tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AccessRole:
    id: str
    slug: str
    name: str
    description: str
    color: str
    kind: Literal["built_in", "custom"]
    permissions: Mapping[str, tuple[str, ...]]
    """``{resource: (actions)}``, the role editor's matrix (design spec B §9.2)."""
    run_scope: Mapping[str, RunScope] = field(default_factory=dict[str, RunScope])
    """``{"agents": ("support-triage",)}`` replaces ``agents:run`` with per-agent run scopes."""
    bindable_instance_ids: tuple[str, ...] | None = None
    """Instances the role may be bound on; ``None`` means all."""
    version: int = 1

    def scopes(self) -> frozenset[str]:
        result: set[str] = set()
        for resource, actions in self.permissions.items():
            for action in actions:
                selected = self.run_scope.get(resource, "all")
                if action == "run" and selected != "all":
                    result.update(f"{resource}:{component}:run" for component in selected)
                else:
                    result.add(f"{resource}:{action}")
        return frozenset(result)

    def bindable_on(self, instance_id: str) -> bool:
        return self.bindable_instance_ids is None or instance_id in self.bindable_instance_ids


def _role(slug: str, name: str, description: str, color: str, permissions: Mapping[str, Sequence[str]]) -> AccessRole:
    return AccessRole(
        id=f"{ROLE_ID_PREFIX}_{slug.replace('-', '_')}",
        slug=slug,
        name=name,
        description=description,
        color=color,
        kind="built_in",
        permissions={resource: tuple(actions) for resource, actions in permissions.items()},
    )


_READ = ("read",)
_RW = ("read", "write")
_RWD = ("read", "write", "delete")

BUILT_IN_ROLES: tuple[AccessRole, ...] = (
    _role(
        "instance-admin",
        "Instance admin",
        "Everything on the instance, including other people's sessions and the queue.",
        "#C5F25C",
        {"agent_os": ("admin",), "queue": ("operate",)},
    ),
    _role(
        "operator",
        "Operator",
        "Runs and supervises live agents. Can resolve approvals; can't change definitions.",
        "#C5F25C",
        {
            "agents": ("read", "run"),
            "teams": ("read", "run"),
            "workflows": ("read", "run"),
            "components": _READ,
            "registry": _READ,
            "sessions": _READ,
            "memories": _READ,
            "learnings": _READ,
            "knowledge": _READ,
            "traces": _READ,
            "metrics": _READ,
            "evals": _READ,
            "approvals": _RWD,
            "schedules": _RW,
            "config": _READ,
            "queue": ("operate",),
        },
    ),
    _role(
        "builder",
        "Builder",
        "Builds and tests agents, teams and workflows in Studio; manages knowledge and evaluations.",
        "#7DA6FF",
        {
            "agents": ("read", "run", "write"),
            "teams": ("read", "run", "write"),
            "workflows": ("read", "run", "write"),
            "components": _RWD,
            "registry": _READ,
            "filesystem": _READ,
            "sessions": _RW,
            "memories": _RW,
            "learnings": _RW,
            "knowledge": _RWD,
            "traces": _READ,
            "metrics": _READ,
            "evals": _RWD,
            "approvals": _READ,
            "schedules": _RW,
            "config": _READ,
        },
    ),
    _role(
        "viewer",
        "Viewer",
        "Read-only: sees agents, runs, traces, metrics and context, changes nothing.",
        "#A9AFB8",
        dict.fromkeys(
            (
                "agents",
                "teams",
                "workflows",
                "components",
                "registry",
                "filesystem",
                "sessions",
                "memories",
                "learnings",
                "knowledge",
                "traces",
                "metrics",
                "evals",
                "approvals",
                "schedules",
                "config",
            ),
            _READ,
        ),
    ),
    _role(
        "auditor",
        "Auditor",
        "Reads the audit log and what happened on instances: traces, sessions, approvals.",
        "#B79CFF",
        {
            "audit": _READ,
            "traces": _READ,
            "sessions": _READ,
            "approvals": _READ,
            "metrics": _READ,
            "evals": _READ,
            "config": _READ,
        },
    ),
)

BUILT_IN_BY_ID: Mapping[str, AccessRole] = {role.id: role for role in BUILT_IN_ROLES}
FULL_ACCESS = "Full access"
"""The implicit binding Owners and Administrators have on every instance (unless explicit bindings are required)."""


def org_role_scopes(org_role: str, control_plane_scopes: Iterable[str]) -> frozenset[str]:
    """Control-plane scopes carried by an org role."""
    every = frozenset(control_plane_scopes)
    if org_role == "owner":
        return every
    if org_role == "administrator":
        return every - {"os:delete", "os:keys:rotate", "org:delete"}
    if org_role == "member":
        return frozenset({"org:read", "os:read", "org:members:read", "org:roles:read", "settings:read"}) & every
    return frozenset()


def implicit_full_access(org_role: str | None, require_explicit_bindings: bool) -> bool:
    return org_role in {"owner", "administrator"} and not require_explicit_bindings


@dataclass(frozen=True, slots=True)
class Binding:
    id: str
    principal_kind: Literal["user", "group", "service_account"]
    principal_id: str
    instance_id: str | None
    role_id: str | None
    scopes: tuple[str, ...]
    expires_at: datetime | None
    reason: str | None
    created_by: str
    created_at: datetime

    def active(self, now: datetime) -> bool:
        return self.expires_at is None or self.expires_at > now

    def applies_to(self, instance_id: str | None) -> bool:
        return self.instance_id is None or self.instance_id == instance_id


__all__ = ["ADMIN_SCOPE"]
