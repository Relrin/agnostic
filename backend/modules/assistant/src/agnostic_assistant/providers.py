"""Dependency wiring of the assistant module."""

from __future__ import annotations

from dishka import (
    Provider,
    Scope,
    provide,  # pyright: ignore[reportUnknownVariableType]
)

from agnostic_assistant.application.answer import AnswerMessage
from agnostic_assistant.application.ask import Ask
from agnostic_assistant.application.attachments import AttachmentLimits
from agnostic_assistant.application.configuration import AiFeatures
from agnostic_assistant.application.conversations import Conversations
from agnostic_assistant.application.housekeeping import Housekeeping
from agnostic_assistant.application.limits import Admission, AnswerLimits
from agnostic_assistant.application.ports import AnswerEngine, AssistantStore, Relay
from agnostic_assistant.application.tools import ToolBox, ToolCatalog, ToolLimits
from agnostic_assistant.facade import AssistantStatusReader, AssistantStatusReaderImpl
from agnostic_assistant.infrastructure.engine import AgnoEngine
from agnostic_assistant.infrastructure.models import ModelFactory
from agnostic_assistant.infrastructure.relay import BusRelay
from agnostic_assistant.infrastructure.repository import SqlAssistantStore
from agnostic_assistant.settings import AssistantSettings
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.events import EventBus
from agnostic_kernel.modules import LoadedModules


class AssistantProvider(Provider):
    scope = Scope.REQUEST

    store = provide(SqlAssistantStore, provides=AssistantStore)
    admission = provide(Admission)
    toolbox = provide(ToolBox)
    ask = provide(Ask)
    conversations = provide(Conversations)
    features = provide(AiFeatures)
    answer = provide(AnswerMessage)
    housekeeping = provide(Housekeeping)
    status = provide(AssistantStatusReaderImpl, provides=AssistantStatusReader)

    @provide(scope=Scope.APP)
    def catalog(self, modules: LoadedModules) -> ToolCatalog:
        return ToolCatalog(spec for module in modules.enabled for spec in module.assistant_tools())

    @provide(scope=Scope.APP)
    def models(self) -> ModelFactory:
        return ModelFactory()

    @provide(scope=Scope.APP)
    def engine(self, models: ModelFactory) -> AnswerEngine:
        return AgnoEngine(models)

    @provide(scope=Scope.APP)
    def relay(self, bus: EventBus, store: EphemeralStore) -> Relay:
        return BusRelay(bus, store)

    @provide(scope=Scope.APP)
    def limits(self, settings: AssistantSettings) -> AnswerLimits:
        return AnswerLimits(
            answer_timeout_seconds=settings.answer_timeout_seconds,
            max_tool_calls=settings.max_tool_calls,
            history_messages=settings.history_messages,
            max_question_chars=settings.max_question_chars,
            tools=ToolLimits(settings.tool_timeout_seconds, settings.max_tool_result_chars),
            attachments=AttachmentLimits(
                settings.max_attachments, settings.max_attachment_bytes, settings.max_attachment_chars
            ),
        )
