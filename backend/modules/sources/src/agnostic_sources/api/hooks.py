"""Webhook receivers at ``/hooks/{github,gitlab,gitea,forgejo}``: no session, a signature instead."""

from typing import Literal

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Request, Response, status

from agnostic_kernel.errors import ValidationFailedError
from agnostic_sources.application.webhooks import WebhookIntake
from agnostic_sources.settings import SourcesSettings

hooks_router = APIRouter(route_class=DishkaRoute, include_in_schema=False)


@hooks_router.post("/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def receive(
    provider: Literal["github", "gitlab", "gitea", "forgejo"],
    request: Request,
    intake: FromDishka[WebhookIntake],
    settings: FromDishka[SourcesSettings],
) -> Response:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > settings.webhook_max_bytes:
            raise ValidationFailedError("The webhook body is too large.")
    _ = await intake.receive(provider, dict(request.headers), bytes(body))
    return Response(status_code=status.HTTP_202_ACCEPTED)
