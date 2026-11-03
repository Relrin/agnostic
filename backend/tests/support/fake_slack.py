"""Outbound HTTP of the notifications module, answered like Slack (Web API and incoming webhooks) and webhook
receivers would, recording every request."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import orjson

from agnostic_notifications.application.ports import OutboundResponse


@dataclass
class FakeSlack:
    users: dict[str, str] = field(default_factory=lambda: {"daniel@localhost.company": "U0DANIEL"})
    """Email → Slack member id (``users.lookupByEmail``)."""
    token: str = "xoxb-test-token"
    requests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    fail_webhooks: int = 0

    def messages(self) -> list[dict[str, Any]]:
        """``chat.postMessage`` bodies and incoming-webhook posts, in order."""
        return [r["json"] for r in self.requests if r["url"].endswith("/chat.postMessage") or "/hooks/" in r["url"]]

    async def post(  # noqa: PLR0911  (one answer per Slack method)
        self,
        url: str,
        *,
        json: Any = None,
        content: bytes | None = None,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> OutboundResponse:
        body = json if json is not None else (orjson.loads(content) if content else None)
        self.requests.append({"url": url, "json": body, "form": dict(form or {}), "headers": dict(headers or {})})
        if "/hooks/" in url:
            if self.fail_webhooks:
                self.fail_webhooks -= 1
                return OutboundResponse(500, "boom")
            return OutboundResponse(200, "ok")
        if url.startswith("https://receiver.test/"):
            return OutboundResponse(204, None)
        if (headers or {}).get("Authorization") != f"Bearer {self.token}":
            return OutboundResponse(200, {"ok": False, "error": "invalid_auth"})
        if url.endswith("/users.lookupByEmail"):
            member = self.users.get((form or {}).get("email", ""))
            if member is None:
                return OutboundResponse(200, {"ok": False, "error": "users_not_found"})
            return OutboundResponse(200, {"ok": True, "user": {"id": member}})
        if url.endswith("/chat.postMessage"):
            return OutboundResponse(200, {"ok": True, "channel": (json or {}).get("channel"), "ts": "1730.0001"})
        return OutboundResponse(404, {"ok": False, "error": "unknown_method"})
