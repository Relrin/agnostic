"""Request and response bodies of the tool catalog API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agnostic_spec.toolkits import ToolkitList, ToolkitSpec
from agnostic_tool_catalog.application.catalog import Changes, EntryView
from agnostic_tool_catalog.application.sync import InstanceStatus, SyncToken
from agnostic_tool_catalog.domain.entries import Draft

LevelIn = Literal["org", "team", "custom"]
KindIn = Literal["mcp", "toolkit"]
TransportIn = Literal["streamable-http", "sse", "stdio"]


class SameToolOut(BaseModel):
    entry_id: str
    registry_name: str
    level: LevelIn
    level_label: str
    display_name: str


class EntryOut(BaseModel):
    id: str
    slug: str
    registry_name: str = Field(description="The toolkit name on the runtime, level first (org-linear)")
    level: LevelIn
    level_label: str = Field(description="Organization, Team · <group> or Custom: the badge on the block")
    owner_group_id: str | None
    owner_group_name: str | None
    display_name: str
    description: str
    icon: str | None
    kind: KindIn
    transport: TransportIn | None
    toolkit_key: str | None
    config: dict[str, Any] = Field(description="Credentials are {'env': NAME} references, never values")
    requires_confirmation_tools: list[str]
    instance_ids: list[str] = Field(description="Empty: every instance")
    status: Literal["active", "disabled"]
    local: bool = Field(description="Runs commands on the runtime: privileged, and the runtime must opt in")
    version: int
    editable: bool
    same_as: list[SameToolOut] = Field(description="Other entries you can use that offer the same tool")
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, view: EntryView) -> EntryOut:
        entry = view.entry
        return cls(
            id=entry.id,
            slug=entry.slug,
            registry_name=entry.registry_name,
            level=entry.level,
            level_label=view.level_label,
            owner_group_id=entry.owner_group_id,
            owner_group_name=view.owner_group_name,
            display_name=entry.display_name,
            description=entry.description,
            icon=entry.icon,
            kind=entry.kind,
            transport=entry.transport,
            toolkit_key=entry.toolkit_key,
            config=entry.config,
            requires_confirmation_tools=list(entry.requires_confirmation_tools),
            instance_ids=list(entry.instance_ids),
            status=entry.status,
            local=entry.local,
            version=entry.version,
            editable=view.editable,
            same_as=[
                SameToolOut(
                    entry_id=item.entry_id,
                    registry_name=item.registry_name,
                    level=item.level,
                    level_label=item.level_label,
                    display_name=item.display_name,
                )
                for item in view.same_as
            ],
            created_by=entry.created_by,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )


class EntryIn(BaseModel):
    slug: str = Field(description="Short name (linear); the registry name adds the level in front")
    level: LevelIn
    display_name: str
    kind: KindIn
    owner_group_id: str | None = Field(default=None, description="Team entries: the group; custom: optional")
    description: str = ""
    icon: str | None = None
    transport: TransportIn | None = None
    toolkit_key: str | None = None
    config: dict[str, Any] = Field(
        default_factory=dict[str, Any],
        description="MCP: url, headers, command, args, env, include_tools, exclude_tools, tool_name_prefix, "
        "timeout_seconds. Toolkit: params. Credentials as {'env': NAME, 'format': 'Bearer {}'}.",
    )
    requires_confirmation_tools: list[str] = Field(default_factory=list[str])
    instance_ids: list[str] = Field(default_factory=list[str], description="Ids or slugs; empty: every instance")

    def draft(self) -> Draft:
        return Draft(
            slug=self.slug,
            level=self.level,
            display_name=self.display_name,
            kind=self.kind,
            owner_group_id=self.owner_group_id,
            description=self.description,
            icon=self.icon,
            transport=self.transport,
            toolkit_key=self.toolkit_key,
            config=self.config,
            requires_confirmation_tools=tuple(self.requires_confirmation_tools),
            instance_ids=tuple(self.instance_ids),
        )


class EntryPatch(BaseModel):
    """Name, level, kind and toolkit stay: the runtime knows the tool by them (add a new entry instead)."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(description="Expected version (optimistic concurrency)")
    display_name: str | None = None
    description: str | None = None
    icon: str | None = None
    transport: TransportIn | None = None
    config: dict[str, Any] | None = None
    requires_confirmation_tools: list[str] | None = None
    instance_ids: list[str] | None = None

    def changes(self) -> Changes:
        # A null means "leave it" (clear a text with ""): nulls never reach the rules as values.
        values = self.model_dump(exclude_unset=True, exclude_none=True, exclude={"version"})
        return Changes(values=values, version=self.version)


