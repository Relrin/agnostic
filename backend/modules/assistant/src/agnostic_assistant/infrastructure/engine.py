"""The answer engine on agno: one ``Agent`` per answer, the bound tools as agno functions, events translated."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agno.agent import Agent
from agno.media import Image
from agno.models.message import Message
from agno.run.agent import (
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.tools.function import Function

from agnostic_assistant.application.ports import (
    BoundTool,
    Connection,
    ContentDelta,
    EngineError,
    EngineEvent,
    EngineRequest,
    Failed,
    Finished,
    ToolFinished,
    ToolStarted,
)
from agnostic_assistant.infrastructure.models import ModelFactory
from agnostic_kernel.logging import get_logger

log = get_logger(__name__)

CHECK_PROMPT = "Reply with the single word: ready"


def _function(tool: BoundTool) -> Function:
    async def entrypoint(**arguments: Any) -> str:  # noqa: ANN401
        return await tool.run(arguments)

    return Function(
        name=tool.name,
        description=tool.description,
        parameters=dict(tool.parameters),
        entrypoint=entrypoint,
        skip_entrypoint_processing=True,
    )


def _reason(exc: BaseException) -> str:
    """A sentence for the person: provider errors name the provider's message, not a traceback."""
    text = str(exc).strip() or type(exc).__name__
    return f"The model provider returned an error: {text[:300]}"


def _tokens(metrics: Any) -> tuple[int, int]:  # noqa: ANN401
    if metrics is None:
        return 0, 0
    return int(getattr(metrics, "input_tokens", 0) or 0), int(getattr(metrics, "output_tokens", 0) or 0)


class AgnoEngine:
    def __init__(self, models: ModelFactory) -> None:
        self._models = models

    def _agent(self, request: EngineRequest) -> Agent:
        return Agent(
            model=self._models.build(request.model, request.connection),
            name="Ask your OS",
            tools=[_function(tool) for tool in request.tools],
            instructions=request.instructions,
            tool_call_limit=request.max_tool_calls if request.tools else None,
            telemetry=False,
        )

    def _input(self, request: EngineRequest) -> list[Message]:
        messages = [Message(role=turn.role, content=turn.content) for turn in request.history]
        images = [Image(content=a.data, mime_type=a.media_type) for a in request.images if a.data is not None]
        messages.append(Message(role="user", content=request.question, images=images or None))
        return messages

    async def run(self, request: EngineRequest) -> AsyncIterator[EngineEvent]:
        try:
            agent = self._agent(request)
            content = ""
            stream = agent.arun(self._input(request), stream=True, stream_events=True)  # pyright: ignore[reportUnknownMemberType]
            async for event in stream:
                match event:
                    case ToolCallStartedEvent(tool=tool) if tool is not None:
                        yield ToolStarted(tool.tool_call_id or "", tool.tool_name or "")
                    case ToolCallCompletedEvent(tool=tool) if tool is not None:
                        duration = tool.metrics.duration if tool.metrics and tool.metrics.duration else None
                        yield ToolFinished(
                            tool.tool_call_id or "", tool.tool_name or "", round(duration * 1000) if duration else None
                        )
                    case RunContentEvent(content=str() as delta) if delta:
                        content += delta
                        yield ContentDelta(delta)
                    case RunCompletedEvent():
                        final = event.content if isinstance(event.content, str) else content
                        yield Finished(final or content, *_tokens(event.metrics))
                        return
                    case RunErrorEvent():
                        yield Failed(_reason(Exception(event.content or "the run failed")))
                        return
                    case RunCancelledEvent():
                        yield Failed("The answer was cancelled.")
                        return
                    case _:
                        pass
            yield Finished(content)
        except Exception as exc:  # noqa: BLE001  (any provider failure ends the answer with a sentence)
            log.warning("assistant.engine_failed", model=request.model, error=str(exc))
            yield Failed(_reason(exc))

    async def check(self, model: str, connection: Connection) -> str:
        agent = Agent(model=self._models.build(model, connection), telemetry=False)
        try:
            output = await agent.arun(CHECK_PROMPT)  # pyright: ignore[reportUnknownMemberType]
        except Exception as exc:
            raise EngineError(_reason(exc)) from exc
        status: object = getattr(output, "status", None)
        content: object = getattr(output, "content", None)
        if str(status).lower().endswith("error"):
            raise EngineError(_reason(Exception(str(content or "the model failed"))))
        return str(content or "").strip()
