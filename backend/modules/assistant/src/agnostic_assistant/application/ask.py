"""Questions and explanations are accepted here and answered by a worker; the browser follows the answer's events."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agnostic_assistant.application.attachments import Upload, extract
from agnostic_assistant.application.limits import USE_SCOPE, Admission, AnswerLimits, require_feature
from agnostic_assistant.application.ports import AssistantStore, NewMessage
from agnostic_assistant.application.tasks import ANSWER_TASK
from agnostic_assistant.domain.explainers import EXPLAINERS, ExplainerError, subject_key
from agnostic_assistant.domain.model import title_of
from agnostic_gateway.facade import GatewayFacade
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import NotFoundError, ValidationFailedError
from agnostic_kernel.jobs import JobQueue

CONTEXT = re.compile(r"^[a-z_]{2,20}:[\w.:@/\-]{1,200}$")
"""What the person is looking at: ``trace:8f3a…``, ``schedule:sch_1``, ``page:traces``."""


@dataclass(frozen=True, slots=True)
class Accepted:
    message_id: str
    conversation_id: str | None
    reused: bool = False


class Ask:
    def __init__(
        self,
        store: AssistantStore,
        gateway: GatewayFacade,
        authorizer: Authorizer,
        admission: Admission,
        queue: JobQueue,
        limits: AnswerLimits,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._authorizer = authorizer
        self._admission = admission
        self._queue = queue
        self._limits = limits

    async def question(
        self,
        principal: Principal,
        instance_ref: str,
        question: str,
        *,
        conversation_id: str | None,
        context: str | None,
        uploads: Sequence[Upload] = (),
    ) -> Accepted:
        text = question.strip()
        if not text:
            raise ValidationFailedError("Ask a question.", extra={"fields": ["question"]})
        if len(text) > self._limits.max_question_chars:
            raise ValidationFailedError(
                f"Keep the question under {self._limits.max_question_chars:,} characters; attach longer text.",
                extra={"fields": ["question"]},
            )
        if context is not None and not CONTEXT.fullmatch(context):
            raise ValidationFailedError("Unknown page context.", extra={"fields": ["context"]})
        instance = await self._gateway.instance(instance_ref)
        _ = await self._authorizer.require(principal, USE_SCOPE)
        settings = await self._store.settings()
        require_feature(settings, "assistant")
        attachments = extract(uploads, provider=settings.provider, limits=self._limits.attachments)
        await self._admission.admit(principal, settings)

        if conversation_id is not None:
            conversation = await self._store.conversation(conversation_id)
            if conversation is None or conversation.user_id != principal.id or conversation.instance_id != instance.id:
                raise NotFoundError("That conversation doesn't exist.")
            await self._store.touch_conversation(conversation.id)
        else:
            conversation = await self._store.create_conversation(principal.id, instance.id, title_of(text))
        asked = await self._store.add_message(
            NewMessage(
                conversation_id=conversation.id,
                user_id=principal.id,
                instance_id=instance.id,
                role="user",
                feature="assistant",
                kind="ask",
                subject={"context": context} if context else {},
                content=text,
                status="completed",
                attachments=attachments,
            )
        )
        answer = await self._store.add_message(
            NewMessage(
                conversation_id=conversation.id,
                user_id=principal.id,
                instance_id=instance.id,
                role="assistant",
                feature="assistant",
                kind="ask",
                subject={"question_id": asked.id, **({"context": context} if context else {})},
                content="",
                status="queued",
            )
        )
        await self._store.commit()
        _ = await self._queue.defer(ANSWER_TASK, message_id=answer.id)
        return Accepted(answer.id, conversation.id)

    async def explanation(
        self,
        principal: Principal,
        instance_ref: str,
        kind: str,
        subject: Mapping[str, Any],
        *,
        material: object = None,
        regenerate: bool = False,
    ) -> Accepted:
        try:
            explainer = EXPLAINERS.get(kind)
            explainer.check(subject, material)
        except ExplainerError as exc:
            raise ValidationFailedError(str(exc)) from exc
        instance = await self._gateway.instance(instance_ref)
        _ = await self._authorizer.require(principal, USE_SCOPE)
        settings = await self._store.settings()
        require_feature(settings, explainer.feature)
        key = subject_key(kind, subject, material)
        if not regenerate and (found := await self._store.reusable(principal.id, instance.id, kind, key)):
            return Accepted(found.id, None, reused=True)
        await self._admission.admit(principal, settings)
        answer = await self._store.add_message(
            NewMessage(
                conversation_id=None,
                user_id=principal.id,
                instance_id=instance.id,
                role="assistant",
                feature=explainer.feature,
                kind=kind,
                subject={"subject": dict(subject), "material": material},
                content="",
                status="queued",
                subject_key=key,
            )
        )
        await self._store.commit()
        _ = await self._queue.defer(ANSWER_TASK, message_id=answer.id)
        return Accepted(answer.id, None)
