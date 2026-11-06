"""How runtimes get the catalog: the manifest their bridge pulls, the token it pulls with, and how it is doing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from agnostic_agentos_client import AgentOSError
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.errors import NotFoundError, ServiceUnavailableError, ValidationFailedError
from agnostic_service_accounts.facade import NewServiceAccount, ServiceAccountsFacade
from agnostic_spec.toolkits import ToolkitList
from agnostic_studio.facade import CatalogInfo, CatalogTool
from agnostic_tool_catalog.application.catalog import CatalogAccess, CatalogViews
from agnostic_tool_catalog.application.ports import (
    COMPONENTS_WRITE,
    READ,
    SYNC,
    WRITE,
    EntryRepository,
    RuntimeBridge,
    SyncState,
    SyncStateRepository,
)
from agnostic_tool_catalog.application.toolkits import Toolkits
from agnostic_tool_catalog.domain.entries import visible
from agnostic_tool_catalog.domain.manifest import build_manifest, etag, manifest_entry

TOKEN_EXPIRY = "365d"  # noqa: S105  (an expiry choice, not a secret)


@dataclass(frozen=True, slots=True)
class Pulled:
    manifest: dict[str, Any] | None
    """``None`` when the bridge already has this version (answer 304)."""
    etag: str


@dataclass(frozen=True, slots=True)
class SyncToken:
    token: str
    service_account: str
    env: dict[str, str]
    """What to set on the runtime."""


@dataclass(frozen=True, slots=True)
class InstanceStatus:
    instance: Instance
    state: SyncState | None
    bridge: dict[str, Any] | None
    """The bridge's own report (``GET /agnostic/v1/tool-catalog/status``), when it answered."""


@dataclass(frozen=True, slots=True)
class RuntimeToolkits:
    toolkits: ToolkitList
    from_instance: bool
    importable: dict[str, bool]


