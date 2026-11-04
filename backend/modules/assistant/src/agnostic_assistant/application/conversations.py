"""A person's own conversations and answers: nobody else, admins included, can read them here."""

from __future__ import annotations

from dataclasses import dataclass

from agnostic_assistant.application.ports import AssistantStore, Relay
from agnostic_assistant.domain.model import Conversation, Message
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_gateway.facade import GatewayFacade
from agnostic_kernel.auth import Principal
from agnostic_kernel.errors import NotFoundError

LIST_LIMIT = 50


@dataclass(frozen=True, slots=True)
class Thread:
    conversation: Conversation
    messages: list[Message]


class Conversations:
    def __init__(self, store: AssistantStore, gateway: GatewayFacade, relay: Relay, audit: AuditLog) -> None:
        self._store = store
        self._gateway = gateway
        self._relay = relay
        self._audit = audit

    async def list(self, principal: Principal, instance_ref: str) -> list[Conversation]:
        instance = await self._gateway.instance(instance_ref)
        return await self._store.conversations(principal.id, instance.id, LIST_LIMIT)

    async def _own(self, principal: Principal, instance_ref: str, conversation_id: str) -> Conversation:
        instance = await self._gateway.instance(instance_ref)
        conversation = await self._store.conversation(conversation_id)
        if conversation is None or conversation.user_id != principal.id or conversation.instance_id != instance.id:
            raise NotFoundError("That conversation doesn't exist.")
        return conversation

    async def thread(self, principal: Principal, instance_ref: str, conversation_id: str) -> Thread:
        conversation = await self._own(principal, instance_ref, conversation_id)
        return Thread(conversation, await self._store.messages(conversation.id))

    async def delete(self, principal: Principal, instance_ref: str, conversation_id: str) -> None:
        conversation = await self._own(principal, instance_ref, conversation_id)
        await self._store.delete_conversation(conversation.id)
        _ = await self._audit.record(
            AuditEntry(
                action="assistant.conversation.delete",
                actor=actor_of(principal),
                resource_kind="assistant_conversation",
                resource_id=conversation.id,
                resource_display=conversation.title,
                instance_id=conversation.instance_id,
                decision="allowed",
                fields={"title": conversation.title},
            )
        )
        await self._store.commit()

    async def message(self, principal: Principal, instance_ref: str, message_id: str) -> Message:
        instance = await self._gateway.instance(instance_ref)
        message = await self._store.message(message_id)
        if message is None or message.user_id != principal.id or message.instance_id != instance.id:
            raise NotFoundError("That answer doesn't exist.")
        return message

    async def cancel(self, principal: Principal, instance_ref: str, message_id: str) -> Message:
        message = await self.message(principal, instance_ref, message_id)
        if message.settled:
            return message
        if not await self._store.cancel(message.id):
            await self._relay.request_cancel(message.id)
        await self._store.commit()
        return await self.message(principal, instance_ref, message_id)
