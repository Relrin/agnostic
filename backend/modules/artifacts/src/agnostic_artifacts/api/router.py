"""HTTP routes of the artefacts module.

``/instances/{instance}/artifacts/...`` serves an artefact's bytes to someone who can read its session, and manages
share links. ``/shares/{token}`` opens a link; it is the one route here that may answer without a sign-in, and only
for links shared with anyone.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Path, Query, Response

from agnostic_artifacts.api.schemas import CreatedShareOut, SharedArtifactOut, ShareIn, ShareOut, SharesOut
from agnostic_artifacts.application.content import ArtifactContent, Fetched
from agnostic_artifacts.application.shares import ShareRequest, Shares
from agnostic_kernel.auth import Authentication, Principal

router = APIRouter(route_class=DishkaRoute)
share_router = APIRouter(route_class=DishkaRoute)

DispositionQuery = Annotated[
    Literal["inline", "attachment"], Query(description="inline to view (isolated preview), attachment to download")
]


def _response(fetched: Fetched, filename: str, disposition: Literal["inline", "attachment"]) -> Response:
    served = fetched.served(filename, disposition)
    return Response(content=fetched.data, media_type=served.content_type, headers=served.headers)


@router.get(
    "/{instance}/artifacts/{session_id}/content/{storage_key:path}",
    summary="An artefact's bytes, for viewing in an isolated preview or for download (needs sessions:read)",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The file"}},
)
async def artifact_content(
    instance: str,
    session_id: str,
    storage_key: Annotated[str, Path(description="Storage key, as the artefact list gives it")],
    principal: FromDishka[Principal],
    content: FromDishka[ArtifactContent],
    filename: Annotated[str, Query(min_length=1, max_length=255)] = "artifact",
    disposition: DispositionQuery = "inline",
) -> Response:
    target = await content.instance(instance)
    fetched = await content.fetch(principal, target, session_id, storage_key)
    return _response(fetched, filename, disposition)


@router.post(
    "/{instance}/artifacts/shares",
    summary="Create a share link to an artefact you can read (needs artifacts:share)",
    status_code=201,
)
async def create_share(
    instance: str, body: ShareIn, principal: FromDishka[Principal], shares: FromDishka[Shares]
) -> CreatedShareOut:
    created = await shares.create(
        principal,
        instance,
        ShareRequest(
            session_id=body.session_id,
            storage_key=body.storage_key,
            filename=body.filename,
            audience=body.audience,
            ttl_seconds=body.ttl_seconds,
        ),
    )
    return CreatedShareOut(
        share=ShareOut.of(created.share, datetime.now(UTC)), token=created.token, path=f"/s/{created.token}"
    )


@router.get(
    "/{instance}/artifacts/shares", summary="Your share links on an instance (everyone's with artifacts:manage)"
)
async def list_shares(
    instance: str,
    principal: FromDishka[Principal],
    shares: FromDishka[Shares],
    session_id: str | None = None,
) -> SharesOut:
    now = datetime.now(UTC)
    found = await shares.list(principal, instance, session_id=session_id)
    return SharesOut(data=[ShareOut.of(share, now) for share in found], public_links=shares.public_links)


@router.delete("/{instance}/artifacts/shares/{share_id}", summary="Revoke a share link; it stops working at once")
async def revoke_share(
    instance: str, share_id: str, principal: FromDishka[Principal], shares: FromDishka[Shares]
) -> ShareOut:
    return ShareOut.of(await shares.revoke(principal, instance, share_id), datetime.now(UTC))


@share_router.get("/{token}", summary="What a share link points to (sign-in needed unless it is shared with anyone)")
async def shared_artifact(
    token: str, authentication: FromDishka[Authentication], shares: FromDishka[Shares]
) -> SharedArtifactOut:
    share = await shares.describe(token, authentication.principal)
    return SharedArtifactOut(
        filename=share.filename,
        content_type=share.content_type,
        size=share.size,
        audience=share.audience,
        shared_by=share.created_by_name,
        created_at=share.created_at,
        expires_at=share.expires_at,
    )


@share_router.get(
    "/{token}/content",
    summary="The shared file's bytes, as they were when shared",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The file"}},
)
async def shared_content(
    token: str,
    authentication: FromDishka[Authentication],
    shares: FromDishka[Shares],
    disposition: DispositionQuery = "inline",
) -> Response:
    share, fetched = await shares.open(token, authentication.principal)
    return _response(fetched, share.filename, disposition)
