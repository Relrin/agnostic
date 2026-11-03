"""Org notification channels: a Slack workspace (bot or incoming webhook), a shared mailbox, a webhook endpoint.

Secrets (bot tokens, webhook URLs, signing secrets) are stored sealed and never leave the API in clear: the public
view shows that they are set and their last characters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlsplit

from agnostic_notifications.domain.catalog import EVENTS_BY_NAME, ChannelKind

SECRET_KEYS = frozenset({"token", "webhook_url", "secret"})
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InvalidChannelError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Channel:
    id: str
    kind: ChannelKind
    name: str
    config: Mapping[str, Any]
    events: tuple[str, ...]
    """Event types posted to this channel for everyone (empty: only when an approval route names it)."""
    instance_ids: tuple[str, ...]
    """Instances whose events it receives (empty: all)."""
    enabled: bool
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    def receives(self, event: str, instance_id: str | None) -> bool:
        if not self.enabled or event not in self.events:
            return False
        return not self.instance_ids or instance_id is None or instance_id in self.instance_ids

    @property
    def sends_direct_messages(self) -> bool:
        """A Slack bot that may DM people who turned on Slack notifications."""
        return self.kind == "slack" and self.config.get("mode") == "bot" and bool(self.config.get("direct_messages"))

    def public_config(self) -> dict[str, Any]:
        return redact(self.config)


def redact(config: Mapping[str, Any]) -> dict[str, Any]:
    shown: dict[str, Any] = {}
    for key, value in config.items():
        if key in SECRET_KEYS and isinstance(value, str) and value:
            shown[key] = f"…{value[-4:]}" if len(value) > 8 else "set"  # noqa: PLR2004
        else:
            shown[key] = value
    return shown


def _http_url(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidChannelError(f"{field} is required.")
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise InvalidChannelError(f"{field} must be an http(s) URL.")
    return value


def validate_config(  # noqa: C901  (one branch per channel kind and mode)
    kind: ChannelKind, config: Mapping[str, Any], previous: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The config to store. Secrets left out of an update keep their previous values."""
    merged: dict[str, Any] = dict(previous or {})
    merged.update({key: value for key, value in config.items() if not (key in SECRET_KEYS and value in {None, ""})})
    if kind == "slack":
        mode = merged.get("mode") or ("webhook" if merged.get("webhook_url") else "bot")
        result: dict[str, Any] = {"mode": mode}
        if mode == "webhook":
            result["webhook_url"] = _http_url(merged.get("webhook_url"), "webhook_url")
        elif mode == "bot":
            token = merged.get("token")
            if not isinstance(token, str) or not token:
                raise InvalidChannelError("A Slack bot needs its token (xoxb-…).")
            result["token"] = token
            channel = merged.get("channel")
            if channel is not None and not isinstance(channel, str):
                raise InvalidChannelError("channel must be a Slack channel id or #name.")
            if channel:
                result["channel"] = channel
            result["direct_messages"] = bool(merged.get("direct_messages", True))
        else:
            raise InvalidChannelError("mode must be bot or webhook.")
        api_base = merged.get("api_base")
        if api_base:
            result["api_base"] = _http_url(api_base, "api_base").rstrip("/")
        return result
    if kind == "email":
        to = merged.get("to")
        addresses = [to] if isinstance(to, str) else cast("Sequence[object]", to or [])
        clean = [str(item).strip() for item in addresses if str(item).strip()]
        if not clean or not all(EMAIL.match(item) for item in clean):
            raise InvalidChannelError("to must list one or more email addresses.")
        return {"to": clean}
    result = {"url": _http_url(merged.get("url"), "url")}
    secret = merged.get("secret")
    if secret:
        result["secret"] = str(secret)
    return result


def validate_events(events: Sequence[str]) -> tuple[str, ...]:
    unknown = [event for event in events if event not in EVENTS_BY_NAME]
    if unknown:
        raise InvalidChannelError(f"Unknown event types: {', '.join(unknown)}.")
    return tuple(dict.fromkeys(events))