class ToolkitParamOut(BaseModel):
    name: str
    type: str
    required: bool
    default: Any = None
    choices: list[Any]
    secret: bool
    description: str


class ToolkitOut(BaseModel):
    key: str
    label: str
    description: str
    category: str
    local: bool
    extra: str | None = Field(description="The package the runtime needs for it")
    params: list[ToolkitParamOut]
    importable: bool | None = Field(default=None, description="The runtime can build it (from the runtime's own list)")

    @classmethod
    def of(cls, spec: ToolkitSpec, importable: bool | None) -> ToolkitOut:
        return cls(
            key=spec.key,
            label=spec.label,
            description=spec.description,
            category=spec.category,
            local=spec.local,
            extra=spec.extra,
            params=[
                ToolkitParamOut(
                    name=param.name,
                    type=param.type,
                    required=param.required,
                    default=param.default,
                    choices=list(param.choices),
                    secret=param.secret,
                    description=param.description,
                )
                for param in spec.params
            ],
            importable=importable,
        )


class ToolkitsOut(BaseModel):
    agno_version: str
    from_instance: bool = Field(description="The instance's bridge answered with its own list")
    toolkits: list[ToolkitOut]

    @classmethod
    def of(
        cls, toolkits: ToolkitList, *, from_instance: bool, importable: dict[str, bool] | None = None
    ) -> ToolkitsOut:
        return cls(
            agno_version=toolkits.agno_version,
            from_instance=from_instance,
            toolkits=[ToolkitOut.of(spec, (importable or {}).get(spec.key)) for spec in toolkits.toolkits],
        )


class BridgeEntryOut(BaseModel):
    name: str
    state: str
    detail: str | None = None
    functions: list[str] = Field(default_factory=list[str])


class BridgeReportOut(BaseModel):
    enabled: bool = True
    local_allowed: bool = False
    interval_seconds: int | None = None
    last_sync_at: datetime | None = None
    last_error: str | None = None
    replica_id: str | None = None
    entries: list[BridgeEntryOut] = Field(default_factory=list[BridgeEntryOut])


class SyncStatusOut(BaseModel):
    instance_id: str
    instance_name: str
    last_pulled_at: datetime | None
    entries: int
    bridge_version: str | None
    reachable: bool = Field(description="The bridge answered for its tool catalog status")
    bridge: BridgeReportOut | None

    @classmethod
    def of(cls, status: InstanceStatus) -> SyncStatusOut:
        state = status.state
        return cls(
            instance_id=status.instance.id,
            instance_name=status.instance.display_name,
            last_pulled_at=state.last_pulled_at if state else None,
            entries=state.entries if state else 0,
            bridge_version=state.bridge_version if state else None,
            reachable=status.bridge is not None,
            bridge=BridgeReportOut.model_validate(status.bridge) if status.bridge is not None else None,
        )


class SyncTokenOut(BaseModel):
    token: str = Field(description="Shown once")
    service_account: str
    env: dict[str, str] = Field(description="Set these on the runtime")

    @classmethod
    def of(cls, token: SyncToken) -> SyncTokenOut:
        return cls(token=token.token, service_account=token.service_account, env=token.env)


class NudgeOut(BaseModel):
    reached: bool


class DiscoveredToolOut(BaseModel):
    name: str
    description: str | None = None
