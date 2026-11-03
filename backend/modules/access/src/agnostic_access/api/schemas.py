"""Request and response bodies of ``/api/v1/access`` and ``/api/v1/me/access``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, cast

from pydantic import AwareDatetime, BaseModel, Field

from agnostic_access.application.requests import RequestView
from agnostic_access.application.roles import RolePreview
from agnostic_access.application.use_cases import MyAccess, RoleReach, RoleView
from agnostic_access.domain.effective import Explanation, Grant
from agnostic_access.domain.requests import AccessRequest
from agnostic_access.domain.roles import AccessRole, Binding, RoleDraft, RoleVersion, RunScope
from agnostic_access.domain.scopes import ScopeSpec


def _run_scope(run_scope: Mapping[str, RunScope]) -> dict[str, list[str] | Literal["all"]]:
    result: dict[str, list[str] | Literal["all"]] = {}
    for resource, value in run_scope.items():
        result[resource] = "all" if value == "all" else list(value)
    return result


class RoleOut(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    color: str
    kind: Literal["built_in", "custom"]
    permissions: dict[str, list[str]]
    run_scope: dict[str, list[str] | Literal["all"]]
    bindable_instance_ids: list[str] | None
    scopes: list[str]
    people: int = Field(description="People who hold the role, directly or through a group")
    groups: int = 0
    service_accounts: int = 0
    version: int

    @classmethod
    def from_view(cls, view: RoleView) -> RoleOut:
        return cls.from_role(view.role, view.people, view.groups, view.service_accounts)

    @classmethod
    def from_role(cls, role: AccessRole, people: int = 0, groups: int = 0, service_accounts: int = 0) -> RoleOut:
        return cls(
            id=role.id,
            slug=role.slug,
            name=role.name,
            description=role.description,
            color=role.color,
            kind=role.kind,
            permissions={resource: list(actions) for resource, actions in role.permissions.items()},
            run_scope=_run_scope(role.run_scope),
            bindable_instance_ids=list(role.bindable_instance_ids) if role.bindable_instance_ids is not None else None,
            scopes=sorted(role.scopes()),
            people=people,
            groups=groups,
            service_accounts=service_accounts,
            version=role.version,
        )


class RoleIn(BaseModel):
    """The role editor's draft; the server derives the token scopes."""

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    color: str = Field(default="#A9AFB8", max_length=20, pattern=r"^#[0-9A-Fa-f]{6}$")
    permissions: dict[str, list[str]] = Field(examples=[{"agents": ["read", "run"], "knowledge": ["read", "write"]}])
    run_scope: dict[str, list[str] | Literal["all"]] = Field(
        default_factory=dict[str, list[str] | Literal["all"]], examples=[{"agents": ["support-triage"]}]
    )
    bindable_instance_ids: list[str] | None = Field(default=None, description="null: bindable on every instance")

    def draft(self) -> RoleDraft:
        run_scope: dict[str, RunScope] = {
            resource: "all" if value == "all" else tuple(value) for resource, value in self.run_scope.items()
        }
        return RoleDraft(
            name=self.name,
            description=self.description,
            color=self.color,
            permissions={resource: tuple(actions) for resource, actions in self.permissions.items()},
            run_scope=run_scope,
            bindable_instance_ids=tuple(self.bindable_instance_ids) if self.bindable_instance_ids is not None else None,
        )


class RoleUpdate(RoleIn):
    version: int = Field(description="The version you edited; a newer saved version is a conflict")


class RoleDuplicate(BaseModel):
    name: str | None = Field(default=None, max_length=80)


class DiffLineOut(BaseModel):
    op: Literal["add", "remove"]
    text: str


class GroupRefOut(BaseModel):
    id: str
    name: str


class ReachOut(BaseModel):
    people: int
    direct_people: list[str]
    groups: list[GroupRefOut]
    service_accounts: list[str]
    sentence: str = Field(description='"9 people and 2 groups (Support AI, Billing ops)"')

    @classmethod
    def from_reach(cls, reach: RoleReach) -> ReachOut:
        people = len(reach.people)
        parts = [f"{people} {'person' if people == 1 else 'people'}"]
        if reach.groups:
            plural = "s" if len(reach.groups) != 1 else ""
            parts.append(f"{len(reach.groups)} group{plural} ({', '.join(name for _, name in reach.groups)})")
        if reach.service_accounts:
            count = len(reach.service_accounts)
            parts.append(f"{count} service account{'s' if count != 1 else ''}")
        return cls(
            people=people,
            direct_people=sorted(reach.direct),
            groups=[GroupRefOut(id=group_id, name=name) for group_id, name in reach.groups],
            service_accounts=sorted(reach.service_accounts),
            sentence=" and ".join(parts),
        )


