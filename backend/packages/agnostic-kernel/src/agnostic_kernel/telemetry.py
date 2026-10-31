"""OpenTelemetry tracing. Spans are exported over OTLP/HTTP to the operator's collector, when one is configured."""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_kernel.settings import OtelSettings


def configure_tracing(settings: OtelSettings) -> TracerProvider | None:
    """Install a global tracer provider and client instrumentation. Returns ``None`` when tracing is off."""
    if not settings.endpoint:
        return None
    exporter = OTLPSpanExporter(
        endpoint=settings.endpoint,
        headers={key: value.get_secret_value() for key, value in settings.headers.items()},
        certificate_file=str(settings.tls.ca_file) if settings.tls.ca_file else None,
        client_certificate_file=str(settings.tls.cert_file) if settings.tls.cert_file else None,
        client_key_file=str(settings.tls.key_file) if settings.tls.key_file else None,
    )
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.service_name}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()  # pyright: ignore[reportUnknownMemberType]
    RedisInstrumentor().instrument()  # pyright: ignore[reportUnknownMemberType]
    return provider


def instrument_app(app: FastAPI, provider: TracerProvider | None) -> None:
    if provider is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, excluded_urls="healthz,readyz")


def instrument_engine(engine: AsyncEngine, provider: TracerProvider | None) -> None:
    if provider is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine, tracer_provider=provider)  # pyright: ignore[reportUnknownMemberType]
