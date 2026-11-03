"""References to objects the AgentOS registry owns, in the shapes agno 3.1 writes them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Ref(BaseModel):
    model_config = ConfigDict(extra="allow")


class ModelRef(Ref):
    """``Model.to_dict()``: the registry resolves it by id, provider and (to tell classes apart) name."""

    id: str
    provider: str | None = None
    name: str | None = None

    @classmethod
    def parse(cls, value: object) -> ModelRef | None:
        """Both stored forms: the dict, or the ``"provider:id"`` shorthand."""
        if isinstance(value, ModelRef):
            return value
        if isinstance(value, dict):
            return cls.model_validate(value)
        if isinstance(value, str) and value:
            provider, _, model_id = value.partition(":")
            return cls(id=model_id, provider=provider) if model_id else cls(id=provider)
        return None


class ToolRef(Ref):
    """``Function.to_dict()`` plus the owning toolkit. Rehydration needs ``parameters``, so Studio always writes it."""

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None
    requires_confirmation: bool | None = None
    external_execution: bool | None = None
    approval_type: str | None = None
    toolkit: str | None = None

    @property
    def registry_name(self) -> str:
        """The registry lists a toolkit's functions under the toolkit's name."""
        return self.toolkit or self.name

    @property
    def needs_approval(self) -> bool:
        return bool(self.requires_confirmation or self.approval_type)


class KnowledgeRef(Ref):
    name: str


class MemoryManagerRef(Ref):
    registry_id: str


class MemberRef(Ref):
    type: Literal["agent", "team"] = "agent"
    agent_id: str | None = None
    team_id: str | None = None

    @property
    def component_id(self) -> str:
        return (self.agent_id if self.type == "agent" else self.team_id) or ""


def learning_name(value: object) -> str | None:
    """A named learning machine (``{"name": …}``) is a registry reference; anything else is inline or a flag."""
    if isinstance(value, dict) and set(value) == {"name"} and isinstance(value["name"], str):  # pyright: ignore[reportUnknownArgumentType]
        return value["name"]
    return None


def schema_name(value: object) -> str | None:
    """A schema stored as a class name is a registry reference; a dict is an inline JSON Schema."""
    return value if isinstance(value, str) and value else None
