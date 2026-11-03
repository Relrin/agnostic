"""SCIM 2.0 service provider at ``/scim/v2`` (outside ``/api/v1``), for Okta, Entra ID and other IdPs.

Requests authenticate with the SCIM bearer token, not a web session. Every response is ``application/scim+json``
and every error uses the SCIM error schema; each authenticated request also updates the sync status (last request,
last error) shown in Org settings > Directory sync.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from typing import Annotated, Any, cast

import orjson
from dishka import AsyncContainer
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agnostic_directory.application.scim import ScimAuth, ScimGroups, ScimRecorder, ScimUsers
from agnostic_directory.application.sync import DirectoryPolicy
from agnostic_directory.domain.scim import (
    MEDIA_TYPE,
    Json,
    Page,
    ScimError,
    list_response,
    project,
    resource_types,
    schemas,
    service_provider_config,
)
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import AppError
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

PRINCIPAL_STATE = "scim_principal"


class ScimResponse(JSONResponse):
    media_type = MEDIA_TYPE

    def render(self, content: Any) -> bytes:  # noqa: ANN401
        return orjson.dumps(content)


def _as_scim_error(exc: Exception) -> ScimError:
    if isinstance(exc, ScimError):
        return exc
    if isinstance(exc, AppError):
        code = int(exc.status)
        return ScimError(400 if code == status.HTTP_422_UNPROCESSABLE_CONTENT else code, exc.detail or exc.title)
    if isinstance(exc, RequestValidationError):
        return ScimError(400, "A query parameter or the body is malformed.", "invalidValue")
    log.error("scim.unhandled_error", exc_info=exc)
    return ScimError(500, "Something went wrong.")


async def _record(request: Request, error: ScimError | None) -> None:
    container = cast("AsyncContainer | None", getattr(request.state, "dishka_container", None))
    if container is None:
        return
    try:
        recorder = await container.get(ScimRecorder)
        if error is None:
            await recorder.succeeded()
        else:
            await recorder.failed(error)
    except Exception as exc:  # noqa: BLE001  (the status pill must never fail the IdP's request)
        log.warning("scim.status_not_recorded", error=str(exc)[:200])


class ScimRoute(DishkaRoute):
    """Answers every error in the SCIM error schema and records each authenticated request in the sync status."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def scim_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except Exception as exc:  # noqa: BLE001
                error = _as_scim_error(exc)
                if getattr(request.state, PRINCIPAL_STATE, None) is not None:
                    await _record(request, error)
                return ScimResponse(error.body(), status_code=error.status)
            if getattr(request.state, PRINCIPAL_STATE, None) is not None:
                await _record(request, None)
            return response

        return scim_handler


scim_router = APIRouter(route_class=ScimRoute, include_in_schema=False)


async def _caller(request: Request, auth: ScimAuth) -> Principal:
    principal = await auth.authenticate(request.headers.get("authorization"))
    setattr(request.state, PRINCIPAL_STATE, principal)
    return principal


async def _body(request: Request) -> Mapping[str, object]:
    try:
        body = orjson.loads(await request.body())
    except orjson.JSONDecodeError as exc:
        raise ScimError(400, "The body must be a JSON object.", "invalidSyntax") from exc
    if not isinstance(body, dict):
        raise ScimError(400, "The body must be a JSON object.", "invalidSyntax")
    return cast("Mapping[str, object]", body)


def _one(
    resource: Json, *, status_code: int = 200, attributes: str | None = None, excluded: str | None = None
) -> Response:
    headers: dict[str, str] = {}
    meta = resource.get("meta")
    if isinstance(meta, dict) and status_code == status.HTTP_201_CREATED:
        headers["Location"] = str(cast("dict[str, object]", meta).get("location") or "")
    return ScimResponse(
        project(resource, attributes=attributes, excluded=excluded), status_code=status_code, headers=headers
    )


def _many(resources: list[Json], total: int, page: Page, attributes: str | None, excluded: str | None) -> Response:
    projected = [project(resource, attributes=attributes, excluded=excluded) for resource in resources]
    return ScimResponse(list_response(projected, total=total, page=page))


@scim_router.get("/ServiceProviderConfig")
async def get_service_provider_config(
    request: Request, auth: FromDishka[ScimAuth], policy: FromDishka[DirectoryPolicy]
) -> Response:
    _ = await _caller(request, auth)
    return ScimResponse(service_provider_config(policy.scim_base_url))


@scim_router.get("/ResourceTypes")
async def list_resource_types(
    request: Request, auth: FromDishka[ScimAuth], policy: FromDishka[DirectoryPolicy]
) -> Response:
    _ = await _caller(request, auth)
    types = resource_types(policy.scim_base_url)
    return ScimResponse(list_response(types, total=len(types), page=Page.of(1, len(types))))


@scim_router.get("/ResourceTypes/{name}")
async def get_resource_type(
    name: str, request: Request, auth: FromDishka[ScimAuth], policy: FromDishka[DirectoryPolicy]
) -> Response:
    _ = await _caller(request, auth)
    for resource_type in resource_types(policy.scim_base_url):
        if str(resource_type["id"]).lower() == name.lower():
            return ScimResponse(resource_type)
    raise ScimError(404, f"There is no resource type {name}.")


