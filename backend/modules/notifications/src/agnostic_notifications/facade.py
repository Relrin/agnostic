"""The only import surface other modules may use: send a notification."""

from __future__ import annotations

from typing import Protocol

from agnostic_notifications.application.notify import NotificationRequest, Notify, NotifyResult

__all__ = ["NotificationRequest", "Notifier", "NotifierImpl", "NotifyResult"]


class Notifier(Protocol):
    async def notify(self, request: NotificationRequest) -> NotifyResult:
        """Inbox rows for the recipients, deliveries for their channels and the org channels that listen.

        Commits on its own: call it after the caller's change is committed.
        """
        ...


class NotifierImpl:
    def __init__(self, notify: Notify) -> None:
        self._notify = notify

    async def notify(self, request: NotificationRequest) -> NotifyResult:
        return await self._notify(request)
