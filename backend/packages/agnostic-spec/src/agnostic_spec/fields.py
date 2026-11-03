"""Field metadata that drives the Studio form: where a field lives, how it is labelled and which widget edits it."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

Widget = Literal[
    "text",
    "textarea",
    "number",
    "switch",
    "select",
    "string_list",
    "model",
    "tools",
    "knowledge",
    "schema",
    "memory_manager",
    "learning",
    "members",
    "mode",
    "json",
]

META_KEY = "x-agnostic"


@dataclass(frozen=True, slots=True)
class FieldMeta:
    section: str
    label: str
    help: str = ""
    widget: Widget = "text"
    agno_param: str | None = None
    since_agno: str = "3.1"
    order: int = 0
    default: Any = None
    """The value agno leaves out of ``to_dict()``; ``None`` when agno writes every value it is given."""
    legacy: bool = False

    def as_schema(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None and value != ""}


def meta_field(
    section: str,
    label: str,
    *,
    help: str = "",  # noqa: A002
    widget: Widget = "text",
    order: int = 0,
    default: Any = None,  # noqa: ANN401
    legacy: bool = False,
    agno_param: str | None = None,
    since_agno: str = "3.1",
) -> Any:  # noqa: ANN401
    """A pydantic ``Field`` (absent by default) carrying :class:`FieldMeta` in its JSON Schema."""
    meta = FieldMeta(
        section=section,
        label=label,
        help=help,
        widget=widget,
        agno_param=agno_param,
        since_agno=since_agno,
        order=order,
        default=default,
        legacy=legacy,
    )
    return Field(default=None, description=help or None, json_schema_extra={META_KEY: meta.as_schema()})


def field_meta(model: type[BaseModel], name: str) -> FieldMeta | None:
    info = model.model_fields.get(name)
    if info is None or not isinstance(info.json_schema_extra, dict):
        return None
    extra: dict[str, Any] = info.json_schema_extra  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    raw = extra.get(META_KEY)
    if not isinstance(raw, dict):
        return None
    values: dict[str, Any] = raw  # pyright: ignore[reportUnknownVariableType]
    return FieldMeta(**{key: value for key, value in values.items() if key in FieldMeta.__dataclass_fields__})


def omitted_defaults(model: type[BaseModel]) -> dict[str, Any]:
    """Field name → the value agno never writes for it (only fields that have one)."""
    defaults: dict[str, Any] = {}
    for name in model.model_fields:
        meta = field_meta(model, name)
        if meta is not None and meta.default is not None:
            defaults[name] = meta.default
    return defaults
