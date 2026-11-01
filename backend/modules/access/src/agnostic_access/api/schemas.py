"""Request and response bodies of ``/api/v1/access`` and ``/api/v1/me/access``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from agnostic_access.application.use_cases import MyAccess, RoleView
from agnostic_access.domain.effective import Explanation, Grant
from agnostic_access.domain.roles import Binding, RunScope
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
    people: int
    version: int

    @classmethod
    def from_view(cls, view: RoleView) -> RoleOut:
        role = view.role
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
            people=view.people,
            version=role.version,
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


class BindingCreate(BaseModel):
    user_id: str
    instance: str | None = Field(default=None, description="Instance id or slug; null binds on all instances")
    role_id: str | None = None
    scopes: list[str] = Field(default_factory=list[str], max_length=200, examples=[["agents:billing-agent:run"]])
    expires_at: AwareDatetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class GrantOut(BaseModel):
    scope: str
    source: Literal["org_role", "implicit", "binding"]
    role_id: str | None
    role_name: str
    binding_id: str | None
    instance_id: str | None
    expires_at: datetime | None

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
    user_id: str = Field(description="Whose access to explain (usr_…)")
    scope: str = Field(examples=["components:write"])
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

    @classmethod
    def from_domain(cls, explanation: Explanation) -> ExplanationOut:
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
        )
