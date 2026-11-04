"""The tools modules contribute, offered to the model only when the asking person may use them."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import orjson
from dishka import AsyncContainer
from pydantic import ValidationError

from agnostic_assistant.application.ports import BoundTool
from agnostic_assistant.domain.model import SourceRef, ToolCallRecord, ToolStatus, merge_sources
from agnostic_assistant.domain.prompts import Unavailable, quote
from agnostic_instances.facade import Instance
from agnostic_kernel.auth import Authorizer, Principal
from agnostic_kernel.errors import AppError, ScopeMissingError
from agnostic_kernel.logging import get_logger
from agnostic_kernel.tools import Redaction, ToolCall, ToolSpec, clip

log = get_logger(__name__)

FORBIDDEN = 403
NOT_FOUND = 404


class ToolCatalog:
    """Every enabled module's ``assistant_tools()``, by name."""

    def __init__(self, specs: Iterable[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in self._specs:
                msg = f"two modules contribute an assistant tool named {spec.name!r}"
                raise ValueError(msg)
            self._specs[spec.name] = spec

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)


@dataclass(slots=True)
class Ledger:
    """What the tools of one answer did, and the pages their data came from.

    Outcomes are matched to the engine's tool events by name, in call order.
    """

    outcomes: dict[str, deque[tuple[ToolStatus, str | None]]] = field(
        default_factory=lambda: defaultdict[str, deque[tuple[ToolStatus, str | None]]](deque)
    )
    sources: list[SourceRef] = field(default_factory=list[SourceRef])

    def outcome(self, name: str) -> tuple[ToolStatus, str | None]:
        queue = self.outcomes.get(name)
        return queue.popleft() if queue else ("done", None)

    def merged_sources(self) -> list[SourceRef]:
        return merge_sources(self.sources)


def area_of(scope: str) -> str:
    """``traces:read`` → ``traces``; ``agents:billing-agent:run`` → ``agents``."""
    return scope.split(":", 1)[0].replace("_", " ")


@dataclass(frozen=True, slots=True)
class ToolLimits:
    timeout_seconds: float
    max_result_chars: int


class ToolBox:
    def __init__(self, catalog: ToolCatalog, authorizer: Authorizer) -> None:
        self._catalog = catalog
        self._authorizer = authorizer

    def scope_of(self, name: str) -> str | None:
        spec = self._catalog.get(name)
        return spec.scope if spec else None

    async def usable(self, principal: Principal, instance: Instance) -> tuple[list[ToolSpec], list[Unavailable]]:
        offered: list[ToolSpec] = []
        missing: dict[str, Unavailable] = {}
        for spec in self._catalog.specs():
            if spec.scope is None:
                offered.append(spec)
                continue
            decision = await self._authorizer.check(
                principal, spec.scope, instance_id=None if spec.org_scope else instance.id
            )
            if decision.allowed:
                offered.append(spec)
            else:
                missing.setdefault(spec.scope, Unavailable(area_of(spec.scope), spec.scope))
        return offered, list(missing.values())

    def bind(
        self,
        container: AsyncContainer,
        principal: Principal,
        instance: Instance,
        specs: Iterable[ToolSpec],
        *,
        redaction: Redaction,
        limits: ToolLimits,
        ledger: Ledger,
    ) -> list[BoundTool]:
        def runner(spec: ToolSpec) -> BoundTool:
            async def run(arguments: Mapping[str, Any]) -> str:
                return await self.call(
                    container, principal, instance, spec, arguments, redaction=redaction, limits=limits, ledger=ledger
                )

            schema = spec.arguments.model_json_schema()
            schema.pop("title", None)
            return BoundTool(spec.name, spec.description, schema, run)

        return [runner(spec) for spec in specs]

    async def call(
        self,
        container: AsyncContainer,
        principal: Principal,
        instance: Instance,
        spec: ToolSpec,
        arguments: Mapping[str, Any],
        *,
        redaction: Redaction,
        limits: ToolLimits,
        ledger: Ledger,
    ) -> str:
        """Runs one tool and returns its quoted result; failures become data the model can explain."""
        status: ToolStatus = "done"
        detail: str | None = None
        payload: Any
        started = time.monotonic()
        try:
            parsed = spec.arguments.model_validate(dict(arguments))
            async with asyncio.timeout(limits.timeout_seconds):
                result = await spec.handler(container, ToolCall(principal, instance.id, instance.slug, parsed))
            payload = redaction.apply(result.data)
            ledger.sources.extend(SourceRef(s.kind, s.label, s.path) for s in result.sources)
        except ValidationError as exc:
            status, detail = "error", "invalid arguments"
            payload = {"invalid_arguments": exc.errors(include_url=False, include_input=False)}
        except ScopeMissingError as exc:
            status, detail = "denied", exc.detail
            payload = {"denied": True, "detail": exc.detail, "missing_scopes": exc.extra.get("missing_scopes", [])}
        except AppError as exc:
            message = exc.detail or exc.title
            if exc.status == FORBIDDEN:
                status, detail, payload = "denied", message, {"denied": True, "detail": message}
            elif exc.status == NOT_FOUND:
                status, detail, payload = "not_found", message, {"not_found": True, "detail": message}
            else:
                status, detail, payload = "error", message, {"error": message}
        except TimeoutError:
            status, detail = "error", f"timed out after {limits.timeout_seconds:g} s"
            payload = {"error": f"The tool didn't answer within {limits.timeout_seconds:g} s."}
        except Exception as exc:  # noqa: BLE001  (a broken tool must not break the answer)
            log.warning("assistant.tool_failed", tool=spec.name, error=str(exc))
            status, detail, payload = "error", "failed", {"error": "The tool failed."}
        ledger.outcomes[spec.name].append((status, clip(detail, 300)))
        text = orjson.dumps(payload, default=str).decode()
        if len(text) > limits.max_result_chars:
            text = f"{text[: limits.max_result_chars]}… (cut: the result was {len(text):,} characters)"
        log.debug("assistant.tool", tool=spec.name, status=status, ms=round((time.monotonic() - started) * 1000))
        return quote(f"tool:{spec.name}", text)


def record(tool_id: str, name: str, outcome: tuple[ToolStatus, str | None], duration_ms: int | None) -> ToolCallRecord:
    status, detail = outcome
    return ToolCallRecord(tool_id, name, status, duration_ms, detail)
