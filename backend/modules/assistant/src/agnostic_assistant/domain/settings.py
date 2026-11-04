"""The org's AI features: which model answers what, what it may see, and how much it may spend."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from typing import Any, Literal, cast, get_args

type Feature = Literal["assistant", "summaries", "suggestions"]
"""``assistant``: Ask your OS and its follow-ups. ``summaries``: explanations next to deterministic text (trace
diagnosis, eval insight, change summaries). ``suggestions``: drafts a person can insert (CEL, commit messages)."""

FEATURES: tuple[Feature, ...] = get_args(Feature.__value__)

PROVIDERS: Mapping[str, str] = {
    "openai": "OpenAI (Responses API)",
    "openai-chat": "OpenAI (Chat Completions)",
    "openai-like": "OpenAI-compatible endpoint",
    "vllm": "vLLM",
    "ollama": "Ollama",
    "anthropic": "Anthropic",
    "azure-openai": "Azure OpenAI",
}
"""Model string prefixes that can be configured (``vllm:Qwen/Qwen3-32B``)."""

VISION_PROVIDERS = frozenset({"openai", "openai-chat", "anthropic", "azure-openai", "ollama", "vllm", "openai-like"})
"""Providers whose API accepts images; whether the chosen model understands them is up to the model."""

MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
MAX_REQUESTS_PER_MINUTE = 600
MAX_NOTICE = 1000


class SettingsError(ValueError):
    def __init__(self, message: str, field_name: str) -> None:
        super().__init__(message)
        self.field = field_name


def parse_model(value: str) -> tuple[str, str]:
    """``"vllm:Qwen/Qwen3-32B"`` → ``("vllm", "Qwen/Qwen3-32B")``."""
    provider, _, model_id = value.strip().partition(":")
    provider = provider.lower()
    if not model_id.strip():
        msg = f"Write the model as provider:model, e.g. ollama:qwen3:8b (got {value!r})."
        raise SettingsError(msg, "models")
    if provider not in PROVIDERS:
        msg = f"Unknown provider {provider!r}; use one of {', '.join(PROVIDERS)}."
        raise SettingsError(msg, "models")
    return provider, model_id.strip()


@dataclass(frozen=True, slots=True)
class AiSettings:
    enabled: bool = False
    """Master switch. Off: no model is called and no AI element is shown outside settings."""
    models: Mapping[Feature, str] = field(default_factory=dict[Feature, str])
    """Model string per feature; a feature without its own model uses the assistant's."""
    endpoint: str | None = None
    """Base URL for self-hosted and compatible providers (vLLM, Ollama, OpenAI-compatible, Azure)."""
    api_version: str | None = None
    has_api_key: bool = False
    temperature: float = 0.1
    features: Mapping[Feature, bool] = field(default_factory=lambda: dict.fromkeys(FEATURES, True))
    monthly_token_budget: int | None = None
    """Tokens the whole org may use per calendar month (UTC); ``None``: unlimited."""
    user_monthly_tokens: int | None = None
    requests_per_minute: int = 10
    """Per person, all features together."""
    redact_tool_args: bool = False
    """Strip the arguments runtimes passed to tools from what the model sees."""
    redact_user_messages: bool = False
    """Strip what end users typed (run inputs, session messages) from what the model sees."""
    audit_question_text: bool = False
    """Keep the question text in the audit log (by default only tools and sources are recorded)."""
    retention_days: int = 90
    data_notice: str | None = None
    """Shown under the Ask box, e.g. "Answers are generated on our own vLLM cluster"."""
    version: int = 0
    updated_by: str | None = None
    updated_at: datetime | None = None

    def model_for(self, feature: Feature) -> str | None:
        return self.models.get(feature) or self.models.get("assistant")

    @property
    def provider(self) -> str | None:
        model = self.models.get("assistant")
        return parse_model(model)[0] if model else None

    def available(self, feature: Feature) -> bool:
        return self.enabled and self.features.get(feature, False) and self.model_for(feature) is not None

    def updated(self, changes: Mapping[str, Any]) -> AiSettings:
        known = {f.name for f in fields(self)} - {"has_api_key", "version", "updated_by", "updated_at"}
        unknown = set(changes) - known
        if unknown:
            msg = f"Unknown setting(s): {', '.join(sorted(unknown))}."
            raise SettingsError(msg, min(unknown))
        values = dict(changes)
        if "models" in values:
            models = cast("Mapping[str, str | None]", values["models"])
            cleaned: dict[Feature, str] = {}
            for name, model in models.items():
                if name not in FEATURES:
                    raise SettingsError(f"Unknown feature {name!r}.", "models")
                if model and model.strip():
                    provider, model_id = parse_model(model)
                    cleaned[name] = f"{provider}:{model_id}"
            values["models"] = cleaned
        if "features" in values:
            toggles = cast("Mapping[str, bool]", values["features"])
            if set(toggles) - set(FEATURES):
                raise SettingsError("Unknown feature toggle.", "features")
            values["features"] = {**self.features, **{cast("Feature", k): bool(v) for k, v in toggles.items()}}
        for name in ("endpoint", "api_version", "data_notice"):
            if name in values and isinstance(values[name], str):
                values[name] = values[name].strip() or None
        result = replace(self, **values)
        result.validate()
        return result

    def validate(self) -> None:
        if not 0 <= self.temperature <= 2:  # noqa: PLR2004
            raise SettingsError("Temperature is between 0 and 2.", "temperature")
        for name in ("monthly_token_budget", "user_monthly_tokens"):
            value = cast("int | None", getattr(self, name))
            if value is not None and value < 1:
                raise SettingsError("A token budget is at least 1 (leave it empty for no limit).", name)
        if not 1 <= self.requests_per_minute <= MAX_REQUESTS_PER_MINUTE:
            msg = f"Requests per minute are between 1 and {MAX_REQUESTS_PER_MINUTE}."
            raise SettingsError(msg, "requests_per_minute")
        if not MIN_RETENTION_DAYS <= self.retention_days <= MAX_RETENTION_DAYS:
            msg = f"Keep conversations between {MIN_RETENTION_DAYS} and {MAX_RETENTION_DAYS} days."
            raise SettingsError(msg, "retention_days")
        if self.endpoint and not self.endpoint.startswith(("http://", "https://")):
            raise SettingsError("The endpoint is a URL starting with http:// or https://.", "endpoint")
        if self.data_notice and len(self.data_notice) > MAX_NOTICE:
            raise SettingsError(f"Keep the notice under {MAX_NOTICE} characters.", "data_notice")
        if self.enabled and not self.models.get("assistant"):
            raise SettingsError("Choose the assistant's model before turning AI features on.", "models")

    def diff(self, before: AiSettings, *, key_changed: bool) -> list[dict[str, str]]:
        """Audit lines from ``before`` to ``self``; the key itself is never written down."""
        lines: list[dict[str, str]] = []
        for item in fields(self):
            name = item.name
            if name in {"has_api_key", "version", "updated_by", "updated_at"}:
                continue
            old, new = getattr(before, name), getattr(self, name)
            if old != new:
                lines.append({"op": "note", "text": f"{name}: {_show(old)} → {_show(new)}"})
        if key_changed:
            lines.append({"op": "note", "text": "API key: replaced" if self.has_api_key else "API key: removed"})
        return lines


def _show(value: object) -> str:
    if isinstance(value, Mapping):
        items = cast("Mapping[str, object]", value)
        return ", ".join(f"{k}={v}" for k, v in sorted(items.items())) or "none"
    return "none" if value is None else str(value)