class ManifestReader:
    """The machine side: what a bridge pulls with its instance's sync token."""

    def __init__(
        self,
        authorizer: Authorizer,
        instances: InstancesFacade,
        entries: EntryRepository,
        states: SyncStateRepository,
    ) -> None:
        self._authorizer = authorizer
        self._instances = instances
        self._entries = entries
        self._states = states

    async def pull(
        self,
        principal: Principal,
        instance_ref: str,
        *,
        if_none_match: str | None,
        ip: str | None,
        bridge_version: str | None,
    ) -> Pulled:
        instance = await self._instances.get(instance_ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {instance_ref!r}.")
        _ = await self._authorizer.require(principal, SYNC, instance_id=instance.id)
        manifest = build_manifest(instance.id, await self._entries.list())
        tag = etag(manifest)
        await self._states.record(
            SyncState(
                instance_id=instance.id,
                manifest_etag=tag,
                entries=len(manifest["entries"]),
                bridge_version=(bridge_version or "")[:40] or None,
                last_pull_ip=ip,
                last_pulled_at=utcnow(),
            )
        )
        await self._states.commit()
        return Pulled(None if if_none_match == tag else manifest, tag)


class CatalogSync:
    """The people side: set a runtime up to pull, see how it is doing, nudge it, try a server out."""

    def __init__(
        self,
        authorizer: Authorizer,
        access: CatalogAccess,
        instances: InstancesFacade,
        entries: EntryRepository,
        states: SyncStateRepository,
        bridge: RuntimeBridge,
        accounts: ServiceAccountsFacade,
        audit: AuditLog,
        toolkits: Toolkits,
        public_url: str,
    ) -> None:
        self._authorizer = authorizer
        self._access = access
        self._instances = instances
        self._entries = entries
        self._states = states
        self._bridge = bridge
        self._accounts = accounts
        self._audit = audit
        self._toolkits = toolkits
        self._public_url = public_url

    async def _instance(self, ref: str) -> Instance:
        instance = await self._instances.get(ref)
        if instance is None:
            raise NotFoundError(f"There is no instance {ref!r}.")
        return instance

    async def status(self, principal: Principal, ref: str) -> InstanceStatus:
        _ = await self._authorizer.require(principal, READ)
        instance = await self._instance(ref)
        return InstanceStatus(instance, await self._states.get(instance.id), await self._bridge.status(instance))

    async def nudge(self, principal: Principal, ref: str) -> bool:
        _ = await self._authorizer.require(principal, WRITE)
        instance = await self._instance(ref)
        nudged = await self._bridge.nudge(instance)
        _ = await self._audit.record(
            AuditEntry(
                action="tool_catalog.sync",
                actor=actor_of(principal),
                resource_kind="instance",
                resource_id=instance.id,
                resource_display=instance.display_name,
                instance_id=instance.id,
                fields={"instance": instance.display_name, "outcome": "pulled" if nudged else "not reachable"},
            )
        )
        await self._entries.commit()
        return nudged

    async def sync_token(self, principal: Principal, ref: str) -> SyncToken:
        """A gateway token the instance's bridge pulls with: ``tool_catalog:sync`` on this instance only."""
        _ = await self._authorizer.require(principal, WRITE)
        instance = await self._instance(ref)
        name = f"tool-sync-{instance.slug[:40]}-{instance.id[-8:].lower()}"
        for account in await self._accounts.list(principal):
            if account.account.name == name:
                await self._accounts.revoke(principal, account.account.id)
        created = await self._accounts.create(
            principal,
            NewServiceAccount(
                name=name,
                instances=[instance.id],
                description=f"Pulls the tool catalog for {instance.display_name}.",
                scopes=[SYNC],
                expires_in=TOKEN_EXPIRY,
                kinds=("gateway",),
            ),
        )
        token = next((issued.token for issued in created.tokens if issued.kind == "gateway"), None)
        if token is None:
            raise ServiceUnavailableError("The sync token couldn't be issued; try again.")
        _ = await self._audit.record(
            AuditEntry(
                action="tool_catalog.sync_token",
                actor=actor_of(principal),
                resource_kind="instance",
                resource_id=instance.id,
                resource_display=instance.display_name,
                instance_id=instance.id,
                fields={"instance": instance.display_name},
            )
        )
        await self._entries.commit()
        return SyncToken(
            token=token,
            service_account=name,
            env={
                "AGNOSTIC_CONTROL_PLANE_URL": self._public_url,
                "AGNOSTIC_INSTANCE_ID": instance.id,
                "AGNOSTIC_TOOL_CATALOG_TOKEN": token,
            },
        )

    async def discover(self, principal: Principal, entry_id: str, ref: str) -> list[dict[str, Any]]:
        """Connect to an entry's MCP server from the instance's runtime once and list the tools it offers."""
        viewer = await self._access.viewer(principal)
        entry = await self._entries.get(entry_id)
        if entry is None or not visible(entry, viewer):
            raise NotFoundError(f"There is no tool catalog entry {entry_id!r}.")
        if entry.kind != "mcp":
            raise ValidationFailedError("Only MCP servers are discovered; a toolkit's tools are in its description.")
        instance = await self._instance(ref)
        if not entry.applies_to(instance.id):
            raise ValidationFailedError(f"{entry.display_name} isn't offered on {instance.display_name}.")
        if not viewer.manager:
            # The runtime connects with its own credentials: only people who may build there can make it.
            _ = await self._authorizer.require(principal, COMPONENTS_WRITE, instance_id=instance.id)
        try:
            body = await self._bridge.probe(instance, manifest_entry(entry))
        except AgentOSError as exc:
            raise ServiceUnavailableError(f"{instance.display_name} couldn't reach the server: {exc}") from exc
        return cast("list[dict[str, Any]]", body.get("tools") or [])

    async def toolkits(self, principal: Principal, ref: str | None) -> RuntimeToolkits:
        """The instance's own toolkit list when its bridge answers (with what it can build), else the shared one."""
        _ = await self._authorizer.require(principal, READ)
        if ref:
            body = await self._bridge.toolkits(await self._instance(ref))
            if body is not None:
                items = cast("list[dict[str, Any]]", body.get("toolkits") or [])
                importable = {str(item.get("key")): bool(item.get("importable")) for item in items}
                return RuntimeToolkits(Toolkits.from_runtime(body), from_instance=True, importable=importable)
        return RuntimeToolkits(self._toolkits.all(), from_instance=False, importable={})


class CatalogLookup:
    """Studio's ``ToolCatalogLookup``: which registry tools come from the catalog, and how each is doing."""

    def __init__(self, authorizer: Authorizer, catalog: CatalogViews, bridge: RuntimeBridge) -> None:
        self._authorizer = authorizer
        self._catalog = catalog
        self._bridge = bridge

    async def for_instance(self, principal: Principal, instance: Instance) -> list[CatalogTool]:
        if principal.kind == "system" or not (await self._authorizer.check(principal, READ)).allowed:
            return []
        views = await self._catalog.for_instance(principal, instance)
        if not views:
            return []
        report = await self._bridge.status(instance) or {}
        states = {
            str(cast("dict[str, Any]", item).get("name")): cast("dict[str, Any]", item)
            for item in cast("list[object]", report.get("entries") or [])
            if isinstance(item, dict)
        }
        tools: list[CatalogTool] = []
        for view in views:
            entry = view.entry
            state = states.get(entry.registry_name) or {}
            tools.append(
                CatalogTool(
                    registry_name=entry.registry_name,
                    description=entry.description or None,
                    info=CatalogInfo(
                        entry_id=entry.id,
                        level=entry.level,
                        level_label=view.level_label,
                        display_name=entry.display_name,
                        kind=entry.kind,
                        state=str(state.get("state") or "not_on_instance"),
                        icon=entry.icon,
                        transport=entry.transport,
                        toolkit_key=entry.toolkit_key,
                        detail=state.get("detail"),
                        same_as=tuple(other.registry_name for other in view.same_as),
                    ),
                )
            )
        return tools
