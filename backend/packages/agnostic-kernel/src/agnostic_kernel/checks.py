"""Endpoint probes shared by ``/readyz`` and ``agnostic config check --connect``."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from agnostic_kernel.cache import create_redis, detect_server, probe_commands
from agnostic_kernel.db import create_engine
from agnostic_kernel.migrations_runner import state
from agnostic_kernel.modules import Module
from agnostic_kernel.settings import OtelSettings, Settings

REQUIRED_EXTENSIONS = ("citext", "pg_trgm")
MIN_POSTGRES_MAJOR = 17
CHECK_TIMEOUT = 5.0


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    facts: dict[str, str] = field(default_factory=dict)


async def check_database(engine: AsyncEngine) -> CheckResult:
    if engine.dialect.name == "sqlite":
        return await _check_sqlite(engine)
    try:
        async with asyncio.timeout(CHECK_TIMEOUT), engine.connect() as connection:
            version_num = int((await connection.execute(text("SHOW server_version_num"))).scalar_one())
            version = str((await connection.execute(text("SHOW server_version"))).scalar_one())
            ssl = (
                await connection.execute(text("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"))
            ).scalar_one_or_none()
            rows = await connection.execute(
                text(
                    "SELECT name, installed_version IS NOT NULL FROM pg_available_extensions WHERE name = ANY(:names)"
                ),
                {"names": list(REQUIRED_EXTENSIONS)},
            )
            extensions = {str(name): bool(installed) for name, installed in rows}
    except (OSError, TimeoutError, SQLAlchemyError) as exc:
        return CheckResult("database", ok=False, detail=f"unreachable: {exc}")

    facts = {
        "backend": "postgresql",
        "version": version,
        "tls": "on" if ssl else "off",
        **{f"extension.{name}": _extension_state(name, extensions) for name in REQUIRED_EXTENSIONS},
    }
    problems: list[str] = []
    if version_num // 10000 < MIN_POSTGRES_MAJOR:
        problems.append(f"PostgreSQL {MIN_POSTGRES_MAJOR}+ is required")
    missing = [name for name in REQUIRED_EXTENSIONS if name not in extensions]
    if missing:
        problems.append(f"extensions not available: {', '.join(missing)}")
    return CheckResult("database", ok=not problems, detail="; ".join(problems) or "ok", facts=facts)


async def _check_sqlite(engine: AsyncEngine) -> CheckResult:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT), engine.connect() as connection:
            version = str((await connection.execute(text("SELECT sqlite_version()"))).scalar_one())
    except (OSError, TimeoutError, SQLAlchemyError) as exc:
        return CheckResult("database", ok=False, detail=f"unusable: {exc}")
    facts = {"backend": "sqlite", "version": version, "database": str(engine.url.database or ":memory:")}
    return CheckResult("database", ok=True, detail="ok (SQLite: development and evaluation only)", facts=facts)


def _extension_state(name: str, extensions: dict[str, bool]) -> str:
    if name not in extensions:
        return "missing"
    return "installed" if extensions[name] else "available"


async def check_cache(redis: Redis, *, probe: bool = True) -> CheckResult:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            _ = await redis.ping()  # pyright: ignore[reportUnknownMemberType]
            server = await detect_server(redis)
            commands = await probe_commands(redis) if probe else None
    except (OSError, TimeoutError, RedisError) as exc:
        return CheckResult("cache", ok=False, detail=f"unreachable: {exc}")

    facts = {"server": server.kind, "version": server.version}
    if commands is None:
        return CheckResult("cache", ok=True, detail="ok", facts=facts)
    facts["commands"] = f"{len(commands.ok)} ok, {len(commands.failed)} failed"
    if commands.failed:
        detail = "unsupported: " + ", ".join(f"{name} ({error})" for name, error in commands.failed.items())
        return CheckResult("cache", ok=False, detail=detail, facts=facts)
    return CheckResult("cache", ok=True, detail="ok", facts=facts)


async def check_migrations(engine: AsyncEngine, modules: Sequence[Module]) -> CheckResult:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            current = await state(engine, modules)
    except (OSError, TimeoutError, SQLAlchemyError) as exc:
        return CheckResult("migrations", ok=False, detail=f"cannot read migration state: {exc}")
    facts = {"current": ",".join(current.current) or "none", "pending": ",".join(current.pending) or "none"}
    if current.up_to_date:
        return CheckResult("migrations", ok=True, detail="ok", facts=facts)
    return CheckResult("migrations", ok=False, detail="pending migrations: run `agnostic db upgrade`", facts=facts)


async def check_otel(settings: OtelSettings) -> CheckResult | None:
    if not settings.endpoint:
        return None
    verify: bool | str = str(settings.tls.ca_file) if settings.tls.ca_file else True
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT, verify=verify) as client:
            response = await client.get(settings.endpoint)
    except httpx.HTTPError as exc:
        return CheckResult("otel", ok=False, detail=f"unreachable: {exc}")
    return CheckResult("otel", ok=True, detail="reachable", facts={"status": str(response.status_code)})


async def run_endpoint_checks(settings: Settings, modules: Sequence[Module]) -> list[CheckResult]:
    """Probe every configured endpoint with fresh connections (used by the CLI)."""
    engine = create_engine(settings.database)
    redis = create_redis(settings.redis)
    try:
        results = [await check_database(engine), await check_cache(redis)]
        if results[0].ok:
            results.append(await check_migrations(engine, modules))
        otel = await check_otel(settings.otel)
        if otel is not None:
            results.append(otel)
        return results
    finally:
        await redis.aclose()
        await engine.dispose()
