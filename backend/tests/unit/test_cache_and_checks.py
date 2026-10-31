"""Cache classification and endpoint checks that don't need a live server."""

import pytest
from redis.asyncio import Redis

from agnostic_kernel.cache import classify_server, create_redis
from agnostic_kernel.checks import check_cache, check_database, check_otel, run_endpoint_checks
from agnostic_kernel.db import create_engine, psycopg_conninfo
from agnostic_kernel.settings import DatabaseSettings, OtelSettings, RedisSettings
from agnostic_kernel.testing import UNREACHABLE_REDIS, make_settings


@pytest.mark.parametrize(
    ("info", "kind", "version"),
    [
        ({"redis_version": "8.10.3"}, "redis", "8.10.3"),
        ({"redis_version": "7.2.4", "valkey_version": "9.1.3", "server_name": "valkey"}, "valkey", "9.1.3"),
        ({"redis_version": "7.2.4", "server_name": "Valkey"}, "valkey", "7.2.4"),
        ({"redis_version": "7.4.0", "dragonfly_version": "df-v1.40.2"}, "dragonfly", "df-v1.40.2"),
        ({}, "unknown", ""),
    ],
)
def test_classify_server(info: dict[str, object], kind: str, version: str) -> None:
    server = classify_server(info)
    assert (server.kind, server.version) == (kind, version)


def test_sentinel_needs_master() -> None:
    with pytest.raises(ValueError, match="SENTINEL_MASTER"):
        create_redis(RedisSettings(sentinels=["s1:26379"]))


def test_sentinel_client() -> None:
    client = create_redis(RedisSettings(sentinels=["s1:26379", "s2"], sentinel_master="mymaster"))
    assert isinstance(client, Redis)


async def test_unreachable_cache_is_reported() -> None:
    client = create_redis(RedisSettings(url=UNREACHABLE_REDIS, socket_timeout=1))  # pyright: ignore[reportArgumentType]
    result = await check_cache(client)
    await client.aclose()
    assert not result.ok
    assert "unreachable" in result.detail


async def test_sqlite_database_check(sqlite_database: str) -> None:
    engine = create_engine(DatabaseSettings(url=sqlite_database))  # pyright: ignore[reportArgumentType]
    result = await check_database(engine)
    await engine.dispose()
    assert result.ok
    assert result.facts["backend"] == "sqlite"


async def test_unreachable_postgres_is_reported() -> None:
    engine = create_engine(DatabaseSettings(url="postgresql://x:y@127.0.0.1:1/db", connect_timeout=1))  # pyright: ignore[reportArgumentType]
    result = await check_database(engine)
    await engine.dispose()
    assert not result.ok


async def test_run_endpoint_checks_on_sqlite(sqlite_database: str) -> None:
    results = await run_endpoint_checks(make_settings(sqlite_database), [])
    by_name = {r.name: r for r in results}
    assert by_name["database"].ok
    assert not by_name["cache"].ok
    assert not by_name["migrations"].ok  # nothing applied yet


async def test_otel_check() -> None:
    assert await check_otel(OtelSettings()) is None
    result = await check_otel(OtelSettings(endpoint="http://127.0.0.1:1/v1/traces"))
    assert result is not None
    assert not result.ok


def test_psycopg_conninfo() -> None:
    settings = DatabaseSettings(url="postgresql://u:p@db:5433/cp?sslmode=disable", sslmode="require")  # pyright: ignore[reportArgumentType]
    conninfo = psycopg_conninfo(settings, search_path="procrastinate")
    assert "host=db" in conninfo
    assert "port=5433" in conninfo
    assert "sslmode=require" in conninfo
    assert "search_path=procrastinate" in conninfo
    with pytest.raises(ValueError, match="PostgreSQL"):
        psycopg_conninfo(DatabaseSettings(url="sqlite:///x.db"))  # pyright: ignore[reportArgumentType]
