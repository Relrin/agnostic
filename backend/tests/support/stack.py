"""The whole control plane on SQLite (in-process cache, embedded jobs) with a fake AgentOS behind the gateway."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from asgi_lifespan import LifespanManager
from dishka import AsyncContainer, Provider, Scope, provide
from dishka.integrations.fastapi import FastapiProvider
from fastapi import FastAPI

from agnostic_gateway.application.ports import Upstream
from agnostic_gateway.infrastructure.upstream import UpstreamPool
from agnostic_instances.application.ports import RuntimeClient
from agnostic_instances.infrastructure.runtime import HttpRuntimeClient
from agnostic_kernel import migrations_runner
from agnostic_kernel.auth import HttpAuthProvider
from agnostic_kernel.bootstrap import Bootstrapper, BootstrapResult, OwnerAccount
from agnostic_kernel.container import build_container
from agnostic_kernel.db import create_engine
from agnostic_kernel.mail import Email, Mailer
from agnostic_kernel.modules import load_modules
from agnostic_kernel.settings import Settings
from agnostic_kernel.testing import make_settings
from agnostic_notifications.application.ports import OutboundHttp
from agnostic_server.app import create_app
from tests.support.fake_agentos import FakeAgentOS
from tests.support.fake_slack import FakeSlack

PUBLIC_URL = "http://agnostic.test"
OWNER_PASSWORD = "correct horse battery staple"


class FakeDnsRuntimeClient(HttpRuntimeClient):
    async def resolve(self, host: str, port: int) -> list[str]:
        if host.endswith(".invalid"):
            raise OSError(f"[Errno 11001] getaddrinfo failed for {host}")
        return ["10.0.0.7"]


@dataclass
class CapturingMailer:
    sent: list[Email] = field(default_factory=list[Email])

    async def send(self, email: Email) -> None:
        self.sent.append(email)


class Routes:
    """Routes runtime traffic by host to fake runtimes (``prod.agentos.test`` → one fake app)."""

    def __init__(self) -> None:
        self.runtimes: dict[str, FakeAgentOS] = {}

    def transport(self) -> httpx.AsyncBaseTransport:
        routes = self

        class _Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                runtime = routes.runtimes.get(request.url.host)
                if runtime is None:
                    raise httpx.ConnectError(f"Connection refused: {request.url.host}", request=request)
                return await httpx.ASGITransport(app=runtime.app).handle_async_request(request)

        return _Transport()


@dataclass
class Stack:
    app: FastAPI
    container: AsyncContainer
    routes: Routes
    mailer: CapturingMailer
    settings: Settings
    slack: FakeSlack
    clients: list[httpx.AsyncClient] = field(default_factory=list[httpx.AsyncClient])

    def runtime(self, host: str, **kwargs: Any) -> FakeAgentOS:
        fake = FakeAgentOS(**kwargs)
        self.routes.runtimes[host] = fake
        return fake

    def client(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=PUBLIC_URL)
        self.clients.append(client)
        return client

    async def bootstrap(
        self, org_name: str = "Localhost Company", owner: OwnerAccount | None = None
    ) -> BootstrapResult:
        async with self.container() as request:
            return await (await request.get(Bootstrapper)).bootstrap(org_name, owner)

    async def sign_in(self, email: str, password: str) -> httpx.AsyncClient:
        client = self.client()
        response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client

    async def owner(self) -> httpx.AsyncClient:
        _ = await self.bootstrap(owner=OwnerAccount("daniel@localhost.company", "Daniel Okafor", OWNER_PASSWORD))
        return await self.sign_in("daniel@localhost.company", OWNER_PASSWORD)


async def migrate(settings: Settings) -> None:
    engine = create_engine(settings.database)
    await migrations_runner.upgrade(engine, list(load_modules().installed.values()))
    await engine.dispose()


@asynccontextmanager
async def running_stack(database_url: str, **overrides: Any) -> AsyncGenerator[Stack]:
    settings = make_settings(database_url, http={"public_url": PUBLIC_URL}, **overrides)
    await migrate(settings)
    routes = Routes()
    mailer = CapturingMailer()
    slack = FakeSlack()
    transport = routes.transport()

    class TestAdapters(Provider):
        @provide(scope=Scope.APP)
        def runtime(self) -> RuntimeClient:
            return FakeDnsRuntimeClient(transport)

        @provide(scope=Scope.APP)
        async def upstream(self) -> AsyncIterator[Upstream]:
            pool = UpstreamPool(read_timeout=30, transport=transport)
            yield pool
            await pool.aclose()

        @provide(scope=Scope.APP)
        def mail(self) -> Mailer:
            return mailer

        @provide(scope=Scope.APP)
        def outbound(self) -> OutboundHttp:
            return slack

    modules = load_modules(settings.modules.disabled)
    container = build_container(
        settings, modules, extra=(FastapiProvider(), HttpAuthProvider()), overrides=(TestAdapters(),)
    )
    app = create_app(settings, modules=modules, container=container)
    async with LifespanManager(app):
        stack = Stack(app=app, container=container, routes=routes, mailer=mailer, settings=settings, slack=slack)
        try:
            yield stack
        finally:
            for client in stack.clients:
                await client.aclose()