@scim_router.get("/Schemas")
async def list_schemas(request: Request, auth: FromDishka[ScimAuth], policy: FromDishka[DirectoryPolicy]) -> Response:
    _ = await _caller(request, auth)
    documents = schemas(policy.scim_base_url)
    return ScimResponse(list_response(documents, total=len(documents), page=Page.of(1, len(documents))))


@scim_router.get("/Schemas/{schema_id}")
async def get_schema(
    schema_id: str, request: Request, auth: FromDishka[ScimAuth], policy: FromDishka[DirectoryPolicy]
) -> Response:
    _ = await _caller(request, auth)
    for document in schemas(policy.scim_base_url):
        if str(document["id"]).lower() == schema_id.lower():
            return ScimResponse(document)
    raise ScimError(404, f"There is no schema {schema_id}.")


@scim_router.get("/Users")
async def list_users(
    request: Request,
    auth: FromDishka[ScimAuth],
    users: FromDishka[ScimUsers],
    filter_text: Annotated[str | None, Query(alias="filter", max_length=4096)] = None,
    start_index: Annotated[int | None, Query(alias="startIndex")] = None,
    count: Annotated[int | None, Query()] = None,
    attributes: Annotated[str | None, Query()] = None,
    excluded: Annotated[str | None, Query(alias="excludedAttributes")] = None,
) -> Response:
    _ = await _caller(request, auth)
    page = Page.of(start_index, count)
    resources, total = await users.list(filter_text=filter_text, page=page)
    return _many(resources, total, page, attributes, excluded)


@scim_router.post("/Users")
async def create_user(request: Request, auth: FromDishka[ScimAuth], users: FromDishka[ScimUsers]) -> Response:
    actor = await _caller(request, auth)
    return _one(await users.create(actor, await _body(request)), status_code=status.HTTP_201_CREATED)


@scim_router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    request: Request,
    auth: FromDishka[ScimAuth],
    users: FromDishka[ScimUsers],
    attributes: Annotated[str | None, Query()] = None,
    excluded: Annotated[str | None, Query(alias="excludedAttributes")] = None,
) -> Response:
    _ = await _caller(request, auth)
    return _one(await users.get(user_id), attributes=attributes, excluded=excluded)


@scim_router.put("/Users/{user_id}")
async def replace_user(
    user_id: str, request: Request, auth: FromDishka[ScimAuth], users: FromDishka[ScimUsers]
) -> Response:
    actor = await _caller(request, auth)
    return _one(await users.replace(actor, user_id, await _body(request)))


@scim_router.patch("/Users/{user_id}")
async def patch_user(
    user_id: str, request: Request, auth: FromDishka[ScimAuth], users: FromDishka[ScimUsers]
) -> Response:
    actor = await _caller(request, auth)
    return _one(await users.patch(actor, user_id, await _body(request)))


@scim_router.delete("/Users/{user_id}")
async def delete_user(
    user_id: str, request: Request, auth: FromDishka[ScimAuth], users: FromDishka[ScimUsers]
) -> Response:
    actor = await _caller(request, auth)
    await users.delete(actor, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@scim_router.get("/Groups")
async def list_groups(
    request: Request,
    auth: FromDishka[ScimAuth],
    groups: FromDishka[ScimGroups],
    filter_text: Annotated[str | None, Query(alias="filter", max_length=4096)] = None,
    start_index: Annotated[int | None, Query(alias="startIndex")] = None,
    count: Annotated[int | None, Query()] = None,
    attributes: Annotated[str | None, Query()] = None,
    excluded: Annotated[str | None, Query(alias="excludedAttributes")] = None,
) -> Response:
    _ = await _caller(request, auth)
    page = Page.of(start_index, count)
    resources, total = await groups.list(filter_text=filter_text, page=page)
    return _many(resources, total, page, attributes, excluded)


@scim_router.post("/Groups")
async def create_group(request: Request, auth: FromDishka[ScimAuth], groups: FromDishka[ScimGroups]) -> Response:
    actor = await _caller(request, auth)
    return _one(await groups.create(actor, await _body(request)), status_code=status.HTTP_201_CREATED)


@scim_router.get("/Groups/{group_id}")
async def get_group(
    group_id: str,
    request: Request,
    auth: FromDishka[ScimAuth],
    groups: FromDishka[ScimGroups],
    attributes: Annotated[str | None, Query()] = None,
    excluded: Annotated[str | None, Query(alias="excludedAttributes")] = None,
) -> Response:
    _ = await _caller(request, auth)
    return _one(await groups.get(group_id), attributes=attributes, excluded=excluded)


@scim_router.put("/Groups/{group_id}")
async def replace_group(
    group_id: str, request: Request, auth: FromDishka[ScimAuth], groups: FromDishka[ScimGroups]
) -> Response:
    actor = await _caller(request, auth)
    return _one(await groups.replace(actor, group_id, await _body(request)))


@scim_router.patch("/Groups/{group_id}")
async def patch_group(
    group_id: str, request: Request, auth: FromDishka[ScimAuth], groups: FromDishka[ScimGroups]
) -> Response:
    actor = await _caller(request, auth)
    return _one(await groups.patch(actor, group_id, await _body(request)))


@scim_router.delete("/Groups/{group_id}")
async def delete_group(
    group_id: str, request: Request, auth: FromDishka[ScimAuth], groups: FromDishka[ScimGroups]
) -> Response:
    actor = await _caller(request, auth)
    await groups.delete(actor, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
