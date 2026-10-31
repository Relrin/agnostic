"""Structured logging for the API, worker and CLI.

Standard-library loggers (uvicorn, sqlalchemy, procrastinate) are routed through the same processors, so every
line carries the request id and goes through secret redaction.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable, MutableMapping
from typing import Any

import orjson
import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from agnostic_kernel.settings import LogSettings

REDACTED = "***"
_SECRET_KEY = re.compile(r"(password|passwd|secret|token|authorization|api[_-]?key|cookie)", re.IGNORECASE)


def redact_secrets(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Mask values whose key looks like a secret, at any nesting depth."""
    return _redact(event_dict)


def _redact[M: MutableMapping[str, Any]](mapping: M) -> M:
    for key, value in mapping.items():
        if _SECRET_KEY.search(key):
            mapping[key] = REDACTED
        elif isinstance(value, dict):
            mapping[key] = _redact(dict(value))  # pyright: ignore[reportUnknownArgumentType]
    return mapping


def _orjson_dumps(obj: object, default: Callable[[object], object] | None = None) -> str:
    return orjson.dumps(obj, default=default).decode()


def configure_logging(settings: LogSettings) -> None:
    """Configure structlog and the stdlib root logger. Safe to call more than once."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_secrets,
    ]
    renderer: Processor
    if settings.format == "json":
        renderer = structlog.processors.JSONRenderer(serializer=_orjson_dumps)
        shared.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "procrastinate"):
        stdlib_logger = logging.getLogger(name)
        stdlib_logger.handlers.clear()
        stdlib_logger.propagate = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.stdlib.get_logger(name)  # pyright: ignore[reportAny]
