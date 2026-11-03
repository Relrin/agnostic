"""Request and response bodies of ``/api/v1/directory``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agnostic_directory.application.admin import IssuedToken, RuleView, ScimStatus
from agnostic_directory.application.google import GoogleView
from agnostic_directory.application.groups import GroupDetail, MemberView
from agnostic_directory.domain.groups import Group
from agnostic_directory.domain.sync import ScimToken
from agnostic_kernel.db import utcnow

type GroupSourceOut = Literal["manual", "scim", "oidc_claim", "google_directory"]


class GroupOut(BaseModel):
    id: str
    name: str
    description: str
    source: GroupSourceOut
    external_id: str | None
    external_name: str | None
    sync_label: str = Field(description='"Manual" or where the members come from, e.g. "SCIM · support-ai"')
    synced: bool
    member_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, group: Group) -> GroupOut:
        return cls(
            id=group.id,
            name=group.name,
            description=group.description,
            source=group.source,
            external_id=group.external_id,
            external_name=group.external_name,
            sync_label=group.sync_label(),
            synced=group.synced,
            member_count=group.member_count,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )


class GroupMemberOut(BaseModel):
    user_id: str
    display_name: str
    email: str
    role: Literal["member", "owner"]
    source: GroupSourceOut

    @classmethod
    def from_view(cls, view: MemberView) -> GroupMemberOut:
        return cls(
            user_id=view.user_id,
            display_name=view.display_name,
            email=view.email,
            role=view.role,
            source=view.source,
        )


class GroupDetailOut(GroupOut):
    members: list[GroupMemberOut]

    @classmethod
    def from_detail(cls, detail: GroupDetail) -> GroupDetailOut:
        base = GroupOut.from_domain(detail.group)
        return cls(**base.model_dump(), members=[GroupMemberOut.from_view(view) for view in detail.members])


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, examples=["Support AI"])
    description: str = Field(default="", max_length=500)
    member_ids: list[str] = Field(default_factory=list[str], max_length=500)
    owner_ids: list[str] = Field(default_factory=list[str], max_length=50)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)


class GroupMemberIn(BaseModel):
    role: Literal["member", "owner"] = "member"


class ScimTokenOut(BaseModel):
    id: str
    label: str = Field(description='Shown as the actor of what the IdP does, e.g. "Okta SCIM"')
    prefix: str = Field(description="The first characters of the token, to tell tokens apart")
    state: Literal["active", "rotating", "expired", "revoked"]
    created_by: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None = Field(description="When a token being rotated stops working")
    rotated_from: str | None

    @classmethod
    def from_domain(cls, token: ScimToken) -> ScimTokenOut:
        return cls(
            id=token.id,
            label=token.label,
            prefix=token.prefix,
            state=token.state(utcnow()),
            created_by=token.created_by,
            created_at=token.created_at,
            last_used_at=token.last_used_at,
            expires_at=token.expires_at,
            rotated_from=token.rotated_from,
        )


class IssuedScimTokenOut(BaseModel):
    token: ScimTokenOut
    secret: str = Field(description="The bearer token for the IdP; shown only now")

    @classmethod
    def from_issued(cls, issued: IssuedToken) -> IssuedScimTokenOut:
        return cls(token=ScimTokenOut.from_domain(issued.token), secret=issued.secret)


class ScimTokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=60, examples=["Okta SCIM"])


class ScimStatusOut(BaseModel):
    endpoint_url: str = Field(description="The SCIM base URL to configure at the IdP")
    healthy: bool
    last_request_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    counts: dict[str, int]
    tokens: list[ScimTokenOut]

    @classmethod
    def from_status(cls, status: ScimStatus) -> ScimStatusOut:
        return cls(
            endpoint_url=status.endpoint_url,
            healthy=status.state.healthy,
            last_request_at=status.state.last_request_at,
            last_error=status.state.last_error,
            last_error_at=status.state.last_error_at,
            counts=status.state.counts,
            tokens=[ScimTokenOut.from_domain(token) for token in status.tokens],
        )


type RuleSourceOut = Literal["scim", "oidc_claim", "google_directory"]


class MappingRuleOut(BaseModel):
    id: str
    source: RuleSourceOut
    provider_id: str | None
    idp_group: str
    group_id: str
    group_name: str
    created_by: str
    created_at: datetime

    @classmethod
    def from_view(cls, view: RuleView) -> MappingRuleOut:
        rule = view.rule
        return cls(
            id=rule.id,
            source=rule.source,
            provider_id=rule.provider_id,
            idp_group=rule.idp_group,
            group_id=rule.group_id,
            group_name=view.group_name,
            created_by=rule.created_by,
            created_at=rule.created_at,
        )


class MappingRuleCreate(BaseModel):
    source: RuleSourceOut
    idp_group: str = Field(
        min_length=1, max_length=200, description="The IdP group's name or id", examples=["support-ai"]
    )
    group_id: str = Field(description="The manual group its members are added to")
    provider_id: str | None = Field(default=None, max_length=64, description="Claim rules only: the sign-in provider")


class DirectorySettingsOut(BaseModel):
    deprovision: Literal["disable", "remove"] = Field(
        description="disable: deprovision the account and keep the org membership; remove: also leave the org"
    )


class DirectorySettingsIn(BaseModel):
    deprovision: Literal["disable", "remove"]


class GoogleSyncOut(BaseModel):
    configured: bool
    client_email: str | None = Field(description="The service account (its key is never returned)")
    admin_subject: str | None
    customer_id: str | None
    group_filter: list[str]
    enabled: bool
    last_run_at: datetime | None
    last_error: str | None
    counts: dict[str, int]

    @classmethod
    def from_view(cls, view: GoogleView) -> GoogleSyncOut:
        return cls(
            configured=view.configured,
            client_email=view.client_email,
            admin_subject=view.admin_subject,
            customer_id=view.customer_id,
            group_filter=list(view.group_filter),
            enabled=view.enabled,
            last_run_at=view.record.last_run_at,
            last_error=view.record.last_error,
            counts=view.record.counts,
        )


class GoogleSyncIn(BaseModel):
    service_account_json: str | None = Field(
        default=None, max_length=20_000, description="The JSON key file of the service account (write-only)"
    )
    admin_subject: str | None = Field(default=None, max_length=320, description="A Workspace admin's email")
    customer_id: str | None = Field(default=None, max_length=64, description='Default "my_customer"')
    group_filter: list[str] | None = Field(
        default=None,
        max_length=100,
        description='Group email prefixes ending in "*" or text the group email or name contains; empty syncs all',
    )
    enabled: bool | None = None


class GoogleTestOut(BaseModel):
    ok: bool
    detail: str
