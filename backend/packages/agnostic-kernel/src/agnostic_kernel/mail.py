"""Outgoing email.

SMTP is an endpoint like the database; without one, emails go to the log so local installs still work
(the links are printed where the operator can see them).
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import unquote, urlsplit

from agnostic_kernel.logging import get_logger
from agnostic_kernel.settings import SmtpSettings

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Email:
    to: str
    subject: str
    text: str


class Mailer(Protocol):
    async def send(self, email: Email) -> None: ...


class LogMailer:
    """Development fallback: the message, links included, goes to the log."""

    async def send(self, email: Email) -> None:
        log.warning("mail.not_configured", to=email.to, subject=email.subject, body=email.text)


class SmtpMailer:
    def __init__(self, settings: SmtpSettings) -> None:
        assert settings.url is not None
        self._settings = settings
        self._url = urlsplit(settings.url.get_secret_value())

    def _context(self) -> ssl.SSLContext:
        tls = self._settings.tls
        context = ssl.create_default_context(cafile=str(tls.ca_file) if tls.ca_file else None)
        if tls.cert_file:
            context.load_cert_chain(str(tls.cert_file), str(tls.key_file) if tls.key_file else None)
        return context

    def _connect(self) -> smtplib.SMTP:
        host = self._url.hostname or "localhost"
        timeout = self._settings.timeout
        if self._url.scheme == "smtps":
            return smtplib.SMTP_SSL(host, self._url.port or 465, timeout=timeout, context=self._context())
        return smtplib.SMTP(host, self._url.port or 587, timeout=timeout)

    def _session(self, client: smtplib.SMTP) -> bool:
        """STARTTLS when offered, then log in; ``True`` when the connection is encrypted."""
        encrypted = self._url.scheme == "smtps"
        _ = client.ehlo()  # has_extn() only knows the server's extensions after EHLO
        if self._url.scheme == "smtp" and client.has_extn("starttls"):
            client.starttls(context=self._context())
            encrypted = True
        if self._url.username:
            client.login(unquote(self._url.username), unquote(self._url.password or ""))
        return encrypted

    def _send_sync(self, message: EmailMessage) -> None:
        with self._connect() as client:
            _ = self._session(client)
            client.send_message(message)

    def _probe_sync(self) -> bool:
        with self._connect() as client:
            encrypted = self._session(client)
            _ = client.noop()
            return encrypted

    async def probe(self) -> bool:
        """Connect, negotiate TLS and log in without sending anything; ``True`` when TLS is on."""
        return await asyncio.to_thread(self._probe_sync)

    async def send(self, email: Email) -> None:
        message = EmailMessage()
        message["From"] = self._settings.sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.text)
        await asyncio.to_thread(self._send_sync, message)
        log.info("mail.sent", to=email.to, subject=email.subject)


def create_mailer(settings: SmtpSettings) -> Mailer:
    return SmtpMailer(settings) if settings.url is not None else LogMailer()
