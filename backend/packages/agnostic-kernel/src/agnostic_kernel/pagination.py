"""Cursor pagination envelope: ``{data, next_cursor, total_estimate?}``."""

from __future__ import annotations

import base64
import binascii
from typing import Annotated

import orjson
from fastapi import Query
from pydantic import BaseModel, ConfigDict, JsonValue

from agnostic_kernel.errors import ValidationFailedError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page[T](BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[T]
    next_cursor: str | None = None
    total_estimate: int | None = None


class PageParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int = DEFAULT_LIMIT
    cursor: str | None = None

    def position(self) -> dict[str, JsonValue] | None:
        return decode_cursor(self.cursor) if self.cursor else None


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Maximum items to return")] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(description="Opaque cursor from a previous page")] = None,
) -> PageParams:
    """FastAPI dependency: ``Depends(page_params)``."""
    return PageParams(limit=limit, cursor=cursor)


def encode_cursor(position: dict[str, JsonValue]) -> str:
    return base64.urlsafe_b64encode(orjson.dumps(position, option=orjson.OPT_SORT_KEYS)).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, JsonValue]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value: object = orjson.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError) as exc:
        raise ValidationFailedError(detail="The cursor is malformed.") from exc
    if not isinstance(value, dict):
        raise ValidationFailedError(detail="The cursor is malformed.")
    return value  # pyright: ignore[reportUnknownVariableType]
