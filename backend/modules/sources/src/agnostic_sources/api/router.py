"""HTTP routes under ``/api/v1/instances/{instance}/studio/sources`` and the org-wide ``/api/v1/studio/connections``."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response, status
from fastapi.responses import RedirectResponse

from agnostic_codegen import unified
from agnostic_kernel.auth import Principal
from agnostic_kernel.settings import Settings
from agnostic_sources.api.schemas import (
    ActivateIn,
    ChangeDiffOut,
    ChangeOut,
    ChangesOut,
    CodeSourceOut,
    CommitIn,
    CommitPreviewOut,
    ComponentSourceOut,
    ConflictCountOut,
    ConflictOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionPatchIn,
    IncludeIn,
    InstallUrlOut,
    JobOut,
    LocalRootsOut,
    PullIn,
    PullRequestOut,
    PullResultOut,
    RepoOut,
    ResolveIn,
    ScanReportOut,
    SourceIn,
    SourcePatchIn,
    WebhookDeliveryOut,
)
from agnostic_sources.application.access import SOURCES_WRITE, SourcesAccess
from agnostic_sources.application.connections import Connections
from agnostic_sources.application.files import SourceFiles
from agnostic_sources.application.outgoing import Committer, OutgoingPreparer, PullRequestTracker
from agnostic_sources.application.sources import Sources
from agnostic_sources.application.sync import ConflictResolver, Puller
from agnostic_sources.application.views import SourceViews

router = APIRouter(route_class=DishkaRoute)
org_router = APIRouter(route_class=DishkaRoute)

SOURCES = "/{instance}/studio/sources"
SOURCE = "/{instance}/studio/sources/{source_id}"


# ---------------------------------------------------------------- connections, for the whole org


@org_router.get("/studio/connections", summary="Connections to git hosts")
async def list_connections(
    principal: FromDishka[Principal], connections: FromDishka[Connections]
) -> list[ConnectionOut]:
    return [ConnectionOut.of(item) for item in await connections.list(principal)]


@org_router.post("/studio/connections", status_code=status.HTTP_201_CREATED, summary="Connect a git host")
async def create_connection(
    body: ConnectionIn, principal: FromDishka[Principal], connections: FromDishka[Connections]
) -> ConnectionOut:
    return ConnectionOut.of(await connections.create(principal, body.draft()))


@org_router.get(
    "/studio/connections/github/callback",
    summary="Where GitHub returns after the app was installed",
    response_class=RedirectResponse,
    status_code=status.HTTP_303_SEE_OTHER,
)
async def github_callback(
    installation_id: str,
    state: str,
    principal: FromDishka[Principal],
    connections: FromDishka[Connections],
    settings: FromDishka[Settings],
) -> RedirectResponse:
    _, return_to = await connections.complete_install(principal, state, installation_id)
    target = return_to if return_to and return_to.startswith("/") and not return_to.startswith("//") else "/"
    return RedirectResponse(f"{settings.public_url()}{target}", status_code=status.HTTP_303_SEE_OTHER)


@org_router.get("/studio/connections/{connection_id}", summary="One connection")
async def get_connection(
    connection_id: str, principal: FromDishka[Principal], connections: FromDishka[Connections]
) -> ConnectionOut:
    return ConnectionOut.of(await connections.get(principal, connection_id))


@org_router.patch("/studio/connections/{connection_id}", summary="Change a connection (only the fields sent)")
async def update_connection(
    connection_id: str,
    body: ConnectionPatchIn,
    principal: FromDishka[Principal],
    connections: FromDishka[Connections],
) -> ConnectionOut:
    return ConnectionOut.of(await connections.update(principal, connection_id, body.patch(), body.version))


@org_router.delete("/studio/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove")
async def delete_connection(
    connection_id: str, principal: FromDishka[Principal], connections: FromDishka[Connections]
) -> Response:
    await connections.delete(principal, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@org_router.post("/studio/connections/{connection_id}/verify", summary="Check the connection's credentials")
async def verify_connection(
    connection_id: str, principal: FromDishka[Principal], connections: FromDishka[Connections]
) -> ConnectionOut:
    return ConnectionOut.of(await connections.verify(principal, connection_id))


@org_router.get("/studio/connections/{connection_id}/github/install", summary="Where to install the GitHub App")
async def github_install(
    connection_id: str,
    principal: FromDishka[Principal],
    connections: FromDishka[Connections],
    return_to: str | None = None,
) -> InstallUrlOut:
    return InstallUrlOut(url=await connections.install_url(principal, connection_id, return_to))


@org_router.get("/studio/connections/{connection_id}/repos", summary="Repositories the connection can see")
async def connection_repos(
    connection_id: str, principal: FromDishka[Principal], connections: FromDishka[Connections], q: str | None = None
) -> list[RepoOut]:
    return [RepoOut.of(repo) for repo in await connections.repos(principal, connection_id, q)]


@org_router.get("/studio/connections/{connection_id}/branches", summary="Branches of a repository")
async def connection_branches(
    connection_id: str, repo: str, principal: FromDishka[Principal], connections: FromDishka[Connections]
) -> list[str]:
    return await connections.branches(principal, connection_id, repo)


# ---------------------------------------------------------------- sources


@router.get(SOURCES, summary="Code sources synced with the instance")
async def list_sources(
    instance: str, principal: FromDishka[Principal], views: FromDishka[SourceViews]
) -> list[CodeSourceOut]:
    _, cards = await views.cards(principal, instance)
    return [CodeSourceOut.of(card) for card in cards]


@router.post(SOURCES, status_code=status.HTTP_201_CREATED, summary="Connect a repository or local folder (scans it)")
async def create_source(
    instance: str,
    body: SourceIn,
    principal: FromDishka[Principal],
    sources: FromDishka[Sources],
    views: FromDishka[SourceViews],
) -> CodeSourceOut:
    source = await sources.create(principal, instance, body.draft())
    return CodeSourceOut.of(await views.card(principal, instance, source.id))


@router.get(f"{SOURCES}/conflicts/count", summary="Open conflicts on the instance (the sidebar dot)")
async def conflict_count(
    instance: str, principal: FromDishka[Principal], views: FromDishka[SourceViews]
) -> ConflictCountOut:
    found, count = await views.conflict_count(principal, instance)
    return ConflictCountOut(instance_id=found.id, count=count)


@router.get(f"{SOURCES}/local-roots", summary="Folders local sources may point into")
async def local_roots(
    instance: str, principal: FromDishka[Principal], access: FromDishka[SourcesAccess], files: FromDishka[SourceFiles]
) -> LocalRootsOut:
    _ = await access.instance(principal, instance, SOURCES_WRITE)
    return LocalRootsOut(roots=files.folders.allowed_roots())


@router.get(SOURCE, summary="One source")
async def get_source(
    instance: str, source_id: str, principal: FromDishka[Principal], views: FromDishka[SourceViews]
) -> CodeSourceOut:
    return CodeSourceOut.of(await views.card(principal, instance, source_id))


@router.patch(SOURCE, summary="Change the branch, path mappings, sync policy or registry convention")
async def update_source(
    instance: str,
    source_id: str,
    body: SourcePatchIn,
    principal: FromDishka[Principal],
    sources: FromDishka[Sources],
    views: FromDishka[SourceViews],
) -> CodeSourceOut:
    _ = await sources.update(principal, instance, source_id, body.patch(), body.version)
    return CodeSourceOut.of(await views.card(principal, instance, source_id))


@router.delete(SOURCE, status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect (components stay in Studio)")
async def delete_source(
    instance: str, source_id: str, principal: FromDishka[Principal], sources: FromDishka[Sources]
) -> Response:
    await sources.delete(principal, instance, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(f"{SOURCE}/scan", summary="The initial scan: files, parse results, matches and proposed bindings")
async def scan_report(
    instance: str, source_id: str, principal: FromDishka[Principal], sources: FromDishka[Sources]
) -> ScanReportOut:
    _, source = await sources.get(principal, instance, source_id)
    return ScanReportOut(
        status=source.status, status_detail=source.status_detail, head_sha=source.head_sha, report=source.scan_report
    )


@router.post(f"{SOURCE}/activate", summary="Bind the scanned files and start syncing")
async def activate_source(
    instance: str,
    source_id: str,
    body: ActivateIn,
    principal: FromDishka[Principal],
    sources: FromDishka[Sources],
    views: FromDishka[SourceViews],
) -> CodeSourceOut:
    _ = await sources.activate(principal, instance, source_id, body.decisions())
    return CodeSourceOut.of(await views.card(principal, instance, source_id))


@router.post(f"{SOURCE}/fetch", status_code=status.HTTP_202_ACCEPTED, summary="Fetch now and work out incoming changes")
async def fetch_source(
    instance: str, source_id: str, principal: FromDishka[Principal], sources: FromDishka[Sources]
) -> JobOut:
    return JobOut(job_id=await sources.fetch(principal, instance, source_id))


@router.get(f"{SOURCE}/changes", summary="Incoming and outgoing changes, conflicts and pull requests")
async def get_changes(
    instance: str, source_id: str, principal: FromDishka[Principal], views: FromDishka[SourceViews]
) -> ChangesOut:
    return ChangesOut.of(await views.changes(principal, instance, source_id), principal.id)


@router.patch(f"{SOURCE}/changes/{{change_id}}", summary="Include or leave out a change")
async def include_change(
    instance: str,
    source_id: str,
    change_id: str,
    body: IncludeIn,
    principal: FromDishka[Principal],
    views: FromDishka[SourceViews],
) -> ChangeOut:
    return ChangeOut.of(await views.include(principal, instance, source_id, change_id, body.included), principal.id)


@router.get(f"{SOURCE}/changes/{{change_id}}/diff", summary="The file before and after the change")
async def change_diff(
    instance: str, source_id: str, change_id: str, principal: FromDishka[Principal], views: FromDishka[SourceViews]
) -> ChangeDiffOut:
    _, change = await views.change(principal, instance, source_id, change_id)
    before, after = change.before_code or "", change.after_code or ""
    label = "studio" if change.direction == "outgoing" else "synced"
    return ChangeDiffOut(
        path=change.path,
        before=change.before_code,
        after=change.after_code,
        unified=unified(before, after, from_label=f"{label}/{change.path}", to_label=f"new/{change.path}"),
    )


@router.post(f"{SOURCE}/pull", summary="Pull incoming changes as drafts (never published)")
async def pull_changes(
    instance: str, source_id: str, body: PullIn, principal: FromDishka[Principal], puller: FromDishka[Puller]
) -> list[PullResultOut]:
    return [PullResultOut.of(item) for item in await puller.pull(principal, instance, source_id, body.change_ids)]


@router.post(f"{SOURCE}/outgoing/refresh", summary="Work out what Studio has that the repository doesn't")
async def refresh_outgoing(
    instance: str,
    source_id: str,
    principal: FromDishka[Principal],
    sources: FromDishka[Sources],
    preparer: FromDishka[OutgoingPreparer],
) -> list[ChangeOut]:
    _, source = await sources.get(principal, instance, source_id)
    return [ChangeOut.of(change, principal.id) for change in await preparer.prepare(source.id)]


@router.get(f"{SOURCE}/commit-preview", summary="The branch, message and review requirement of a commit")
async def commit_preview(
    instance: str,
    source_id: str,
    change_ids: Annotated[list[str], Query(min_length=1)],
    principal: FromDishka[Principal],
    committer: FromDishka[Committer],
) -> CommitPreviewOut:
    return CommitPreviewOut.of(await committer.preview(principal, instance, source_id, change_ids))


@router.post(f"{SOURCE}/commit", status_code=status.HTTP_202_ACCEPTED, summary="Commit & open a pull request")
async def commit_changes(
    instance: str, source_id: str, body: CommitIn, principal: FromDishka[Principal], committer: FromDishka[Committer]
) -> JobOut:
    return JobOut(job_id=await committer.request(principal, instance, source_id, body.change_ids, body.message))


@router.post(f"{SOURCE}/pull-requests/refresh", summary="Check the source's open pull requests now")
async def refresh_pull_requests(
    instance: str,
    source_id: str,
    principal: FromDishka[Principal],
    sources: FromDishka[Sources],
    tracker: FromDishka[PullRequestTracker],
) -> list[PullRequestOut]:
    _, source = await sources.get(principal, instance, source_id)
    return [PullRequestOut.of(pull) for pull in await tracker.refresh(source.id)]


@router.post(f"{SOURCE}/conflicts/{{conflict_id}}/resolve", summary="Keep Studio's value, the repository's, or a merge")
async def resolve_conflict(
    instance: str,
    source_id: str,
    conflict_id: str,
    body: ResolveIn,
    principal: FromDishka[Principal],
    resolver: FromDishka[ConflictResolver],
) -> ConflictOut:
    return ConflictOut.of(
        await resolver.resolve(principal, instance, source_id, conflict_id, body.resolution, body.value)
    )


@router.get(f"{SOURCE}/deliveries", summary="Recent webhook deliveries")
async def deliveries(
    instance: str, source_id: str, principal: FromDishka[Principal], views: FromDishka[SourceViews]
) -> list[WebhookDeliveryOut]:
    return [WebhookDeliveryOut.of(item) for item in await views.deliveries(principal, instance, source_id)]


@router.get("/{instance}/studio/components/{component_id}/source", summary="Where the component is synced (source bar)")
async def component_source(
    instance: str, component_id: str, principal: FromDishka[Principal], views: FromDishka[SourceViews]
) -> ComponentSourceOut:
    return ComponentSourceOut.of(await views.component(principal, instance, component_id), principal.id)
