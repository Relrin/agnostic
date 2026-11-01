"""HTTP routes: ``/api/v1/instances/{instance}/approvals``."""

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter

from agnostic_approvals.api.schemas import CountOut, DecideIn, DecideOut
from agnostic_approvals.application.decide import DecideApproval, DecideRequest
from agnostic_approvals.application.poller import ApprovalsCountPoller, current_count
from agnostic_gateway.facade import GatewayFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.ephemeral import EphemeralStore

router = APIRouter(route_class=DishkaRoute)


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
