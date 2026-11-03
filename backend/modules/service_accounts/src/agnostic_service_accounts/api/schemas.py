"""Request and response bodies of ``/api/v1/service-accounts``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from agnostic_instances.facade import Instance
from agnostic_service_accounts.application.accounts import (
    AccountView,
    Created,
    IssuedToken,
    NewServiceAccount,
    Preview,
    TokenIssued,
)
from agnostic_service_accounts.domain.accounts import (
    GATEWAY_TOKEN_PREFIX,
    NATIVE_TOKEN_PREFIX,
    ROTATION_GRACE,
    GatewayToken,
    NativeToken,
)

ROTATION_NOTE = (
    f"Rotate issues a new gateway token and keeps the old one valid for {int(ROTATION_GRACE.total_seconds() // 3600)}"
    " h so callers can switch. AgentOS can't rotate a native token: rotating revokes it and creates a new one under "
    "the same name, so callers see a brief gap."
)


class InstanceRefOut(BaseModel):
    id: str
    slug: str
    display_name: str

    @classmethod
    def from_instance(cls, instance: Instance) -> InstanceRefOut:
        return cls(id=instance.id, slug=instance.slug, display_name=instance.display_name)


class CreatorOut(BaseModel):
    id: str
    name: str


class ScopeItemOut(BaseModel):
    scope: str
    source: str
    """``role:<role name>`` or ``custom``."""
    privileged: bool


class NativeTokenOut(BaseModel):
    id: str
    kind: Literal["native"] = "native"
    instance: InstanceRefOut | None
    prefix: str
    status: Literal["active", "revoked", "expired"]
    scopes: list[str]
    created_at: datetime
    revoked_at: datetime | None
    expires_at: datetime | None
    last_used_at: datetime | None

    @classmethod
    def from_token(cls, token: NativeToken, instances: dict[str, Instance]) -> NativeTokenOut:
        instance = instances.get(token.instance_id)
        return cls(
            id=token.id,
            instance=InstanceRefOut.from_instance(instance) if instance else None,
            prefix=token.token_prefix,
            status=token.status,
            scopes=list(token.scopes),
            created_at=token.created_at,
            revoked_at=token.revoked_at,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
        )


class GatewayTokenOut(BaseModel):
    id: str
    kind: Literal["gateway"] = "gateway"
    prefix: str
    status: Literal["active", "revoked", "expired"]
    created_at: datetime
    grace_until: datetime | None
    """Set once rotated: the token keeps working until then."""
    revoked_at: datetime | None
    revoke_reason: str | None
    last_used_at: datetime | None
    last_used_ip: str | None

    @classmethod
    def from_token(cls, token: GatewayToken, now: datetime) -> GatewayTokenOut:
        return cls(
            id=token.id,
            prefix=token.prefix,
            status=token.current_status(now),
            created_at=token.created_at,
            grace_until=token.grace_until,
            revoked_at=token.revoked_at or (token.grace_until if token.current_status(now) == "revoked" else None),
            revoke_reason=token.revoke_reason,
            last_used_at=token.last_used_at,
            last_used_ip=token.last_used_ip,
        )


class ServiceAccountOut(BaseModel):
    """A row of the list."""

    id: str
    name: str
    principal: str
    description: str
    scope_source: Literal["role", "custom"]
    role_id: str | None
    role_name: str | None
    source_label: str
    """"Custom scopes", or "Access role: Viewer + 1 scope"."""
    scopes: list[str]
    """Every scope: the role's and the extras."""
    extra_scopes: list[str]
    """Scopes granted directly (the custom checklist, or the extras on top of the role)."""
    scope_count: int
    privileged: bool
    instances: list[InstanceRefOut]
    forwards_user_id: bool
    created_by: CreatorOut
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    expired: bool
    expiry_warning: bool
    """Amber: no expiry, or less than 14 days left."""
    kinds: list[Literal["native", "gateway"]]
    active_tokens: int

    @classmethod
    def from_view(cls, view: AccountView) -> ServiceAccountOut:
        account = view.account
        active = sum(1 for t in view.native_tokens if t.active)
        active += sum(1 for t in view.gateway_tokens if t.current_status(view.now) == "active")
        return cls(
            id=account.id,
            name=account.name,
            principal=account.principal,
            description=account.description,
            scope_source=account.scope_source,
            role_id=account.role_id,
            role_name=view.role_name,
            source_label=view.source_label,
            scopes=list(view.all_scopes),
            extra_scopes=list(account.scopes),
            scope_count=len(view.all_scopes),
            privileged=view.privileged,
            instances=[InstanceRefOut.from_instance(instance) for instance in view.instances],
            forwards_user_id=account.forwards_user_id,
            created_by=CreatorOut(id=account.created_by, name=account.created_by_name),
            created_at=account.created_at,
            last_used_at=view.last_used_at,
            expires_at=account.expires_at,
            expired=account.expired(view.now),
            expiry_warning=account.expiry_warning(view.now),
            kinds=list(view.kinds),
            active_tokens=active,
        )


