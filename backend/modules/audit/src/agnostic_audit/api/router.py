"""HTTP routes: ``/api/v1/audit``."""

from datetime import datetime
from typing import Annotated, Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Depends, Query

from agnostic_audit.api.schemas import AuditActionOut, AuditEventOut
from agnostic_audit.application.ports import EventQuery
from agnostic_audit.application.use_cases import AuditVocabulary, GetEvent, ListEvents
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.pagination import Page, PageParams, encode_cursor, page_params

router = APIRouter(route_class=DishkaRoute)

READ_SCOPE = "audit:read"


@router.get("/events", summary="Audit events, newest first")
async def list_events(
    params: Annotated[PageParams, Depends(page_params)],
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    use_case: FromDishka[ListEvents],
    actor: Annotated[str | None, Query(description="Actor id (usr_…, sa:…, system)")] = None,
    action: Annotated[str | None, Query(description="Action, or a prefix ending in * (gateway.*)")] = None,
    decision: Literal["allowed", "denied", "n_a"] | None = None,
    instance: Annotated[str | None, Query(description="Instance id")] = None,
    resource: Annotated[str | None, Query(description="Resource id")] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Page[AuditEventOut]:
    _ = await authorizer.require(principal, READ_SCOPE)
    position = params.position()
    after = None
    if position and isinstance(position.get("t"), str) and isinstance(position.get("id"), str):
        after = (str(position["t"]), str(position["id"]))
    query = EventQuery(
        actor_id=actor,
        action=action,
        decision=decision,
        instance_id=instance,
        resource_id=resource,
        since=since,
        until=until,
    )
    page = await use_case(query, params.limit, after)
    return Page[AuditEventOut](
        data=[AuditEventOut.from_domain(event) for event in page.items],
        next_cursor=(
            encode_cursor({"t": page.next_after.occurred_at.isoformat(), "id": page.next_after.id})
            if page.next_after
            else None
        ),
    )


@router.get("/events/{event_id}", summary="One audit event")
async def get_event(
    event_id: str,
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    use_case: FromDishka[GetEvent],
) -> AuditEventOut:
    _ = await authorizer.require(principal, READ_SCOPE)
    return AuditEventOut.from_domain(await use_case(event_id))


@router.get("/actions", summary="The audit vocabulary: every action and its summary template")
async def list_actions(
    principal: FromDishka[Principal],
    authorizer: FromDishka[Authorizer],
    vocabulary: FromDishka[AuditVocabulary],
) -> list[AuditActionOut]:
    _ = await authorizer.require(principal, READ_SCOPE)
    return [
        AuditActionOut(action=action, summary_template=template)
        for action, template in sorted(vocabulary.actions().items())
    ]
