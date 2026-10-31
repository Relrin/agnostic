"""Prefixed ULIDs: ``usr_01JAB...``, ``ins_01JAB...``.

The prefix names the entity kind, the ULID part sorts by creation time. AgentOS ids are never re-prefixed.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import StringConstraints
from ulid import ULID

_PREFIX = re.compile(r"^[a-z]{2,5}$")
_ULID = r"[0-7][0-9A-HJKMNP-TV-Z]{25}"


class InvalidIdError(ValueError):
    pass


def _check_prefix(prefix: str) -> None:
    if not _PREFIX.fullmatch(prefix):
        msg = f"id prefix must be 2-5 lowercase letters, got {prefix!r}"
        raise ValueError(msg)


def new_id(prefix: str) -> str:
    _check_prefix(prefix)
    return f"{prefix}_{ULID()}"


def id_pattern(prefix: str) -> str:
    _check_prefix(prefix)
    return rf"^{prefix}_{_ULID}$"


def parse_id(value: str, prefix: str) -> str:
    """Return ``value`` if it is a well-formed id with ``prefix``; raise :class:`InvalidIdError` otherwise."""
    if not re.fullmatch(id_pattern(prefix), value):
        msg = f"not a valid {prefix}_ id: {value!r}"
        raise InvalidIdError(msg)
    return value


def id_timestamp(value: str) -> datetime:
    """Creation time encoded in the ULID part of a prefixed id."""
    _, _, raw = value.partition("_")
    return ULID.from_str(raw).datetime


def id_type(prefix: str) -> type[str]:
    """Pydantic-validated string type for ids with ``prefix`` (shows the pattern in OpenAPI)."""
    return Annotated[str, StringConstraints(pattern=id_pattern(prefix))]  # pyright: ignore[reportReturnType]
