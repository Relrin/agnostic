"""One notification rendered for each channel: Slack blocks, an email, a signed webhook body.

Slack buttons are links, never interactive callbacks: "Approve" opens the approval in Agnostic, where a signed-in
person decides under their own scopes. A bot clicking for someone would resolve approvals as the bot.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

type ActionStyle = Literal["primary", "danger", "default"]

SIGNATURE_HEADER = "X-Agnostic-Signature"
EVENT_HEADER = "X-Agnostic-Event"


@dataclass(frozen=True, slots=True)
class Action:
    label: str
    url: str
    style: ActionStyle = "default"


@dataclass(frozen=True, slots=True)
class Message:
    event_type: str
    title: str
    body: str = ""
    url: str | None = None
    """Absolute link to where the person acts (``{public_url}/i/prod/approvals?approval=…``)."""
    actions: tuple[Action, ...] = ()
    context: str | None = None
    """One muted line: the instance, the requester, the time."""
    data: Mapping[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "actions": [{"label": a.label, "url": a.url, "style": a.style} for a in self.actions],
            "context": self.context,
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Message:
        actions: Sequence[Mapping[str, Any]] = value.get("actions") or []
        return cls(
            event_type=str(value["event_type"]),
            title=str(value["title"]),
            body=str(value.get("body") or ""),
            url=value.get("url"),
            actions=tuple(
                Action(str(a["label"]), str(a["url"]), a.get("style") or "default")  # pyright: ignore[reportArgumentType]
                for a in actions
            ),
            context=value.get("context"),
            data=dict(value.get("data") or {}),
        )


def _escape(text: str) -> str:
    """Slack mrkdwn treats ``&``, ``<`` and ``>`` as markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_payload(message: Message) -> dict[str, Any]:
    """``chat.postMessage`` / incoming-webhook body: a header line, the body, link buttons, a context line."""
    title = _escape(message.title)
    headline = f"*<{message.url}|{title}>*" if message.url else f"*{title}*"
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": headline + (f"\n{_escape(message.body)}" if message.body else "")},
        }
    ]
    if message.actions:
        elements: list[dict[str, Any]] = []
        for index, action in enumerate(message.actions):
            button: dict[str, Any] = {
                "type": "button",
                "text": {"type": "plain_text", "text": action.label},
                "url": action.url,
                "action_id": f"open_{index}",
            }
            if action.style != "default":
                button["style"] = action.style
            elements.append(button)
        blocks.append({"type": "actions", "elements": elements})
    if message.context:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": _escape(message.context)}]})
    return {"text": message.title, "blocks": blocks, "unfurl_links": False}


def email_text(message: Message) -> tuple[str, str]:
    """``(subject, body)``; actions become plain links (people click through and sign in)."""
    lines = [message.title, ""]
    if message.body:
        lines += [message.body, ""]
    for action in message.actions:
        lines.append(f"{action.label}: {action.url}")
    if message.url and not message.actions:
        lines.append(f"Open in Agnostic: {message.url}")
    if message.context:
        lines += ["", message.context]
    return message.title, "\n".join(lines).rstrip() + "\n"


def webhook_body(message: Message, *, delivery_id: str, sent_at: str) -> bytes:
    payload = {"id": delivery_id, "sent_at": sent_at, **message.to_dict()}
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode()


def sign(secret: str, body: bytes) -> str:
    """``sha256=<hex>``: receivers recompute the HMAC of the raw body with the shared secret."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
