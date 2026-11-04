"""HTTP routes: the org's AI features, your status, and questions/explanations answered by the worker."""

from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, File, Form, Header, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agnostic_assistant.api.schemas import (
    AcceptedOut,
    AiSettingsIn,
    AiSettingsOut,
    AssistantStatusOut,
    ConnectionCheckIn,
    ConnectionCheckOut,
    ConversationOut,
    ExplanationIn,
    MessageOut,
    ThreadOut,
)
from agnostic_assistant.api.stream import answer_events
from agnostic_assistant.application.ask import Accepted, Ask
from agnostic_assistant.application.attachments import Upload
from agnostic_assistant.application.configuration import AiFeatures
from agnostic_assistant.application.conversations import Conversations
from agnostic_assistant.application.ports import Relay
from agnostic_assistant.settings import AssistantSettings
from agnostic_kernel.auth import Principal

router = APIRouter(route_class=DishkaRoute)
org_router = APIRouter(route_class=DishkaRoute)

BASE = "/{instance}/assistant"
HEARTBEAT_SECONDS = 15.0


def _accepted(accepted: Accepted) -> AcceptedOut:
    return AcceptedOut(message_id=accepted.message_id, conversation_id=accepted.conversation_id, reused=accepted.reused)


@org_router.get("/assistant/status", summary="Which AI features work for you right now, and the token budget")
async def get_status(principal: FromDishka[Principal], features: FromDishka[AiFeatures]) -> AssistantStatusOut:
    return AssistantStatusOut.of(await features.status(principal))


@org_router.get("/assistant/settings", summary="the org's AI features (needs settings:read)")
async def get_settings(principal: FromDishka[Principal], features: FromDishka[AiFeatures]) -> AiSettingsOut:
    return AiSettingsOut.of(await features.get(principal))


@org_router.put(
    "/assistant/settings",
    summary="Change AI features: only the fields sent (needs settings:write; a new API key needs a recent sign-in)",
)
async def update_settings(
    body: AiSettingsIn, principal: FromDishka[Principal], features: FromDishka[AiFeatures]
) -> AiSettingsOut:
    saved = await features.update(principal, body.changes(), api_key=body.api_key, version=body.version)
    return AiSettingsOut.of(saved)


@org_router.post(
    "/assistant/settings/check", summary="Send the configured model one tiny prompt and report what happened"
)
async def check_connection(
    body: ConnectionCheckIn, principal: FromDishka[Principal], features: FromDishka[AiFeatures]
) -> ConnectionCheckOut:
    return ConnectionCheckOut.of(await features.check(principal, body.feature))


@router.post(
    f"{BASE}/questions",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask your OS: queue a question; follow the answer at …/messages/{message_id}/events",
)
async def ask_question(
    instance: str,
    principal: FromDishka[Principal],
    ask: FromDishka[Ask],
    question: Annotated[str, Form(max_length=50_000)],
    conversation_id: Annotated[str | None, Form(max_length=40)] = None,
    context: Annotated[str | None, Form(max_length=220, description="What you're looking at: trace:<id>, …")] = None,
    files: Annotated[list[UploadFile] | None, File(description="Logs or screenshots")] = None,
) -> AcceptedOut:
    uploads = [
        Upload(file.filename or "attachment", file.content_type or "application/octet-stream", await file.read())
        for file in files or []
    ]
    accepted = await ask.question(
        principal, instance, question, conversation_id=conversation_id, context=context, uploads=uploads
    )
    return _accepted(accepted)


@router.post(
    f"{BASE}/explanations",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a generated explanation or suggestion next to a page's own text (reused unless regenerate)",
)
async def explain(
    instance: str, body: ExplanationIn, principal: FromDishka[Principal], ask: FromDishka[Ask]
) -> AcceptedOut:
    accepted = await ask.explanation(
        principal, instance, body.kind, body.subject, material=body.material, regenerate=body.regenerate
    )
    return _accepted(accepted)


@router.get(f"{BASE}/conversations", summary="Your conversations on this instance, most recent first")
async def list_conversations(
    instance: str, principal: FromDishka[Principal], conversations: FromDishka[Conversations]
) -> list[ConversationOut]:
    return [ConversationOut.of(item) for item in await conversations.list(principal, instance)]


@router.get(f"{BASE}/conversations/{{conversation_id}}", summary="One of your conversations with its messages")
async def get_conversation(
    instance: str, conversation_id: str, principal: FromDishka[Principal], conversations: FromDishka[Conversations]
) -> ThreadOut:
    thread = await conversations.thread(principal, instance, conversation_id)
    return ThreadOut(
        conversation=ConversationOut.of(thread.conversation),
        messages=[MessageOut.of(message) for message in thread.messages],
    )


@router.delete(
    f"{BASE}/conversations/{{conversation_id}}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a conversation"
)
async def delete_conversation(
    instance: str, conversation_id: str, principal: FromDishka[Principal], conversations: FromDishka[Conversations]
) -> Response:
    await conversations.delete(principal, instance, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(f"{BASE}/messages/{{message_id}}", summary="An answer or explanation as it stands")
async def get_message(
    instance: str, message_id: str, principal: FromDishka[Principal], conversations: FromDishka[Conversations]
) -> MessageOut:
    return MessageOut.of(await conversations.message(principal, instance, message_id))


@router.get(
    f"{BASE}/messages/{{message_id}}/events",
    summary="Follow an answer as it is written (text/event-stream; resumes from Last-Event-ID)",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def follow_message(
    instance: str,
    message_id: str,
    principal: FromDishka[Principal],
    conversations: FromDishka[Conversations],
    relay: FromDishka[Relay],
    settings: FromDishka[AssistantSettings],
    session: FromDishka[AsyncSession],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=64)] = None,
) -> StreamingResponse:
    message = await conversations.message(principal, instance, message_id)
    # Answers take a while: don't hold a database connection while the stream is open.
    await session.close()
    return StreamingResponse(
        answer_events(
            message,
            relay,
            last_event_id=last_event_id,
            heartbeat=HEARTBEAT_SECONDS,
            max_seconds=settings.answer_timeout_seconds + 60,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(f"{BASE}/messages/{{message_id}}/cancel", summary="Stop an answer that is still being written")
async def cancel_message(
    instance: str, message_id: str, principal: FromDishka[Principal], conversations: FromDishka[Conversations]
) -> MessageOut:
    return MessageOut.of(await conversations.cancel(principal, instance, message_id))
