"""Builds the agno model for a model string and the org's connection settings."""

from __future__ import annotations

from typing import Any

from agno.models.base import Model
from agno.models.openai.like import OpenAILike
from agno.models.utils import get_model

from agnostic_assistant.application.ports import Connection
from agnostic_assistant.domain.settings import parse_model

REQUEST_TIMEOUT_SECONDS = 60.0
NO_KEY = "not-needed"
"""OpenAI-compatible servers without auth still want some key in the header."""
OPENAI_STYLE = frozenset({"openai", "openai-chat", "openai-like", "vllm"})


def _set(model: Model, name: str, value: Any) -> None:  # noqa: ANN401
    if value is not None and hasattr(model, name):
        setattr(model, name, value)


class ModelFactory:
    """``provider:model`` → a configured agno model. Tests replace it with a scripted model."""

    def build(self, model: str, connection: Connection) -> Model:
        provider, model_id = parse_model(model)
        found = OpenAILike(id=model_id) if provider == "openai-like" else get_model(f"{provider}:{model_id}")
        if found is None:
            msg = f"agno has no model for {model!r}"
            raise ValueError(msg)
        built: Model = found
        _set(built, "timeout", REQUEST_TIMEOUT_SECONDS)
        if provider in OPENAI_STYLE:
            _set(built, "base_url", connection.endpoint)
            _set(built, "api_key", connection.api_key or (NO_KEY if provider in {"openai-like", "vllm"} else None))
            _set(built, "temperature", connection.temperature)
        elif provider == "ollama":
            _set(built, "host", connection.endpoint)
            _set(built, "api_key", connection.api_key)
            _set(built, "options", {"temperature": connection.temperature})
        elif provider == "anthropic":
            _set(built, "api_key", connection.api_key)
            _set(built, "temperature", connection.temperature)
            if connection.endpoint:
                _set(built, "client_params", {"base_url": connection.endpoint})
        elif provider == "azure-openai":
            _set(built, "azure_endpoint", connection.endpoint)
            _set(built, "azure_deployment", model_id)
            _set(built, "api_key", connection.api_key)
            _set(built, "api_version", connection.api_version)
            _set(built, "temperature", connection.temperature)
        return built
