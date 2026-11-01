"""Kernel pieces added in P01 that the API tests don't reach: SMTP delivery and the Redis-backed store."""

import ssl
from email.message import EmailMessage
from typing import Any, Self

import pytest

from agnostic_kernel.ephemeral import MemoryStore, RedisStore
from agnostic_kernel.mail import Email, LogMailer, SmtpMailer, create_mailer
from agnostic_kernel.settings import SmtpSettings


class FakeSmtp:
    instances: list[FakeSmtp] = []  # noqa: RUF012

    def __init__(self, host: str, port: int, timeout: float, context: ssl.SSLContext | None = None) -> None:
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[tuple[str, Any]] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append(("quit", None))

    def has_extn(self, name: str) -> bool:
        return name == "starttls"

    def starttls(self, context: ssl.SSLContext) -> None:
        self.calls.append(("starttls", context))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", (user, password)))

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append(("send", message))


async def test_smtp_mailer(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSmtp.instances.clear()
    monkeypatch.setattr("smtplib.SMTP", FakeSmtp)
    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSmtp)
    settings = SmtpSettings(url="smtp://user%40corp:p%40ss@mail.corp:2525", sender="Agnostic <a@corp>")  # pyright: ignore[reportArgumentType]
    mailer = create_mailer(settings)
    assert isinstance(mailer, SmtpMailer)
    await mailer.send(Email(to="marcus@localhost.company", subject="Hi", text="Body"))
    smtp = FakeSmtp.instances[-1]
    assert (smtp.host, smtp.port) == ("mail.corp", 2525)
    kinds = [kind for kind, _ in smtp.calls]
    assert kinds == ["starttls", "login", "send", "quit"]
    assert smtp.calls[1][1] == ("user@corp", "p@ss")
    message = smtp.calls[2][1]
    assert (message["To"], message["From"], message["Subject"]) == (
        "marcus@localhost.company",
        "Agnostic <a@corp>",
        "Hi",
    )

    implicit = SmtpMailer(SmtpSettings(url="smtps://mail.corp"))  # pyright: ignore[reportArgumentType]
    await implicit.send(Email(to="x@y.dev", subject="s", text="t"))
    assert FakeSmtp.instances[-1].port == 465
    assert FakeSmtp.instances[-1].context is not None
    assert isinstance(create_mailer(SmtpSettings()), LogMailer)
    await LogMailer().send(Email(to="x@y.dev", subject="s", text="t"))


class FakeRedis:
    """Just the commands RedisStore uses, with MemoryStore semantics underneath."""

    def __init__(self) -> None:
        self.memory = MemoryStore()

    async def get(self, key: str) -> bytes | None:
        return await self.memory.get(key)

    async def set(self, key: str, value: bytes, px: int | None = None, nx: bool = False) -> bool | None:
        if nx:
            return await self.memory.set_if_absent(key, value, ttl=(px or 0) / 1000)
        await self.memory.set(key, value, ttl=(px / 1000) if px else None)
        return True

    async def execute_command(self, name: str, key: str) -> bytes | None:
        assert name == "GETDEL"
        return await self.memory.pop(key)

    async def delete(self, *keys: str) -> None:
        await self.memory.delete(*keys)

    async def incr(self, key: str) -> int:
        return await self.memory.incr(key, ttl=3600)

    async def pexpire(self, key: str, ms: int) -> None:
        await self.memory.expire(key, ms / 1000)


async def test_redis_store_prefixes_keys() -> None:
    redis = FakeRedis()
    store = RedisStore(redis, prefix="t:")  # pyright: ignore[reportArgumentType]
    await store.set("a", b"1", ttl=10)
    assert list(redis.memory.keys()) == ["t:a"]
    assert await store.get("a") == b"1"
    assert not await store.set_if_absent("a", b"2", ttl=10)
    assert await store.pop("a") == b"1"
    assert await store.incr("n", ttl=10) == 1
    await store.expire("n", 10)
    await store.delete("n")
    await store.delete()
    assert list(redis.memory.keys()) == []
