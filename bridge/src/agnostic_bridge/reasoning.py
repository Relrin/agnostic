"""Reasoning effort per run, in one vocabulary across model providers.

A chat run may carry ``reasoning_effort`` (a form field AgentOS hands to the run as a keyword argument). Providers
spell "think harder" differently, so the level is translated by a :class:`ReasoningProfile` for the run's model:

- OpenAI reasoning models (o-series, gpt-5, gpt-oss) and Azure OpenAI: ``reasoning_effort``.
- xAI Grok mini models: ``reasoning_effort`` with ``low`` and ``high`` only.
- Claude: extended thinking with a token budget, or adaptive thinking with ``output_config.effort`` on the models
  that no longer take a budget.
- Gemini: ``thinking_level`` (Gemini 3) or ``thinking_budget`` (Gemini 2.5).
- Any model class that declares ``reasoning_levels`` and has a ``reasoning_effort`` field (custom models).

Profiles recognise models by the fields they have and the provider they name, not by class, so they hold for
subclasses and need none of the provider SDKs installed. A profile never changes the model it is given:
:func:`with_reasoning` returns a copy, because AgentOS shares one model object between the per-request copies of an
agent. Register a profile for another provider with
:func:`register_reasoning_profile`; :func:`reasoning_options` reports what a model accepts so the UI only offers
levels that work.
"""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Sequence
from typing import Any, ClassVar, Literal, Protocol, get_args

from agno.guardrails.base import BaseGuardrail
from agno.models.base import Model
from agno.utils.log import log_warning
from pydantic import BaseModel, Field

ReasoningLevel = Literal["off", "minimal", "low", "medium", "high", "max"]
LEVELS: tuple[str, ...] = get_args(ReasoningLevel)

RUN_KWARG = "reasoning_effort"
"""The run keyword argument (and form field) that carries the level."""


class ReasoningOptions(BaseModel):
    """The reasoning levels a component's model accepts."""

    levels: list[ReasoningLevel] = Field(description="Levels a run may ask for, least effort first")
    configured: ReasoningLevel | None = Field(
        default=None, description="The level the model is configured with, when it maps onto one"
    )
    parameter: str = Field(description="How the provider receives the level, e.g. 'reasoning_effort'")


class ReasoningProfile(Protocol):
    """Translates the shared levels for one family of models."""

    def matches(self, model: Model) -> bool: ...

    def options(self, model: Model) -> ReasoningOptions | None:
        """The levels ``model`` accepts, or ``None`` when it has no reasoning to tune."""
        ...

    def apply(self, model: Model, level: str) -> None:
        """Set ``level`` on ``model`` (a copy the caller owns)."""
        ...


def _id(model: Model) -> str:
    return (model.id or "").lower()


def _provider(model: Model) -> str:
    try:
        return (model.get_provider() or "").lower()
    except Exception:  # a custom model may not implement it
        return (getattr(model, "provider", None) or "").lower()


def _known(value: Any, levels: Sequence[str]) -> Any:
    return value if isinstance(value, str) and value in levels else None


class DeclaredLevels:
    """A model class that says which levels it takes (``reasoning_levels``) and reads ``reasoning_effort``."""

    def matches(self, model: Model) -> bool:
        return isinstance(getattr(type(model), "reasoning_levels", None), (tuple, list)) and hasattr(
            model, "reasoning_effort"
        )

    def options(self, model: Model) -> ReasoningOptions | None:
        levels = [level for level in type(model).reasoning_levels if level in LEVELS]  # type: ignore[attr-defined]
        if not levels:
            return None
        return ReasoningOptions(
            levels=levels,  # type: ignore[arg-type]
            configured=_known(model.reasoning_effort, levels),  # type: ignore[attr-defined]
            parameter="reasoning_effort",
        )

    def apply(self, model: Model, level: str) -> None:
        model.reasoning_effort = level  # type: ignore[attr-defined]


class OpenAIReasoning:
    """OpenAI's reasoning models, over Chat Completions or Responses (Azure OpenAI included)."""

    _PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-oss")
    _LEVELS: ClassVar[list[ReasoningLevel]] = ["low", "medium", "high"]

    def matches(self, model: Model) -> bool:
        return _provider(model) in {"openai", "azure"} and hasattr(model, "reasoning_effort")

    def options(self, model: Model) -> ReasoningOptions | None:
        name = _id(model).rsplit("/", 1)[-1]
        if not name.startswith(self._PREFIXES):
            return None  # gpt-4.1, gpt-4o, …: the API refuses reasoning_effort
        return ReasoningOptions(
            levels=self._LEVELS,
            configured=_known(getattr(model, "reasoning_effort", None), self._LEVELS),
            parameter="reasoning_effort",
        )

    def apply(self, model: Model, level: str) -> None:
        model.reasoning_effort = level  # type: ignore[attr-defined]


