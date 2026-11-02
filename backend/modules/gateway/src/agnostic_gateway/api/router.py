"""HTTP routes: ``ANY /api/v1/instances/{instance}/os/{path}`` (passthrough) and ``/api/v1/gateway/policies``."""

from collections.abc import AsyncIterator

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from agnostic_gateway.application.ports import RoutePolicyRepository
from agnostic_gateway.application.proxy import Gateway, GatewaySettingsView, PolicyTableCache, ProxyRequest
from agnostic_gateway.application.streaming import PayloadTooLargeError, limited
from agnostic_gateway.domain.policies import is_upload
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import AppError

router = APIRouter(route_class=DishkaRoute)
policies_router = APIRouter(route_class=DishkaRoute)

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class RequestTooLargeError(AppError):
    status = 413
    code = "payload_too_large"
    title = "The request body is too large"


async def _body(request: Request, max_bytes: int) -> AsyncIterator[bytes]:
    async for chunk in limited(request.stream(), max_bytes):
        yield chunk


@router.api_route(
    "/{instance}/os/{path:path}",
    methods=METHODS,
    summary="Call any AgentOS route on the instance as yourself (scoped JWT, audited)",
    response_class=StreamingResponse,
    # A raw proxy: the AgentOS OpenAPI describes these routes; clients call it with a plain fetch.
    include_in_schema=False,
)
async def passthrough(
    instance: str,
    path: str,
    request: Request,
    principal: FromDishka[Principal],
    gateway: FromDishka[Gateway],
    config: FromDishka[GatewaySettingsView],
    session: FromDishka[AsyncSession],
) -> StreamingResponse:
    has_body = request.method not in {"GET", "HEAD", "OPTIONS", "DELETE"} or "content-length" in request.headers
    limit = config.max_upload_bytes if is_upload(request.method, path) else config.max_body_bytes
    proxy_request = ProxyRequest(
        method=request.method,
        path=path,
        params=list(request.query_params.multi_items()),
        headers=list(request.headers.items()),
        body=_body(request, limit) if has_body else None,
        scheme=request.url.scheme,
        host=request.headers.get("host"),
    )
    try:
        response = await gateway.handle(principal, instance, proxy_request)
    except PayloadTooLargeError as exc:
        raise RequestTooLargeError(str(exc)) from exc
    finally:
        # Streams can last minutes: don't hold a database connection while they do.
        await session.close()
    return StreamingResponse(
        response.body,
        status_code=response.status,
        headers=response.headers,
        background=BackgroundTask(response.close),
    )


class RoutePolicyOut(BaseModel):
    method: str
    pattern: str
    scopes: list[str]
    cache_ttl_s: int
    audit_level: str
    rate_bucket: str
    list_filter: bool
    source: str


@policies_router.get("/policies", summary="The route policy table: which scopes each AgentOS route needs")
async def list_policies(
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    cache: FromDishka[PolicyTableCache],
    repository: FromDishka[RoutePolicyRepository],
) -> list[RoutePolicyOut]:
    _ = await authorizer.require(principal, "os:read")
    table = await cache.get(repository)
    return [
        RoutePolicyOut(
            method=policy.method,
            pattern=policy.pattern,
            scopes=list(policy.scopes),
            cache_ttl_s=policy.cache_ttl_s,
            audit_level=policy.audit_level,
            rate_bucket=policy.rate_bucket,
            list_filter=policy.list_filter,
            source=policy.source,
        )
        for policy in sorted(table.policies, key=lambda p: (p.pattern, p.method))
    ]
