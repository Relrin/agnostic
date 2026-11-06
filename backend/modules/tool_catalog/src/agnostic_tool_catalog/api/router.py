"""HTTP routes under ``/api/v1/tool-catalog``: entries, toolkits, per-instance sync, and the bridge's manifest."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from agnostic_kernel.auth import Principal
from agnostic_tool_catalog.api.schemas import (
    DiscoveredToolOut,
    EntryIn,
    EntryOut,
    EntryPatch,
    KindIn,
    LevelIn,
    NudgeOut,
    SyncStatusOut,
    SyncTokenOut,
    ToolkitsOut,
)
from agnostic_tool_catalog.application.catalog import ToolCatalog
from agnostic_tool_catalog.application.sync import CatalogSync, ManifestReader

router = APIRouter(route_class=DishkaRoute)

ENTRY = "/entries/{entry_id}"
BRIDGE_VERSION_HEADER = "x-agnostic-bridge-version"


@router.get("/entries", summary="Tool catalog entries you can see")
async def list_entries(
    principal: FromDishka[Principal],
    catalog: FromDishka[ToolCatalog],
    kind: KindIn | None = None,
    level: LevelIn | None = None,
    instance: Annotated[str | None, Query(description="Only entries that apply to this instance")] = None,
    q: Annotated[str | None, Query(description="Search the name and description")] = None,
) -> list[EntryOut]:
    views = await catalog.list(principal, kind=kind, level=level, instance=instance, query=q)
    return [EntryOut.of(view) for view in views]


@router.post("/entries", status_code=status.HTTP_201_CREATED, summary="Add an MCP server or toolkit")
async def create_entry(body: EntryIn, principal: FromDishka[Principal], catalog: FromDishka[ToolCatalog]) -> EntryOut:
    return EntryOut.of(await catalog.create(principal, body.draft()))


@router.get(ENTRY, summary="One entry")
async def get_entry(entry_id: str, principal: FromDishka[Principal], catalog: FromDishka[ToolCatalog]) -> EntryOut:
    return EntryOut.of(await catalog.get(principal, entry_id))


@router.patch(ENTRY, summary="Change an entry (name, level and kind stay)")
async def update_entry(
    entry_id: str, body: EntryPatch, principal: FromDishka[Principal], catalog: FromDishka[ToolCatalog]
) -> EntryOut:
    return EntryOut.of(await catalog.update(principal, entry_id, body.changes()))


@router.delete(ENTRY, status_code=status.HTTP_204_NO_CONTENT, summary="Remove an entry")
async def delete_entry(
    entry_id: str,
    principal: FromDishka[Principal],
    catalog: FromDishka[ToolCatalog],
    force: Annotated[bool, Query(description="Remove it even though components use it")] = False,
) -> Response:
    await catalog.delete(principal, entry_id, force=force)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(f"{ENTRY}/enable", summary="Offer the entry again")
async def enable_entry(entry_id: str, principal: FromDishka[Principal], catalog: FromDishka[ToolCatalog]) -> EntryOut:
    return EntryOut.of(await catalog.set_status(principal, entry_id, "active"))


@router.post(f"{ENTRY}/disable", summary="Stop offering the entry (runtimes drop it)")
async def disable_entry(entry_id: str, principal: FromDishka[Principal], catalog: FromDishka[ToolCatalog]) -> EntryOut:
    return EntryOut.of(await catalog.set_status(principal, entry_id, "disabled"))


@router.post(f"{ENTRY}/discover", summary="List the tools an MCP server offers, from an instance's runtime")
async def discover_tools(
    entry_id: str,
    instance: Annotated[str, Query(description="The instance whose runtime connects")],
    principal: FromDishka[Principal],
    sync: FromDishka[CatalogSync],
) -> list[DiscoveredToolOut]:
    tools = await sync.discover(principal, entry_id, instance)
    return [DiscoveredToolOut(name=str(tool.get("name")), description=tool.get("description")) for tool in tools]


@router.get("/toolkits", summary="Agno toolkits an entry can name")
async def list_toolkits(
    principal: FromDishka[Principal],
    sync: FromDishka[CatalogSync],
    instance: Annotated[str | None, Query(description="Ask this instance's runtime for its own list")] = None,
) -> ToolkitsOut:
    found = await sync.toolkits(principal, instance)
    return ToolkitsOut.of(found.toolkits, from_instance=found.from_instance, importable=found.importable)


@router.get("/instances/{instance}/status", summary="How an instance's runtime is doing with the catalog")
async def sync_status(instance: str, principal: FromDishka[Principal], sync: FromDishka[CatalogSync]) -> SyncStatusOut:
    return SyncStatusOut.of(await sync.status(principal, instance))


@router.post("/instances/{instance}/sync", summary="Ask the instance's runtime to pull the catalog now")
async def nudge(instance: str, principal: FromDishka[Principal], sync: FromDishka[CatalogSync]) -> NudgeOut:
    return NudgeOut(reached=await sync.nudge(principal, instance))


@router.post(
    "/instances/{instance}/sync-token",
    status_code=status.HTTP_201_CREATED,
    summary="Issue the token the instance's bridge pulls with (replaces the previous one)",
)
async def sync_token(instance: str, principal: FromDishka[Principal], sync: FromDishka[CatalogSync]) -> SyncTokenOut:
    return SyncTokenOut.of(await sync.sync_token(principal, instance))


@router.get(
    "/sync/{instance}/manifest",
    summary="The catalog for one instance, as its bridge pulls it",
    responses={304: {"description": "The bridge already has this version"}},
)
async def manifest(
    instance: str,
    request: Request,
    principal: FromDishka[Principal],
    reader: FromDishka[ManifestReader],
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    pulled = await reader.pull(
        principal,
        instance,
        if_none_match=if_none_match,
        ip=request.client.host if request.client else None,
        bridge_version=request.headers.get(BRIDGE_VERSION_HEADER),
    )
    headers = {"ETag": pulled.etag, "Cache-Control": "no-store"}
    if pulled.manifest is None:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return JSONResponse(pulled.manifest, headers=headers)
