"""The worker's half: answer one queued message as the person who asked, and tell their tabs as it goes."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Mapping
from typing import Any, cast

import orjson
from dishka import AsyncContainer

from agnostic_assistant.application.limits import AnswerLimits
from agnostic_assistant.application.ports import (
    AnswerEngine,
    AssistantStore,
    Connection,
    ContentDelta,
    EngineRequest,
    Failed,
    Finished,
    Outcome,
    Relay,
    ToolFinished,
    ToolStarted,
    Turn,
)
from agnostic_assistant.application.tools import Ledger, ToolBox, record
from agnostic_assistant.domain import events
from agnostic_assistant.domain.budget import estimate_tokens, month_of
from agnostic_assistant.domain.explainers import EXPLAINERS, Explainer
from agnostic_assistant.domain.model import Message, Status, ToolCallRecord
from agnostic_assistant.domain.prompts import Unavailable, quote, system_prompt
from agnostic_assistant.domain.settings import AiSettings
from agnostic_audit.facade import AuditEntry, AuditLog, actor_of
from agnostic_identity.facade import IdentityFacade
from agnostic_instances.facade import Instance, InstancesFacade
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.logging import get_logger
from agnostic_kernel.tools import Redaction, ToolSpec

log = get_logger(__name__)

CANCEL_POLL_SECONDS = 0.5
FENCE = re.compile(r"^```[\w-]*\s*|\s*```$")
JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def clean_output(explainer: Explainer | None, content: str) -> str:
    """Expressions and JSON come back without fences or chatter; anything unparseable is reported, not shown."""
    text = content.strip()
    if explainer is None or explainer.output == "text":
        return text
    text = FENCE.sub("", text).strip()
    if explainer.output == "expression":
        return text.strip("`").strip()
    match = JSON_OBJECT.search(text)
    if match is None:
        msg = "The model didn't return the structured answer it was asked for."
        raise ValueError(msg)
    value: object = json.loads(match.group(0))
    if not isinstance(value, dict):
        msg = "The model didn't return a JSON object."
        raise ValueError(msg)  # noqa: TRY004  (reported to the person, not a type error)
    return json.dumps(value)


class AnswerMessage:
    def __init__(
        self,
        store: AssistantStore,
        instances: InstancesFacade,
        identity: IdentityFacade,
        toolbox: ToolBox,
        engine: AnswerEngine,
        relay: Relay,
        audit: AuditLog,
        limits: AnswerLimits,
    ) -> None:
        self._store = store
        self._instances = instances
        self._identity = identity
        self._toolbox = toolbox
        self._engine = engine
        self._relay = relay
        self._audit = audit
        self._limits = limits

    async def __call__(self, container: AsyncContainer, message_id: str) -> None:
        message = await self._store.message(message_id)
        if message is None or message.status != "queued":
            return
        settings = await self._store.settings()
        model = settings.model_for(message.feature)
        if model is None or not settings.available(message.feature):
            await self._settle(message, None, Outcome("failed", "", (), (), None, 0, 0, "AI features were turned off."))
            return
        if not await self._store.start(message.id, model):
            await self._store.commit()
            return
        await self._store.commit()
        await self._relay.publish(message.id, events.STARTED, {"model": model})

        user = await self._identity.get_user(message.user_id)
        instance = await self._instances.get(message.instance_id)
        if user is None or instance is None:
            reason = "The person who asked no longer exists." if user is None else "The instance was removed."
            await self._settle(message, None, Outcome("failed", "", (), (), model, 0, 0, reason))
            return
        principal = Principal(kind="user", id=user.id, display_name=user.display_name, email=user.email, via="job")
        outcome = await self._answer(container, message, settings, model, principal, instance)
        await self._settle(message, principal, outcome)

    async def _answer(
        self,
        container: AsyncContainer,
        message: Message,
        settings: AiSettings,
        model: str,
        principal: Principal,
        instance: Instance,
    ) -> Outcome:
        ledger = Ledger()
        records: list[ToolCallRecord] = []
        specs, unavailable = await self._toolbox.usable(principal, instance)
        explainer = EXPLAINERS.kinds.get(message.kind) if message.kind != "ask" else None
        try:
            if explainer is None:
                request = await self._question(
                    container, message, settings, model, principal, instance, specs, unavailable, ledger
                )
            else:
                request = await self._explanation(
                    container,
                    message,
                    settings,
                    model,
                    principal,
                    instance,
                    explainer,
                    specs,
                    unavailable,
                    ledger,
                    records,
                )
        except LookupError as exc:
            return Outcome("failed", "", records, ledger.merged_sources(), model, 0, 0, str(exc))

        status, content, error, input_tokens, output_tokens = await self._stream(
            message, request, explainer, ledger, records
        )
        if status == "completed":
            try:
                content = clean_output(explainer, content)
            except ValueError as exc:
                status, error = "failed", str(exc)
        if not input_tokens and not output_tokens:
            input_tokens = estimate_tokens(request.instructions + request.question)
            output_tokens = estimate_tokens(content)
        return Outcome(status, content, records, ledger.merged_sources(), model, input_tokens, output_tokens, error)

    async def _stream(  # noqa: C901  (one branch per engine event)
        self,
        message: Message,
        request: EngineRequest,
        explainer: Explainer | None,
        ledger: Ledger,
        records: list[ToolCallRecord],
    ) -> tuple[Status, str, str | None, int, int]:
        """Runs the engine, relaying its events; returns ``(status, content, error, input, output tokens)``."""
        content = ""
        status: Status = "completed"
        error: str | None = None
        input_tokens = output_tokens = 0
        streams_text = explainer is None or explainer.output == "text"
        last_poll = time.monotonic()
        try:
            async with asyncio.timeout(self._limits.answer_timeout_seconds):
                async for event in self._engine.run(request):
                    match event:
                        case ToolStarted(id=tool_id, name=name):
                            await self._relay.publish(message.id, events.TOOL_STARTED, {"id": tool_id, "name": name})
                        case ToolFinished(id=tool_id, name=name, duration_ms=duration):
                            item = record(tool_id, name, ledger.outcome(name), duration)
                            records.append(item)
                            await self._relay.publish(message.id, events.TOOL_COMPLETED, _tool_event(item))
                        case ContentDelta(text=text):
                            content += text
                            if streams_text:
                                await self._relay.publish(message.id, events.CONTENT, {"delta": text})
                        case Finished():
                            content = event.content or content
                            input_tokens, output_tokens = event.input_tokens, event.output_tokens
                        case Failed(reason=reason):
                            status, error = "failed", reason
                    if time.monotonic() - last_poll > CANCEL_POLL_SECONDS:
                        last_poll = time.monotonic()
                        if await self._relay.cancel_requested(message.id):
                            return "cancelled", content, None, input_tokens, output_tokens
        except TimeoutError:
            status, error = "failed", f"The answer took longer than {self._limits.answer_timeout_seconds:g} s."
        return status, content, error, input_tokens, output_tokens

    def _connection(self, settings: AiSettings, api_key: str | None) -> Connection:
        return Connection(settings.endpoint, api_key, settings.api_version, settings.temperature)

    async def _question(
        self,
        container: AsyncContainer,
        message: Message,
        settings: AiSettings,
        model: str,
        principal: Principal,
        instance: Instance,
        specs: list[ToolSpec],
        unavailable: list[Unavailable],
        ledger: Ledger,
    ) -> EngineRequest:
        question_id = str(message.subject.get("question_id") or "")
        asked = await self._store.message(question_id, attachments=True)
        if asked is None:
            msg = "The question was deleted before it was answered."
            raise LookupError(msg)
        history: list[Turn] = []
        if message.conversation_id:
            earlier = [
                m
                for m in await self._store.messages(message.conversation_id)
                if m.id not in {asked.id, message.id} and m.status == "completed" and m.created_at <= asked.created_at
            ]
            history = (
                [Turn(m.role, m.content) for m in earlier[-self._limits.history_messages :]]
                if self._limits.history_messages
                else []
            )
        parts = [asked.content]
        if context := message.subject.get("context"):
            parts.append(quote("page", f"The person is looking at {context}."))
        parts.extend(
            quote(f"attachment:{a.name}", a.text or "")
            for a in asked.attachments
            if not a.is_image and a.text is not None
        )
        tools = self._toolbox.bind(
            container,
            principal,
            instance,
            specs,
            redaction=Redaction(settings.redact_tool_args, settings.redact_user_messages),
            limits=self._limits.tools,
            ledger=ledger,
        )
        return EngineRequest(
            model=model,
            connection=self._connection(settings, await self._store.api_key()),
            instructions=system_prompt(
                instance_name=instance.display_name,
                now=utcnow(),
                person=principal.display_name,
                unavailable=unavailable,
            ),
            question="\n\n".join(parts),
            history=history,
            images=[a for a in asked.attachments if a.is_image],
            tools=tools,
            max_tool_calls=self._limits.max_tool_calls,
        )

    async def _explanation(
        self,
        container: AsyncContainer,
        message: Message,
        settings: AiSettings,
        model: str,
        principal: Principal,
        instance: Instance,
        explainer: Explainer,
        specs: list[ToolSpec],
        unavailable: list[Unavailable],
        ledger: Ledger,
        records: list[ToolCallRecord],
    ) -> EngineRequest:
        """Explanations get their facts up front and no tools: they describe one thing, they don't explore."""
        subject = cast("Mapping[str, Any]", message.subject.get("subject") or {})
        material = message.subject.get("material")
        usable = {spec.name: spec for spec in specs}
        redaction = Redaction(settings.redact_tool_args, settings.redact_user_messages)
        parts = [f"{explainer.label} for: {orjson.dumps(dict(subject)).decode()}"]
        for index, (name, arguments) in enumerate(explainer.calls(subject, has_material=material is not None)):
            tool_id = f"gather_{index}"
            await self._relay.publish(message.id, events.TOOL_STARTED, {"id": tool_id, "name": name})
            started = time.monotonic()
            spec = usable.get(name)
            if spec is None:
                scope = self._toolbox.scope_of(name)
                detail = f"needs {scope}" if scope else "not available"
                parts.append(quote(f"tool:{name}", orjson.dumps({"denied": True, "detail": detail}).decode()))
                item = ToolCallRecord(tool_id, name, "denied", 0, detail)
            else:
                parts.append(
                    await self._toolbox.call(
                        container,
                        principal,
                        instance,
                        spec,
                        arguments,
                        redaction=redaction,
                        limits=self._limits.tools,
                        ledger=ledger,
                    )
                )
                item = record(tool_id, name, ledger.outcome(name), round((time.monotonic() - started) * 1000))
            records.append(item)
            await self._relay.publish(message.id, events.TOOL_COMPLETED, _tool_event(item))
        if material is not None:
            parts.append(quote("page", orjson.dumps(redaction.apply(material), default=str).decode()))
        return EngineRequest(
            model=model,
            connection=self._connection(settings, await self._store.api_key()),
            instructions=system_prompt(
                instance_name=instance.display_name,
                now=utcnow(),
                person=principal.display_name,
                unavailable=unavailable,
                task=explainer.task,
            ),
            question="\n\n".join(parts),
            max_tool_calls=0,
        )

    async def _settle(self, message: Message, principal: Principal | None, outcome: Outcome) -> None:
        await self._store.finish(message.id, outcome)
        if principal is not None:
            await self._store.add_usage(
                month_of(utcnow()), message.user_id, message.feature, outcome.input_tokens, outcome.output_tokens
            )
            await self._audit_answer(message, principal, outcome)
        await self._store.commit()
        sources = [{"kind": s.kind, "label": s.label, "path": s.path} for s in outcome.sources]
        await self._relay.publish(message.id, events.SOURCES, {"sources": sources})
        if outcome.status == "completed":
            await self._relay.publish(
                message.id,
                events.COMPLETED,
                {
                    "content": outcome.content,
                    "model": outcome.model,
                    "input_tokens": outcome.input_tokens,
                    "output_tokens": outcome.output_tokens,
                },
            )
        elif outcome.status == "cancelled":
            await self._relay.publish(message.id, events.CANCELLED, {"content": outcome.content})
        else:
            await self._relay.publish(message.id, events.FAILED, {"reason": outcome.error or "The answer failed."})
        log.info(
            "assistant.answered",
            message=message.id,
            kind=message.kind,
            status=outcome.status,
            tools=len(outcome.tool_calls),
            tokens=outcome.input_tokens + outcome.output_tokens,
        )

    async def _audit_answer(self, message: Message, principal: Principal, outcome: Outcome) -> None:
        settings = await self._store.settings()
        tools = ", ".join(dict.fromkeys(call.name for call in outcome.tool_calls)) or "no tools"
        fields = {
            "kind": message.kind,
            "tools": tools,
            "sources": str(len(outcome.sources)),
            "model": outcome.model or "none",
            "status": outcome.status,
            "tokens": str(outcome.input_tokens + outcome.output_tokens),
        }
        if settings.audit_question_text and message.kind == "ask":
            question_id = str(message.subject.get("question_id") or "")
            if (asked := await self._store.message(question_id)) is not None:
                fields["question"] = asked.content[:500]
        lines = [{"op": "note", "text": f"{source.label} · {source.path}"} for source in outcome.sources]
        _ = await self._audit.record(
            AuditEntry(
                action="assistant.ask" if message.kind == "ask" else "assistant.explain",
                actor=actor_of(principal),
                resource_kind="assistant_answer",
                resource_id=message.id,
                resource_display=message.kind,
                instance_id=message.instance_id,
                decision="allowed",
                scope_checked="assistant:use",
                fields=fields,
                diff={"title": "Sources", "lines": lines, "note": None} if lines else None,
                via="assistant",
            )
        )


def _tool_event(item: ToolCallRecord) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "status": item.status,
        "duration_ms": item.duration_ms,
        "detail": item.detail,
    }
