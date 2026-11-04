"""Browser security headers for every response: content security policy with Trusted Types, HSTS and friends.

The policy allows only the control plane's own origin. Exceptions, each needed by the web app:

* ``'wasm-unsafe-eval'``: syntax highlighting compiles its grammar engine to WebAssembly;
* ``style-src 'unsafe-inline'``: the code editor, charts and highlighted code set inline ``style`` attributes;
* ``data:``/``blob:`` images and ``blob:`` workers: generated previews, exports and the layout worker;
* ``connect-src`` adds the runtimes switched to direct mode, plus ``AGNOSTIC_HTTP__CSP_EXTRA_CONNECT``.

``require-trusted-types-for 'script'`` makes DOM XSS sinks (``innerHTML``, script URLs) accept only values from
the web app's ``default`` policy. The interactive API docs page (Swagger UI from a CDN) gets a looser policy of
its own; air-gapped installations use the bundled API reference instead.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agnostic_kernel.logging import get_logger
from agnostic_kernel.settings import Settings

log = get_logger(__name__)

API_DOCS_PATH = "/api/v1/docs"
SWAGGER_CDN = "https://cdn.jsdelivr.net"
TRUSTED_TYPES_POLICY = "default"
"""The web app registers only the default policy (``apps/web/src/trusted-types.ts``): it refuses HTML strings and
allows same-origin script URLs, so it gates every dependency's sink as well."""
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"

type OriginProvider = Callable[[], Awaitable[Iterable[str]]]


def origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc}"


class ConnectSources:
    """Origins the web app may call besides its own (runtimes in direct mode), refreshed at most every ``ttl``."""

    def __init__(self, extra: Iterable[str] = (), *, ttl: float = 30.0) -> None:
        self._extra = tuple(origin for value in extra if (origin := origin_of(value)) is not None)
        self._providers: list[OriginProvider] = []
        self._ttl = ttl
        self._cached: tuple[str, ...] = self._extra
        self._at = 0.0

    def add_provider(self, provider: OriginProvider) -> None:
        self._providers.append(provider)
        self.invalidate()

    def invalidate(self) -> None:
        self._at = 0.0

    async def origins(self) -> tuple[str, ...]:
        if not self._providers or time.monotonic() - self._at < self._ttl:
            return self._cached
        found = set(self._extra)
        for provider in self._providers:
            try:
                found.update(origin for value in await provider() if (origin := origin_of(value)) is not None)
            except Exception as exc:  # noqa: BLE001  (keep the last known list rather than failing every page)
                log.warning("csp.connect_sources_failed", error=str(exc))
                return self._cached
        self._cached = tuple(sorted(found))
        self._at = time.monotonic()
        return self._cached


def content_security_policy(connect: Iterable[str] = ()) -> str:
    connect_src = " ".join(("'self'", *connect))
    directives = (
        "default-src 'self'",
        "script-src 'self' 'wasm-unsafe-eval'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        f"connect-src {connect_src}",
        "worker-src 'self' blob:",
        "frame-src 'none'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "manifest-src 'self'",
        "require-trusted-types-for 'script'",
        f"trusted-types {TRUSTED_TYPES_POLICY}",
    )
    return "; ".join(directives)


def api_docs_policy() -> str:
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self' 'unsafe-inline' {SWAGGER_CDN}",
            f"style-src 'self' 'unsafe-inline' {SWAGGER_CDN}",
            "img-src 'self' data: https://fastapi.tiangolo.com",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "base-uri 'none'",
        )
    )


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings, connect: Callable[[], Awaitable[tuple[str, ...]]]) -> None:
        self.app = app
        self._connect = connect
        self._csp_header = (
            "Content-Security-Policy-Report-Only" if settings.http.csp_report_only else "Content-Security-Policy"
        )
        public = settings.public_url()
        self._hsts = (
            f"max-age={settings.http.hsts_max_age}"
            if public.startswith("https://") and settings.http.hsts_max_age > 0
            else None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        policy = api_docs_policy() if path == API_DOCS_PATH else content_security_policy(await self._connect())

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault(self._csp_header, policy)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                if self._hsts is not None:
                    headers.setdefault("Strict-Transport-Security", self._hsts)
            await send(message)

        await self.app(scope, receive, send_wrapper)
