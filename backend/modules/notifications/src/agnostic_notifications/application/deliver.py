"""Sending one delivery (the ``notifications.deliver`` job): email, a Slack message or DM, a signed webhook.

Transient failures raise so the job is retried; the last attempt leaves the delivery ``failed`` with the reason,
which the channel's page shows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from agnostic_kernel.db import utcnow
from agnostic_kernel.logging import get_logger
from agnostic_kernel.mail import Email, Mailer
from agnostic_notifications.application.ports import Delivery, OutboundHttp, Repositories
from agnostic_notifications.domain.channels import Channel
from agnostic_notifications.domain.messages import (
    EVENT_HEADER,
    SIGNATURE_HEADER,
    Message,
    email_text,
    sign,
    slack_payload,
    webhook_body,
)

log = get_logger(__name__)

OK = 200
REDIRECT = 300


class DeliveryError(RuntimeError):
    """The channel refused or failed; ``permanent`` ones aren't retried (a revoked token, an unknown user)."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class Deliver:
    def __init__(
        self,
        repositories: Repositories,
        mailer: Mailer,
        http: OutboundHttp,
        slack_api_base: str,
    ) -> None:
        self._repos = repositories
        self._mailer = mailer
        self._http = http
        self._slack_api_base = slack_api_base.rstrip("/")

    async def __call__(self, delivery_id: str, *, last_attempt: bool) -> None:
        delivery = await self._repos.deliveries.get(delivery_id)
        if delivery is None or delivery.status in {"sent", "skipped"}:
            return
        channel = await self._repos.channels.get(delivery.channel_id) if delivery.channel_id else None
        if delivery.channel_id and (channel is None or not channel.enabled):
            await self._repos.deliveries.finish(
                delivery.id, status="skipped", error="The channel was removed or disabled."
            )
            await self._repos.commit()
            return
        try:
            reference = await self._send(delivery, channel, Message.from_dict(delivery.message))
        except DeliveryError as exc:
            if exc.permanent or last_attempt:
                await self._repos.deliveries.finish(delivery.id, status="failed", error=str(exc)[:1000])
                await self._repos.commit()
                log.warning("notifications.delivery_failed", delivery=delivery.id, error=str(exc))
                return
            await self._repos.deliveries.finish(delivery.id, status="pending", error=str(exc)[:1000])
            await self._repos.commit()
            raise
        await self._repos.deliveries.finish(delivery.id, status="sent", message_ref=reference)
        await self._repos.commit()

    async def _send(self, delivery: Delivery, channel: Channel | None, message: Message) -> str | None:
        if delivery.channel == "email":
            subject, text = email_text(message)
            for address in [part.strip() for part in delivery.target.split(",") if part.strip()]:
                await self._mailer.send(Email(to=address, subject=subject, text=text))
            return None
        if channel is None:
            raise DeliveryError("The delivery names no channel.", permanent=True)
        config = channel.config
        if delivery.channel == "webhook":
            return await self._webhook(delivery, config, message)
        if delivery.channel == "slack_dm":
            email = delivery.target.removeprefix("dm:")
            user = await self._slack_api(config, "users.lookupByEmail", {"email": email}, form=True)
            slack_user = cast("dict[str, Any]", user.get("user") or {}).get("id")
            if not slack_user:
                raise DeliveryError(f"No Slack user has the address {email}.", permanent=True)
            return await self._slack_post(config, str(slack_user), message)
        if config.get("mode") == "webhook":
            response = await self._http.post(str(config["webhook_url"]), json=slack_payload(message))
            if not OK <= response.status < REDIRECT:
                raise DeliveryError(f"Slack answered HTTP {response.status}: {str(response.body)[:200]}")
            return None
        target = config.get("channel")
        if not target:
            raise DeliveryError("The Slack bot has no channel to post to.", permanent=True)
        return await self._slack_post(config, str(target), message)

    async def _slack_api(
        self, config: Mapping[str, Any], method: str, body: Mapping[str, Any], *, form: bool = False
    ) -> dict[str, Any]:
        """A Web API call; ``form`` for methods that don't take JSON bodies (``users.lookupByEmail``)."""
        base = str(config.get("api_base") or self._slack_api_base)
        headers = {"Authorization": f"Bearer {config.get('token', '')}"}
        url = f"{base}/{method}"
        if form:
            response = await self._http.post(url, form={k: str(v) for k, v in body.items()}, headers=headers)
        else:
            response = await self._http.post(url, json=dict(body), headers=headers)
        if not OK <= response.status < REDIRECT:
            raise DeliveryError(f"Slack {method} answered HTTP {response.status}")
        payload = cast("dict[str, Any]", response.body) if isinstance(response.body, dict) else {}
        if not payload.get("ok"):
            error = str(payload.get("error") or "unknown_error")
            permanent = error in {
                "invalid_auth",
                "not_authed",
                "account_inactive",
                "users_not_found",
                "channel_not_found",
            }
            raise DeliveryError(f"Slack {method} failed: {error}", permanent=permanent)
        return payload

    async def _slack_post(self, config: Mapping[str, Any], channel: str, message: Message) -> str | None:
        payload = await self._slack_api(config, "chat.postMessage", {"channel": channel, **slack_payload(message)})
        reference = payload.get("ts")
        return str(reference) if reference else None

    async def _webhook(self, delivery: Delivery, config: Mapping[str, Any], message: Message) -> str | None:
        body = webhook_body(message, delivery_id=delivery.id, sent_at=utcnow().isoformat())
        headers = {"Content-Type": "application/json", EVENT_HEADER: message.event_type}
        secret = config.get("secret")
        if secret:
            headers[SIGNATURE_HEADER] = sign(str(secret), body)
        response = await self._http.post(str(config["url"]), content=body, headers=headers)
        if not OK <= response.status < REDIRECT:
            raise DeliveryError(f"The webhook answered HTTP {response.status}")
        return None