class XAIReasoning:
    """Grok mini models: ``reasoning_effort`` with two levels. Other Grok models reason on their own terms."""

    _LEVELS: ClassVar[list[ReasoningLevel]] = ["low", "high"]

    def matches(self, model: Model) -> bool:
        return _provider(model) == "xai" and hasattr(model, "reasoning_effort")

    def options(self, model: Model) -> ReasoningOptions | None:
        if "mini" not in _id(model):
            return None
        return ReasoningOptions(
            levels=self._LEVELS,
            configured=_known(getattr(model, "reasoning_effort", None), self._LEVELS),
            parameter="reasoning_effort",
        )

    def apply(self, model: Model, level: str) -> None:
        model.reasoning_effort = level  # type: ignore[attr-defined]


class ClaudeReasoning:
    """Claude on Anthropic, Bedrock, Vertex AI or Azure: extended thinking, budgeted or adaptive."""

    BUDGETS: ClassVar[dict[str, int]] = {"low": 2048, "medium": 8192, "high": 16384}
    """Thinking tokens per level on models that take a budget."""

    def matches(self, model: Model) -> bool:
        return "claude" in _id(model) and hasattr(model, "thinking") and hasattr(model, "output_config")

    @staticmethod
    def _budgeted(model: Model) -> bool:
        from agno.utils.models.claude import supports_thinking_budget

        return supports_thinking_budget(model.id)

    def options(self, model: Model) -> ReasoningOptions | None:
        if model.id in getattr(model, "NON_THINKING_MODELS", ()):
            return None
        budgeted = self._budgeted(model)
        levels: list[ReasoningLevel] = (
            ["off", "low", "medium", "high"] if budgeted else ["off", "low", "medium", "high", "max"]
        )
        thinking = getattr(model, "thinking", None)
        configured: ReasoningLevel | None = None
        if not isinstance(thinking, dict) or thinking.get("type") == "disabled":
            configured = "off"
        elif budgeted:
            budget = thinking.get("budget_tokens")
            if isinstance(budget, int):
                configured = min(self.BUDGETS, key=lambda name: abs(self.BUDGETS[name] - budget))  # type: ignore[assignment]
        else:
            configured = _known((getattr(model, "output_config", None) or {}).get("effort"), levels)
        return ReasoningOptions(
            levels=levels,
            configured=configured,
            parameter="thinking.budget_tokens" if budgeted else "output_config.effort",
        )

    def apply(self, model: Model, level: str) -> None:
        if level == "off":
            model.thinking = None  # type: ignore[attr-defined]
            return
        if self._budgeted(model):
            budget = self.BUDGETS.get(level, self.BUDGETS["high"])
            model.thinking = {"type": "enabled", "budget_tokens": budget}  # type: ignore[attr-defined]
            # The answer has to fit after the thinking.
            max_tokens = getattr(model, "max_tokens", None) or 0
            if max_tokens <= budget:
                model.max_tokens = budget + 4096  # type: ignore[attr-defined]
            return
        model.thinking = {"type": "adaptive", "display": "summarized"}  # type: ignore[attr-defined]
        model.output_config = {**(getattr(model, "output_config", None) or {}), "effort": level}  # type: ignore[attr-defined]


class GeminiReasoning:
    """Gemini: ``thinking_level`` on Gemini 3, a thinking token budget on Gemini 2.5."""

    BUDGETS: ClassVar[dict[str, int]] = {"off": 0, "low": 1024, "medium": 8192, "high": 24576}

    def matches(self, model: Model) -> bool:
        return hasattr(model, "thinking_level") and hasattr(model, "thinking_budget")

    @staticmethod
    def _uses_level(model: Model) -> bool:
        return "gemini-3" in _id(model)

    def options(self, model: Model) -> ReasoningOptions | None:
        name = _id(model)
        if self._uses_level(model):
            levels: list[ReasoningLevel] = ["low", "high"]
            return ReasoningOptions(
                levels=levels,
                configured=_known(getattr(model, "thinking_level", None), levels),
                parameter="thinking_level",
            )
        if "gemini-2.5" not in name:
            return None
        # 2.5 Pro always thinks; Flash and Flash-Lite can turn it off.
        levels = ["low", "medium", "high"] if "pro" in name else ["off", "low", "medium", "high"]
        budget = getattr(model, "thinking_budget", None)
        configured: ReasoningLevel | None = None
        if isinstance(budget, int):
            configured = min(self.BUDGETS, key=lambda key: abs(self.BUDGETS[key] - budget))  # type: ignore[assignment]
        return ReasoningOptions(levels=levels, configured=configured, parameter="thinking_budget")

    def apply(self, model: Model, level: str) -> None:
        if self._uses_level(model):
            model.thinking_level = level  # type: ignore[attr-defined]
        else:
            model.thinking_budget = self.BUDGETS.get(level, self.BUDGETS["high"])  # type: ignore[attr-defined]
        if level != "off":
            model.include_thoughts = True  # type: ignore[attr-defined]