class ServiceAccountDetailOut(ServiceAccountOut):
    scope_items: list[ScopeItemOut]
    isolation_note: str
    native_tokens: list[NativeTokenOut]
    gateway_tokens: list[GatewayTokenOut]
    rotation_note: str
    cli_command: str

    @classmethod
    def from_view(cls, view: AccountView) -> ServiceAccountDetailOut:
        row = ServiceAccountOut.from_view(view)
        instances = {instance.id: instance for instance in view.instances}
        return cls(
            **row.model_dump(),
            scope_items=[
                ScopeItemOut(scope=item.scope, source=item.source, privileged=item.privileged)
                for item in view.scope_items
            ],
            isolation_note=view.isolation_note,
            native_tokens=[NativeTokenOut.from_token(token, instances) for token in view.native_tokens],
            gateway_tokens=[GatewayTokenOut.from_token(token, view.now) for token in view.gateway_tokens],
            rotation_note=ROTATION_NOTE,
            cli_command=view.cli_command(),
        )


class ServiceAccountIn(BaseModel):
    name: str = Field(max_length=63, examples=["zendesk-bridge"])
    description: str = Field(default="", max_length=2000)
    instances: list[str] = Field(min_length=1, description="Instance ids or slugs")
    role_id: str | None = Field(default=None, description="An access role (id or slug); scopes are then extras")
    scopes: list[str] = Field(default_factory=list[str])
    expires_in: Literal["30d", "90d", "365d", "never"] = "90d"
    kinds: list[Literal["native", "gateway"]] = Field(default_factory=lambda: ["native"], min_length=1)
    forwards_user_id: bool = False
    """Gateway: pass the caller's ``user_id`` through (per-customer isolation); otherwise it is dropped."""
    confirm_privileged: bool = False
    """Required when any scope is privileged (write, delete, ``agent_os:admin``, ``service_accounts:*``)."""

    def request(self) -> NewServiceAccount:
        return NewServiceAccount(
            name=self.name,
            instances=tuple(self.instances),
            description=self.description,
            role_id=self.role_id,
            scopes=tuple(self.scopes),
            expires_in=self.expires_in,
            kinds=tuple(self.kinds),
            forwards_user_id=self.forwards_user_id,
            confirm_privileged=self.confirm_privileged,
        )


class IssuedTokenOut(BaseModel):
    """Shown once. Afterwards only ``prefix`` is visible; the token is stored as a hash."""

    id: str
    kind: Literal["native", "gateway"]
    token: str
    prefix: str
    instance: InstanceRefOut | None
    """The instance a native token works on; ``None`` for a gateway token (every instance of the account)."""
    expires_at: datetime | None
    curl: str
    """A ready-to-paste sample using the token as a bearer token."""

    @classmethod
    def from_issued(cls, issued: IssuedToken) -> IssuedTokenOut:
        return cls(
            id=issued.id,
            kind=issued.kind,
            token=issued.token,
            prefix=issued.prefix,
            instance=InstanceRefOut.from_instance(issued.instance) if issued.instance else None,
            expires_at=issued.expires_at,
            curl=issued.curl,
        )


class CreatedOut(BaseModel):
    account: ServiceAccountDetailOut
    tokens: list[IssuedTokenOut]
    """One native token per instance and/or one gateway token: copy them now, they are not shown again."""

    @classmethod
    def from_created(cls, created: Created) -> CreatedOut:
        return cls(
            account=ServiceAccountDetailOut.from_view(created.view),
            tokens=[IssuedTokenOut.from_issued(token) for token in created.tokens],
        )


class TokenIn(BaseModel):
    kind: Literal["native", "gateway"]
    instance: str | None = Field(default=None, description="For a native token: the instance (id or slug)")


class TokenIssuedOut(BaseModel):
    account: ServiceAccountDetailOut
    token: IssuedTokenOut
    replaced_id: str | None
    """The token this one rotated: revoked (native) or valid until ``grace_until`` (gateway)."""
    grace_until: datetime | None

    @classmethod
    def from_issued(cls, issued: TokenIssued) -> TokenIssuedOut:
        return cls(
            account=ServiceAccountDetailOut.from_view(issued.view),
            token=IssuedTokenOut.from_issued(issued.token),
            replaced_id=issued.replaced_id,
            grace_until=issued.grace_until,
        )


class ServiceAccountPreviewOut(BaseModel):
    principal: str
    privileged_scopes: list[str]
    expires_at: datetime | None
    cli_command: str
    problems: list[str]
    token_prefixes: dict[str, str] = Field(
        default_factory=lambda: {"native": NATIVE_TOKEN_PREFIX, "gateway": GATEWAY_TOKEN_PREFIX}
    )

    @classmethod
    def from_preview(cls, preview: Preview) -> ServiceAccountPreviewOut:
        return cls(
            principal=preview.principal,
            privileged_scopes=list(preview.privileged_scopes),
            expires_at=preview.expires_at,
            cli_command=preview.cli_command,
            problems=list(preview.problems),
        )
