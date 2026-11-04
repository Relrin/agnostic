"""Access roles (per instance) and the control-plane scopes org roles carry."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from agnostic_access.domain.scopes import ADMIN_SCOPE, PER_COMPONENT

ROLE_ID_PREFIX = "rol"
BINDING_ID_PREFIX = "bnd"

type RunScope = Literal["all"] | tuple[str, ...]
type PrincipalKind = Literal["user", "group", "service_account"]


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
        return (
            frozenset({"org:read", "os:read", "org:members:read", "org:roles:read", "settings:read", "assistant:use"})
            & every
        )
    return frozenset()


def implicit_full_access(org_role: str | None, require_explicit_bindings: bool) -> bool:
    return org_role in {"owner", "administrator"} and not require_explicit_bindings


@dataclass(frozen=True, slots=True)
class Binding:
    id: str
    principal_kind: PrincipalKind
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


MAX_ROLE_NAME = 80
_SLUG = re.compile(r"[^a-z0-9]+")


class InvalidRoleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RoleDraft:
    """What the role editor saves; the server derives the scopes."""

    name: str
    description: str
    color: str
    permissions: Mapping[str, tuple[str, ...]]
    run_scope: Mapping[str, RunScope] = field(default_factory=dict[str, RunScope])
    bindable_instance_ids: tuple[str, ...] | None = None


def role_slug(name: str) -> str:
    slug = _SLUG.sub("-", name.lower()).strip("-")[:63]
    if not slug:
        raise InvalidRoleError("A role needs a name with at least one letter or digit.")
    return slug


def check_draft(draft: RoleDraft, *, catalogued: Callable[[str], bool]) -> RoleDraft:
    """Normalise a draft and reject cells the scope catalog doesn't have (``catalogued("knowledge:write")``)."""
    name = " ".join(draft.name.split())
    if not name:
        raise InvalidRoleError("A role needs a name.")
    if len(name) > MAX_ROLE_NAME:
        raise InvalidRoleError(f"Use at most {MAX_ROLE_NAME} characters for the role name.")
    permissions: dict[str, tuple[str, ...]] = {}
    unknown: list[str] = []
    for resource, actions in draft.permissions.items():
        kept = tuple(dict.fromkeys(action for action in actions if action))
        unknown.extend(f"{resource}:{action}" for action in kept if not catalogued(f"{resource}:{action}"))
        if kept:
            permissions[resource] = kept
    if unknown:
        raise InvalidRoleError(f"Not in the scope catalog: {', '.join(sorted(unknown))}.")
    if not permissions:
        raise InvalidRoleError("A role needs at least one permission.")
    run_scope = _check_run_scope(draft.run_scope, permissions)
    bindable = tuple(dict.fromkeys(draft.bindable_instance_ids)) if draft.bindable_instance_ids is not None else None
    if bindable is not None and not bindable:
        raise InvalidRoleError("A role must be bindable on at least one instance.")
    return replace(
        draft,
        name=name,
        description=draft.description.strip(),
        permissions=permissions,
        run_scope=run_scope,
        bindable_instance_ids=bindable,
    )


def _check_run_scope(
    run_scope: Mapping[str, RunScope], permissions: Mapping[str, tuple[str, ...]]
) -> dict[str, RunScope]:
    checked: dict[str, RunScope] = {}
    for resource, selected in run_scope.items():
        if resource not in PER_COMPONENT:
            raise InvalidRoleError(f"Run scope can only narrow {', '.join(sorted(PER_COMPONENT))}.")
        if selected == "all":
            continue
        if "run" not in permissions.get(resource, ()):
            raise InvalidRoleError(f"Selected {resource} only make sense when the role can run {resource}.")
        ids = tuple(dict.fromkeys(item.strip() for item in selected if item.strip()))
        if not ids:
            raise InvalidRoleError(f"Pick at least one of the {resource}, or let the role run all of them.")
        checked[resource] = ids
    return checked


def apply_draft(role: AccessRole, draft: RoleDraft) -> AccessRole:
    return replace(
        role,
        name=draft.name,
        description=draft.description,
        color=draft.color,
        permissions=draft.permissions,
        run_scope=draft.run_scope,
        bindable_instance_ids=draft.bindable_instance_ids,
    )


@dataclass(frozen=True, slots=True)
class ScopeDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.added and not self.removed

    def lines(self) -> list[dict[str, str]]:
        return [{"op": "add", "text": scope} for scope in self.added] + [
            {"op": "remove", "text": scope} for scope in self.removed
        ]


def scope_diff(before: Iterable[str], after: Iterable[str]) -> ScopeDiff:
    old, new = frozenset(before), frozenset(after)
    return ScopeDiff(added=tuple(sorted(new - old)), removed=tuple(sorted(old - new)))


@dataclass(frozen=True, slots=True)
class RoleVersion:
    role_id: str
    version: int
    snapshot: Mapping[str, object]
    changed_by: str
    changed_by_name: str
    changed_at: datetime


def role_snapshot(role: AccessRole) -> dict[str, object]:
    """What ``access_role_versions`` keeps for each saved version."""
    return {
        "name": role.name,
        "description": role.description,
        "color": role.color,
        "permissions": {resource: list(actions) for resource, actions in role.permissions.items()},
        "run_scope": {resource: value if value == "all" else list(value) for resource, value in role.run_scope.items()},
        "bindable_instance_ids": list(role.bindable_instance_ids) if role.bindable_instance_ids is not None else None,
        "scopes": sorted(role.scopes()),
    }


def compare_versions(installed: str | None, minimum: str | None) -> bool:
    """Whether an AgentOS version (``"3.1.12"``) is at least ``minimum``; unknown versions pass."""
    if not installed or not minimum:
        return True

    def parts(version: str) -> tuple[int, ...]:
        numbers: list[int] = []
        for piece in version.split("."):
            digits = "".join(char for char in piece if char.isdigit())
            numbers.append(int(digits) if digits else 0)
        return tuple(numbers)

    return parts(installed) >= parts(minimum)


__all__ = ["ADMIN_SCOPE"]
