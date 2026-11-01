"""Effective access of a person on an instance, and the explanation of a decision.

Effective scopes for (user, instance) are the union of direct bindings (on the instance or on all instances, for
roles bindable there, not expired), the implicit "Full access" of Owners and Administrators (unless the org requires
explicit bindings), plus the control-plane scopes of the org role. No deny rules.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agnostic_access.domain.roles import FULL_ACCESS, AccessRole, Binding, implicit_full_access, org_role_scopes
from agnostic_access.domain.scopes import ADMIN_SCOPE, satisfies

ORG_ROLE_NAMES = {"owner": "Owner", "administrator": "Administrator", "member": "Member"}


@dataclass(frozen=True, slots=True)
class Grant:
    scope: str
    source: Literal["org_role", "implicit", "binding"]
    role_id: str | None
    role_name: str
    binding_id: str | None = None
    instance_id: str | None = None
    """``None``: the grant applies on all instances."""
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EffectiveAccess:
    user_id: str
    org_role: str | None
    instance_id: str | None
    implicit_full: bool
    grants: tuple[Grant, ...]
    control_plane: frozenset[str]
    """Which scopes in ``grants`` are control-plane scopes (never sent to AgentOS)."""

    def runtime_scopes(self) -> frozenset[str]:
        return frozenset(g.scope for g in self.grants if g.scope not in self.control_plane)

    def control_plane_scopes(self) -> frozenset[str]:
        return frozenset(g.scope for g in self.grants if g.scope in self.control_plane)

    def find(self, required: str, *, control_plane: bool) -> list[Grant]:
        pool = [g for g in self.grants if (g.scope in self.control_plane) == control_plane]
        matches = [g for g in pool if satisfies(g.scope, required, control_plane=control_plane)]
        return sorted(matches, key=lambda g: (g.scope == ADMIN_SCOPE, g.scope != required, g.source != "binding"))

    def role_names(self) -> list[str]:
        """Roles held on this instance, as people see them ("Operator", "Full access")."""
        names: list[str] = []
        for grant in self.grants:
            if grant.source in {"binding", "implicit"} and grant.role_name not in names:
                names.append(grant.role_name)
        return names


def compute_access(
    *,
    user_id: str,
    org_role: str | None,
    instance_id: str | None,
    bindings: Iterable[Binding],
    roles: Mapping[str, AccessRole],
    require_explicit_bindings: bool,
    control_plane_scopes: Iterable[str],
    now: datetime,
) -> EffectiveAccess:
    cp = frozenset(control_plane_scopes)
    grants: list[Grant] = []
    if org_role is not None:
        name = ORG_ROLE_NAMES.get(org_role, org_role)
        grants.extend(
            Grant(scope=scope, source="org_role", role_id=None, role_name=name)
            for scope in sorted(org_role_scopes(org_role, cp))
        )
    implicit = implicit_full_access(org_role, require_explicit_bindings)
    if implicit and instance_id is not None:
        grants.append(Grant(scope=ADMIN_SCOPE, source="implicit", role_id=None, role_name=FULL_ACCESS))

    if org_role is not None:
        for binding in bindings:
            if not binding.active(now):
                continue
            if instance_id is None and binding.instance_id is not None:
                continue
            if not binding.applies_to(instance_id):
                continue
            role = roles.get(binding.role_id) if binding.role_id else None
            if role is not None and instance_id is not None and not role.bindable_on(instance_id):
                continue
            scopes = set(binding.scopes) | (set(role.scopes()) if role else set[str]())
            label = role.name if role else "Direct grant"
            grants.extend(
                Grant(
                    scope=scope,
                    source="binding",
                    role_id=role.id if role else None,
                    role_name=label,
                    binding_id=binding.id,
                    instance_id=binding.instance_id,
                    expires_at=binding.expires_at,
                )
                for scope in sorted(scopes)
            )
    return EffectiveAccess(
        user_id=user_id,
        org_role=org_role,
        instance_id=instance_id,
        implicit_full=implicit,
        grants=tuple(grants),
        control_plane=cp,
    )


@dataclass(frozen=True, slots=True)
class Alternative:
    kind: Literal["role", "instance"]
    label: str
    role_name: str | None = None


@dataclass(frozen=True, slots=True)
class Explanation:
    allowed: bool
    scope: str
    instance_id: str | None
    granted_by: tuple[Grant, ...]
    missing_scopes: tuple[str, ...]
    alternatives: tuple[Alternative, ...]
    text: str


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def explain(
    required: str,
    access: EffectiveAccess,
    *,
    who: str,
    instance_label: str | None,
    action_label: str | None,
    roles: Iterable[AccessRole],
    elsewhere: Mapping[str, EffectiveAccess],
    is_control_plane: Callable[[str], bool],
) -> Explanation:
    control_plane = is_control_plane(required)
    granted = access.find(required, control_plane=control_plane)
    where = f" on {instance_label}" if instance_label and not control_plane else ""
    subject = action_label or "This"
    if granted:
        grant = granted[0]
        if grant.source == "implicit":
            text = f"{who} has {FULL_ACCESS}{where} as {ORG_ROLE_NAMES.get(access.org_role or '', '')}."
        elif grant.source == "org_role":
            text = f"Granted by {who}'s org role {grant.role_name} → `{grant.scope}`."
        else:
            text = f"Granted by {grant.role_name} → `{grant.scope}`{where}."
        return Explanation(
            allowed=True,
            scope=required,
            instance_id=access.instance_id,
            granted_by=tuple(granted),
            missing_scopes=(),
            alternatives=(),
            text=text,
        )

    if control_plane:
        org = ORG_ROLE_NAMES.get(access.org_role or "", "not a member")
        holders = [
            ORG_ROLE_NAMES[name]
            for name in ("owner", "administrator", "member")
            if required in org_role_scopes(name, access.control_plane)
        ]
        text = f"{subject} needs `{required}`. {who} is {org}, which doesn't include it."
        if holders:
            text += f" {_join(holders)}s have it."
        alternatives = tuple(Alternative("role", name) for name in holders)
        return Explanation(
            allowed=False,
            scope=required,
            instance_id=access.instance_id,
            granted_by=(),
            missing_scopes=(required,),
            alternatives=alternatives,
            text=text,
        )

    held = access.role_names()
    if held:
        verb = "doesn't" if len(held) == 1 else "don't"
        text = f"{subject} needs `{required}`{where}. {who} has {_join(held)} there, which {verb} include it."
    else:
        text = f"{subject} needs `{required}`{where}. {who} has no access there."

    including = [
        role.name
        for role in roles
        if any(satisfies(scope, required) for scope in role.scopes()) and role.name not in held
    ]
    other = [
        (label, other_access.find(required, control_plane=False)[0].role_name)
        for label, other_access in elsewhere.items()
        if other_access.find(required, control_plane=False)
    ]
    alternatives = tuple(
        [Alternative("instance", label, role_name) for label, role_name in other]
        + [Alternative("role", name) for name in including]
    )
    if other:
        text += " " + "; ".join(f"{role_name} has it on {label}" for label, role_name in other) + "."
    elif including:
        text += f" {_join(including)} {'includes' if len(including) == 1 else 'include'} it."
    return Explanation(
        allowed=False,
        scope=required,
        instance_id=access.instance_id,
        granted_by=(),
        missing_scopes=(required,),
        alternatives=alternatives,
        text=text,
    )
