"""Prometheus metrics of the control plane itself, on a metrics port of their own (API and worker).

Request metrics are labelled by route template (``/api/v1/instances/{instance}/os/{path:path}``), never by raw
path, so cardinality stays bounded. Latency is time to the response headers: streamed responses (SSE) would
otherwise report their whole lifetime.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)
from prometheus_client.gc_collector import GCCollector
from prometheus_client.platform_collector import PlatformCollector
from prometheus_client.process_collector import ProcessCollector
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agnostic_kernel.logging import get_logger
from agnostic_kernel.settings import MetricsSettings

log = get_logger(__name__)

REGISTRY = CollectorRegistry()
_ = ProcessCollector(registry=REGISTRY)
_ = PlatformCollector(registry=REGISTRY)
_ = GCCollector(registry=REGISTRY)

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

http_requests = Counter(
    "agnostic_http_requests", "HTTP requests handled", ("method", "route", "status"), registry=REGISTRY
)
http_latency = Histogram(
    "agnostic_http_request_duration_seconds",
    "Time to the response headers",
    ("method", "route"),
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
http_in_flight = Gauge("agnostic_http_requests_in_flight", "Requests being handled", registry=REGISTRY)
gateway_upstream = Histogram(
    "agnostic_gateway_upstream_duration_seconds",
    "AgentOS response time through the gateway (to the response headers)",
    ("instance", "outcome"),
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
gateway_overhead = Histogram(
    "agnostic_gateway_overhead_seconds",
    "Time the gateway spends before forwarding a request (policy, scopes, rate limit, token)",
    ("instance",),
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
    registry=REGISTRY,
)
gateway_denials = Counter(
    "agnostic_gateway_denials",
    "Gateway requests refused before reaching AgentOS",
    ("instance", "reason"),
    registry=REGISTRY,
)
sse_streams = Gauge("agnostic_sse_streams", "Server-sent event streams open", ("instance",), registry=REGISTRY)
token_mints = Counter("agnostic_jwt_mints", "Runtime JWTs minted (cache misses)", ("via",), registry=REGISTRY)
cache_lookups = Counter("agnostic_cache_lookups", "Ephemeral-store reads by result", ("result",), registry=REGISTRY)
job_queue_depth = Gauge("agnostic_jobs_waiting", "Jobs waiting in a queue", ("queue",), registry=REGISTRY)
job_queue_running = Gauge("agnostic_jobs_running", "Jobs being worked on", ("queue",), registry=REGISTRY)
job_queue_failed = Gauge("agnostic_jobs_failed", "Failed jobs kept for inspection", ("queue",), registry=REGISTRY)
job_queue_lag = Gauge(
    "agnostic_jobs_oldest_wait_seconds", "Age of the oldest due job not picked up yet", ("queue",), registry=REGISTRY
)
info = Gauge("agnostic_build_info", "Version of the running control plane", ("version",), registry=REGISTRY)


def route_template(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


class MetricsMiddleware:
    """HTTP RED metrics for every request except ``/metrics`` itself."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = "500"

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = str(message["status"])
                http_latency.labels(scope["method"], route_template(scope)).observe(time.perf_counter() - started)
            await send(message)

        http_in_flight.inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            http_in_flight.dec()
            http_requests.labels(scope["method"], route_template(scope), status).inc()


def metrics_endpoint(settings: MetricsSettings) -> Callable[[Request], Awaitable[Response]]:
    token = settings.token.get_secret_value() if settings.token is not None else None

    async def metrics(request: Request) -> Response:
        if token is not None:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    return metrics


def serve_metrics(settings: MetricsSettings) -> None:
    """Expose the registry on ``settings.port`` from a background thread (the API's and the worker's listener)."""
    if not settings.enabled:
        return
    _ = start_http_server(settings.port, registry=REGISTRY)
    log.info("metrics.endpoint", port=settings.port)


type Refresh = Callable[[], Awaitable[None]]


@asynccontextmanager
async def refreshing(refresh: Refresh, *, every: float = 15.0) -> AsyncGenerator[None]:
    """Run ``refresh`` (gauges read from the database) every ``every`` seconds while the context is open."""

    async def loop() -> None:
        while True:
            try:
                await refresh()
            except Exception as exc:  # noqa: BLE001  (a failed refresh leaves the last values; next round retries)
                log.warning("metrics.refresh_failed", error=str(exc))
            await asyncio.sleep(every)

    task = asyncio.create_task(loop(), name="agnostic-metrics-refresh")
    try:
        yield
    finally:
        _ = task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