class RolePreviewOut(BaseModel):
    role: RoleOut
    added: list[str]
    removed: list[str]
    lines: list[DiffLineOut]
    reach: ReachOut
    warnings: list[str]
    redeploy: bool = Field(default=False, description="Always false: new scopes apply on the next request")

    @classmethod
    def from_preview(cls, preview: RolePreview) -> RolePreviewOut:
        reach = ReachOut.from_reach(preview.reach)
        return cls(
            role=RoleOut.from_role(
                preview.role, reach.people, len(preview.reach.groups), len(preview.reach.service_accounts)
            ),
            added=list(preview.diff.added),
            removed=list(preview.diff.removed),
            lines=[DiffLineOut(op="add", text=scope) for scope in preview.diff.added]
            + [DiffLineOut(op="remove", text=scope) for scope in preview.diff.removed],
            reach=reach,
            warnings=list(preview.warnings),
        )


class RoleVersionOut(BaseModel):
    version: int
    name: str
    scopes: list[str]
    changed_by: str
    changed_by_name: str
    changed_at: datetime

    @classmethod
    def from_domain(cls, version: RoleVersion) -> RoleVersionOut:
        scopes = version.snapshot.get("scopes")
        name = version.snapshot.get("name")
        return cls(
            version=version.version,
            name=str(name) if name else "",
            scopes=[str(scope) for scope in cast("list[object]", scopes)] if isinstance(scopes, list) else [],
            changed_by=version.changed_by,
            changed_by_name=version.changed_by_name,
            changed_at=version.changed_at,
        )


class ScopeOut(BaseModel):
    scope: str
    family: str
    action: str
    source: Literal["agentos", "control_plane"]
    resource_kind: Literal["global", "per_component"]
    description: str
    privileged: bool
    hidden: bool
    agentos_min_version: str | None = None

    @classmethod
    def from_spec(cls, spec: ScopeSpec) -> ScopeOut:
        return cls(
            scope=spec.scope,
            family=spec.family,
            action=spec.action,
            source=spec.source,
            resource_kind=spec.resource_kind,
            description=spec.description,
            privileged=spec.privileged,
            hidden=spec.hidden,
            agentos_min_version=spec.agentos_min_version,
        )


class BindingOut(BaseModel):
    id: str
    principal_kind: Literal["user", "group", "service_account"]
    principal_id: str
    instance_id: str | None
    role_id: str | None
    scopes: list[str]
    expires_at: datetime | None
    reason: str | None
    created_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, binding: Binding) -> BindingOut:
        return cls(
            id=binding.id,
            principal_kind=binding.principal_kind,
            principal_id=binding.principal_id,
            instance_id=binding.instance_id,
            role_id=binding.role_id,
            scopes=list(binding.scopes),
            expires_at=binding.expires_at,
            reason=binding.reason,
            created_by=binding.created_by,
            created_at=binding.created_at,
        )


class RoleHoldersOut(BaseModel):
    reach: ReachOut
    bindings: list[BindingOut]


class BindingCreate(BaseModel):
    user_id: str | None = Field(default=None, description="A person (usr_…); the same as principal_id for kind user")
    principal_kind: Literal["user", "group"] = "user"
    principal_id: str | None = Field(default=None, description="usr_… or grp_…")
    instance: str | None = Field(default=None, description="Instance id or slug; null binds on all instances")
    role_id: str | None = None
    scopes: list[str] = Field(default_factory=list[str], max_length=200, examples=[["agents:billing-agent:run"]])
    expires_at: AwareDatetime | None = None
    reason: str | None = Field(default=None, max_length=500)

    def principal(self) -> str | None:
        return self.principal_id or self.user_id


class GrantOut(BaseModel):
    scope: str
    source: Literal["org_role", "implicit", "binding"]
    role_id: str | None
    role_name: str
    binding_id: str | None
    instance_id: str | None
    expires_at: datetime | None
    via_group_id: str | None = None
    via_group_name: str | None = None

    @classmethod
    def from_domain(cls, grant: Grant) -> GrantOut:
        return cls(
            scope=grant.scope,
            source=grant.source,
            role_id=grant.role_id,
            role_name=grant.role_name,
            binding_id=grant.binding_id,
            instance_id=grant.instance_id,
            expires_at=grant.expires_at,
            via_group_id=grant.via_group_id,
            via_group_name=grant.via_group_name,
        )