_PROFILES: list[ReasoningProfile] = [
    DeclaredLevels(),
    ClaudeReasoning(),
    GeminiReasoning(),
    XAIReasoning(),
    OpenAIReasoning(),
]


def register_reasoning_profile(profile: ReasoningProfile) -> None:
    """Add a profile for a provider the bridge doesn't know; it is tried before the built-in ones."""
    _PROFILES.insert(0, profile)


def _profile(model: Model | None) -> ReasoningProfile | None:
    if model is None:
        return None
    for profile in _PROFILES:
        if profile.matches(model):
            return profile
    return None


def reasoning_options(model: Model | None) -> ReasoningOptions | None:
    """The levels ``model`` accepts, or ``None`` when there is nothing to choose."""
    profile = _profile(model)
    if profile is None or model is None:
        return None
    return profile.options(model)


def with_reasoning(model: Model, level: str | None) -> Model:
    """A copy of ``model`` that reasons at ``level``; ``model`` itself when the level is empty or not accepted."""
    if not level:
        return model
    profile = _profile(model)
    options = profile.options(model) if profile is not None else None
    if profile is None or options is None or level not in options.levels:
        log_warning(f"Reasoning effort {level!r} isn't available for model {model.id!r}; running it as configured.")
        return model
    copied = copy.copy(model)
    profile.apply(copied, level)
    return copied


CONFIGURED_MODEL_ATTR = "_agnostic_configured_model"
"""Where the hook keeps the model an agent or team was configured with, so every run derives its model from that one
and a run without a level gets it back, even on an instance that served an earlier run. (An attribute rather than a
weak mapping: Agno components hash by value, and the value changes with the model.)"""


def apply_reasoning_effort(agent: Any = None, team: Any = None, reasoning_effort: str | None = None) -> None:
    """Run this agent or team (its leader's model) at the run's ``reasoning_effort``."""
    component = agent if agent is not None else team
    if component is None or not hasattr(component, "model"):
        return
    configured = getattr(component, CONFIGURED_MODEL_ATTR, None)
    if configured is None:
        configured = component.model
        if configured is None:
            return
        # Slotted or frozen: each run derives from what it has now.
        with contextlib.suppress(AttributeError, TypeError):
            object.__setattr__(component, CONFIGURED_MODEL_ATTR, configured)
    component.model = with_reasoning(configured, reasoning_effort) if reasoning_effort else configured


class ReasoningEffortHook(BaseGuardrail):
    """The pre-hook that applies :func:`apply_reasoning_effort`.

    A guardrail by type only (it never rejects input): Agno runs guardrails before the model call even when an
    AgentOS runs its other hooks in the background, and the model has to be chosen before that call.
    """

    def check(  # type: ignore[override]
        self, agent: Any = None, team: Any = None, reasoning_effort: str | None = None
    ) -> None:
        apply_reasoning_effort(agent=agent, team=team, reasoning_effort=reasoning_effort)

    async def async_check(  # type: ignore[override]
        self, agent: Any = None, team: Any = None, reasoning_effort: str | None = None
    ) -> None:
        apply_reasoning_effort(agent=agent, team=team, reasoning_effort=reasoning_effort)


REASONING_HOOK = ReasoningEffortHook()


def has_reasoning_hook(component: Any) -> bool:
    """Whether runs of ``component`` apply ``reasoning_effort`` (before or after Agno normalised its hooks)."""
    return any(
        hook is REASONING_HOOK or getattr(hook, "__self__", None) is REASONING_HOOK
        for hook in getattr(component, "pre_hooks", None) or []
    )


def add_reasoning_hook(component: Any) -> bool:
    """Put the reasoning hook first in the pre-hooks of an agent or team, before it has run; ``False`` when it can't
    take one. Idempotent."""
    if not hasattr(component, "pre_hooks") or not hasattr(component, "model"):
        return False
    if has_reasoning_hook(component):
        return True
    if getattr(component, "_hooks_normalised", False):
        return False  # it already ran: its hook list holds bound methods now, so leave it as it is
    component.pre_hooks = [REASONING_HOOK, *(component.pre_hooks or [])]
    return True


__all__ = [
    "LEVELS",
    "REASONING_HOOK",
    "RUN_KWARG",
    "ClaudeReasoning",
    "DeclaredLevels",
    "GeminiReasoning",
    "OpenAIReasoning",
    "ReasoningEffortHook",
    "ReasoningLevel",
    "ReasoningOptions",
    "ReasoningProfile",
    "XAIReasoning",
    "add_reasoning_hook",
    "apply_reasoning_effort",
    "has_reasoning_hook",
    "reasoning_options",
    "register_reasoning_profile",
    "with_reasoning",
]
