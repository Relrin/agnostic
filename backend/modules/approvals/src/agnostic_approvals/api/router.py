"""HTTP routes: ``/api/v1/instances/{instance}/approvals`` and the org-wide ``/api/v1/approvals/routes``."""

from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Response

from agnostic_approvals.api.schemas import (
    ApprovalCountsOut,
    ApprovalDetailOut,
    ApprovalsPageOut,
    CountOut,
    DecideIn,
    DecideOut,
    PolicyIn,
    PolicyOut,
    RouteIn,
    RouteOut,
)
from agnostic_approvals.application.decide import DecideApproval, DecideRequest
from agnostic_approvals.application.inbox import ApprovalsInbox, Filters
from agnostic_approvals.application.poller import ApprovalsCountPoller, current_count
from agnostic_approvals.application.routing import ApprovalRouting
from agnostic_gateway.facade import GatewayFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.ephemeral import EphemeralStore

router = APIRouter(route_class=DishkaRoute)
org_router = APIRouter(route_class=DishkaRoute)


@router.get("/{instance}/approvals", summary="Approvals by tab and filters, newest first (needs approvals:read)")
async def list_approvals(
    instance: str,
    principal: FromDishka[Principal],
    inbox: FromDishka[ApprovalsInbox],
    status: Literal["pending", "approved", "rejected", "expired", "cancelled"] = "pending",
    tool: Annotated[str | None, Query(max_length=200)] = None,
    source_kind: Literal["agent", "team", "workflow", "schedule"] | None = None,
    source_id: Annotated[str | None, Query(max_length=200)] = None,
    user_id: Annotated[str | None, Query(max_length=200)] = None,
    schedule_id: Annotated[str | None, Query(max_length=200)] = None,
    type: Literal["blocking", "audit"] | None = None,  # noqa: A002
    q: Annotated[str | None, Query(max_length=260)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ApprovalsPageOut:
    filters = Filters(
        status=status,
        tool=tool,
        source_kind=source_kind,
        source_id=source_id,
        user_id=user_id,
        schedule_id=schedule_id,
        kind=type,
        q=q,
    )
    return ApprovalsPageOut.of(await inbox.list(principal, instance, filters, page=page, limit=limit))


@router.get("/{instance}/approvals/counts", summary="How many approvals each tab holds (needs approvals:read)")
async def approval_counts(
    instance: str, principal: FromDishka[Principal], inbox: FromDishka[ApprovalsInbox]
) -> ApprovalCountsOut:
    return ApprovalCountsOut.of(await inbox.counts(principal, instance))


@router.get(
    "/{instance}/approvals/count",
    summary="Pending approvals on the instance (the nav badge; live updates arrive as approvals.count events)",
)
async def count(
    instance: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    gateway: FromDishka[GatewayFacade],
    store: FromDishka[EphemeralStore],
    poller: FromDishka[ApprovalsCountPoller],
) -> CountOut:
    target = await gateway.instance(instance)
    _ = await authorizer.require(principal, "approvals:read", instance_id=target.id)
    value = await current_count(store, target.id)
    if value is None:
        value = await poller.poll(target, force=True)
    return CountOut(instance_id=target.id, count=value, available=value is not None)


@router.get("/{instance}/approvals/routes", summary="Routing rules of the instance, then the org-wide ones")
async def list_routes(
    instance: str, principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting]
) -> list[RouteOut]:
    return [RouteOut.of(view) for view in await routing.list(principal, instance)]


@router.post("/{instance}/approvals/routes", status_code=201, summary="Route approvals to members or roles")
async def create_route(
    instance: str, principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting], body: RouteIn
) -> RouteOut:
    return RouteOut.of(await routing.create(principal, instance, body.draft()))


@router.get("/{instance}/approvals/policy", summary="Whether expiry stops runs on this instance, and its TTL")
async def get_policy(
    instance: str, principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting]
) -> PolicyOut:
    _, policy = await routing.policy(principal, instance)
    return PolicyOut.of(policy)


@router.put("/{instance}/approvals/policy", summary="Change the expiry policy (Instance admin; audited)")
async def put_policy(
    instance: str, principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting], body: PolicyIn
) -> PolicyOut:
    _, policy = await routing.set_policy(
        principal, instance, enforce_expiry=body.enforce_expiry, ttl_hours=body.ttl_hours
    )
    return PolicyOut.of(policy)


@router.get(
    "/{instance}/approvals/{approval_id}",
    summary="One approval with its context and timeline; records that you viewed it (needs approvals:read)",
)
async def get_approval(
    instance: str, approval_id: str, principal: FromDishka[Principal], inbox: FromDishka[ApprovalsInbox]
) -> ApprovalDetailOut:
    return ApprovalDetailOut.of_detail(await inbox.detail(principal, instance, approval_id))


@router.post(
    "/{instance}/approvals/{approval_id}/decide",
    summary="Approve or reject a paused run's approval, then continue the run (needs approvals:write)",
)
async def decide(
    instance: str,
    approval_id: str,
    body: DecideIn,
    principal: FromDishka[Principal],
    use_case: FromDishka[DecideApproval],
) -> DecideOut:
    request = DecideRequest(decision=body.decision, note=body.note, edited_args=body.edited_args)
    return DecideOut.from_result(await use_case(principal, instance, approval_id, request))


@org_router.get("/approvals/routes", summary="Org-wide routing rules (needs settings:write)")
async def list_org_routes(principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting]) -> list[RouteOut]:
    return [RouteOut.of(view) for view in await routing.list(principal, None)]


@org_router.get("/approvals/routes/by-group/{group_id}", summary="Routing rules naming a group, on any instance")
async def list_group_routes(
    group_id: str, principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting]
) -> list[RouteOut]:
    return [RouteOut.of(view) for view in await routing.for_group(principal, group_id)]


@org_router.post("/approvals/routes", status_code=201, summary="Add an org-wide routing rule (needs settings:write)")
async def create_org_route(
    principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting], body: RouteIn
) -> RouteOut:
    return RouteOut.of(await routing.create(principal, None, body.draft()))


@org_router.put("/approvals/routes/{route_id}", summary="Change a routing rule")
async def update_route(
    route_id: str, principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting], body: RouteIn
) -> RouteOut:
    return RouteOut.of(await routing.update(principal, route_id, body.draft()))


@org_router.delete("/approvals/routes/{route_id}", status_code=204, summary="Remove a routing rule")
async def delete_route(
    route_id: str, principal: FromDishka[Principal], routing: FromDishka[ApprovalRouting]
) -> Response:
    await routing.delete(principal, route_id)
    return Response(status_code=204)