class MyAccessOut(BaseModel):
    instance_id: str | None
    org_role: Literal["owner", "administrator", "member"] | None
    implicit_full_access: bool
    roles: list[str] = Field(description='Roles held on the instance as people see them ("Operator", "Full access")')
    token_scopes: list[str] = Field(description="What the gateway puts in this person's JWT for the instance")
    runtime_scopes: list[str]
    control_plane_scopes: list[str]
    grants: list[GrantOut]

    @classmethod
    def from_access(cls, mine: MyAccess) -> MyAccessOut:
        access = mine.access
        role = access.org_role if access.org_role in {"owner", "administrator", "member"} else None
        return cls(
            instance_id=mine.instance.id if mine.instance else None,
            org_role=role,  # pyright: ignore[reportArgumentType]
            implicit_full_access=access.implicit_full,
            roles=access.role_names(),
            token_scopes=mine.token_scopes,
            runtime_scopes=sorted(access.runtime_scopes()),
            control_plane_scopes=sorted(access.control_plane_scopes()),
            grants=[GrantOut.from_domain(grant) for grant in access.grants],
        )


class ExplainIn(BaseModel):
    user_id: str = Field(description="Whose access to explain: usr_…, or sac_… with principal_kind service_account")
    principal_kind: Literal["user", "service_account"] = "user"
    display_name: str | None = Field(default=None, description='How to call a service account ("sa:zendesk-bridge")')
    scope: str | None = Field(default=None, examples=["components:write"], description="Or resource + verb")
    resource: str | None = Field(default=None, examples=["agents"])
    verb: str | None = Field(default=None, examples=["run"])
    component: str | None = Field(default=None, examples=["billing-agent"], description="agents, teams, workflows")
    instance: str | None = Field(default=None, description="Instance id or slug (runtime scopes)")
    action: str | None = Field(default=None, description='What they tried, e.g. "Publish support-triage"')


class AlternativeOut(BaseModel):
    kind: Literal["role", "instance"]
    label: str
    role_name: str | None


class ExplanationOut(BaseModel):
    allowed: bool
    scope: str
    instance_id: str | None
    granted_by: list[GrantOut]
    missing_scopes: list[str]
    alternatives: list[AlternativeOut]
    explanation: str
    via_group: str | None = Field(default=None, description="The group whose binding decided it")
    can_request: bool = Field(default=False, description="Denied, and temporary access can be requested")

    @classmethod
    def from_domain(cls, explanation: Explanation, *, control_plane: bool = False) -> ExplanationOut:
        return cls(
            allowed=explanation.allowed,
            scope=explanation.scope,
            instance_id=explanation.instance_id,
            granted_by=[GrantOut.from_domain(grant) for grant in explanation.granted_by],
            missing_scopes=list(explanation.missing_scopes),
            alternatives=[
                AlternativeOut(kind=item.kind, label=item.label, role_name=item.role_name)
                for item in explanation.alternatives
            ],
            explanation=explanation.text,
            via_group=next((g.via_group_name for g in explanation.granted_by if g.via_group_name), None),
            can_request=not explanation.allowed and not control_plane,
        )


class AccessRequestIn(BaseModel):
    instance: str | None = Field(default=None, description="Instance id or slug; null asks for all instances")
    role_id: str | None = None
    scopes: list[str] = Field(default_factory=list[str], max_length=50)
    reason: str = Field(min_length=1, max_length=500)
    duration_hours: int = Field(default=8, ge=1, le=2160)


class TemporaryGrantIn(BaseModel):
    principal_kind: Literal["user", "group"] = "user"
    principal_id: str
    instance: str | None = None
    role_id: str | None = None
    scopes: list[str] = Field(default_factory=list[str], max_length=50)
    reason: str = Field(min_length=1, max_length=500)
    duration_hours: int = Field(ge=1, le=2160)


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class AccessRequestOut(BaseModel):
    id: str
    requester_id: str
    instance_id: str | None
    role_id: str | None
    scopes: list[str]
    reason: str
    duration_hours: int
    status: Literal["pending", "approved", "denied", "cancelled", "expired"]
    created_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    note: str | None
    binding_id: str | None
    expires_at: datetime | None
    can_decide: bool = False

    @classmethod
    def from_domain(cls, request: AccessRequest, *, can_decide: bool = False) -> AccessRequestOut:
        return cls(
            id=request.id,
            requester_id=request.requester_id,
            instance_id=request.instance_id,
            role_id=request.role_id,
            scopes=list(request.scopes),
            reason=request.reason,
            duration_hours=request.duration_hours,
            status=request.status,
            created_at=request.created_at,
            decided_by=request.decided_by,
            decided_at=request.decided_at,
            note=request.note,
            binding_id=request.binding_id,
            expires_at=request.expires_at,
            can_decide=can_decide,
        )

    @classmethod
    def from_view(cls, view: RequestView) -> AccessRequestOut:
        return cls.from_domain(view.request, can_decide=view.can_decide)
