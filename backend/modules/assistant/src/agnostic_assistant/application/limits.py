"""Who may ask how often, how much the org may spend, and how long an answer may take."""

from __future__ import annotations

import time
from dataclasses import dataclass
from http import HTTPStatus

from agnostic_assistant.application.attachments import AttachmentLimits
from agnostic_assistant.application.ports import AssistantStore
from agnostic_assistant.application.tools import ToolLimits
from agnostic_assistant.domain.budget import Spend, month_of, over_budget
from agnostic_assistant.domain.settings import AiSettings, Feature
from agnostic_kernel.auth import Principal
from agnostic_kernel.db import utcnow
from agnostic_kernel.ephemeral import EphemeralStore
from agnostic_kernel.errors import AppError, RateLimitedError

USE_SCOPE = "assistant:use"
WINDOW_SECONDS = 60


class FeatureOffError(AppError):
    status = HTTPStatus.CONFLICT
    code = "ai_feature_off"
    title = "This AI feature is off"


class BudgetExhaustedError(AppError):
    status = HTTPStatus.TOO_MANY_REQUESTS
    code = "ai_budget_exhausted"
    title = "The AI token budget is used up"


@dataclass(frozen=True, slots=True)
class AnswerLimits:
    answer_timeout_seconds: float
    max_tool_calls: int
    history_messages: int
    max_question_chars: int
    tools: ToolLimits
    attachments: AttachmentLimits


def require_feature(settings: AiSettings, feature: Feature) -> None:
    if not settings.available(feature):
        what = {"assistant": "Ask your OS", "summaries": "AI summaries", "suggestions": "AI suggestions"}[feature]
        raise FeatureOffError(f"{what} is turned off. An admin can turn it on in Organization settings, AI features.")


class Admission:
    """Checked before a question or an explanation is queued."""

    def __init__(self, store: AssistantStore, ephemeral: EphemeralStore) -> None:
        self._store = store
        self._ephemeral = ephemeral

    async def admit(self, principal: Principal, settings: AiSettings) -> None:
        window = int(time.time() // WINDOW_SECONDS)
        count = await self._ephemeral.incr(f"rl:asst:{principal.id}:{window}", ttl=WINDOW_SECONDS + 10)
        if count > settings.requests_per_minute:
            raise RateLimitedError(
                f"More than {settings.requests_per_minute} AI requests a minute; try again shortly.",
                extra={"retry_after": WINDOW_SECONDS - int(time.time()) % WINDOW_SECONDS},
            )
        org, user = await self._store.spent(month_of(utcnow()), principal.id)
        reason = over_budget(
            Spend(org, user), org_limit=settings.monthly_token_budget, user_limit=settings.user_monthly_tokens
        )
        if reason:
            raise BudgetExhaustedError(reason)
