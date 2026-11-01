"""Gateway building blocks: route policies, header hygiene, SSE heartbeats, size limits, circuit breaker."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from agnostic_gateway.application.streaming import (
    HEARTBEAT,
    CircuitBreaker,
    PayloadTooLargeError,
    limited,
    with_heartbeats,
)
from agnostic_gateway.domain.policies import (
    DEFAULT_POLICIES,
    PolicyTable,
    RoutePolicy,
    merged,
    request_headers,
    response_headers,
    scopes_for_token,
)

TABLE = PolicyTable(DEFAULT_POLICIES)


@pytest.mark.parametrize(
    ("method", "path", "pattern", "scopes"),
    [
        ("GET", "/sessions/filter-schema", "/sessions/filter-schema", ("sessions:read",)),
        ("GET", "/sessions/ses_1", "/sessions/{session_id}", ("sessions:read",)),
        ("GET", "/components/c1/configs/current", "/components/{component_id}/configs/current", ("components:read",)),
        ("GET", "/components/c1/configs/3", "/components/{component_id}/configs/{version}", ("components:read",)),
        ("POST", "/teams/research/runs", "/teams/{team_id}/runs", ("teams:research:run",)),
        (
            "GET",
            "/agents/triage/runs/r1",
            "/agents/{agent_id}/runs/{run_id}",
            ("agents:triage:read", "agents:triage:run"),
        ),
        ("GET", "/filesystem/entries/a/b", "/filesystem/{rest*}", ("filesystem:read",)),
        ("HEAD", "/config", "/config", ("config:read",)),
        ("GET", "/health", "/health", ()),
    ],
)
def test_policy_matching(method: str, path: str, pattern: str, scopes: tuple[str, ...]) -> None:
    policy, params = TABLE.match(method, path)
    assert policy.pattern == pattern
    assert policy.required(params) == scopes


def test_unknown_routes_fail_closed_and_overrides_win() -> None:
    policy, _ = TABLE.match("POST", "/company/tasks")
    assert (policy.source, policy.scopes) == ("fallback", ("agent_os:admin",))
    override = RoutePolicy("GET", "/metrics", ("metrics:read", "traces:read"), source="override")
    table = PolicyTable(merged(DEFAULT_POLICIES, [override]))
    assert table.match("GET", "/metrics")[0].scopes == ("metrics:read", "traces:read")
    assert TABLE.match("GET", "/agents")[0].list_filter


def test_header_hygiene() -> None:
    forwarded = request_headers(
        [
            ("Cookie", "agnostic_session=x"),
            ("Authorization", "Bearer user-supplied"),
            ("X-CSRF-Token", "t"),
            ("Connection", "keep-alive"),
            ("Idempotency-Key", "abc"),
            ("Last-Event-ID", "7"),
            ("Content-Type", "application/json"),
        ]
    )
    assert forwarded == {"Idempotency-Key": "abc", "Last-Event-ID": "7", "Content-Type": "application/json"}
    upstream = [("Set-Cookie", "x=1"), ("Content-Length", "10"), ("Content-Type", "text/event-stream"), ("Server", "x")]
    assert response_headers(upstream, streaming=True) == {"Content-Type": "text/event-stream"}
    assert "Content-Length" in response_headers(upstream, streaming=False)


def test_scope_list_is_trimmed_to_the_route_family_past_8kb() -> None:
    scopes = [f"agents:agent-{n:04d}:run" for n in range(400)] + ["sessions:read"]
    trimmed, was_trimmed = scopes_for_token(scopes, "sessions")
    assert was_trimmed
    assert trimmed == ["sessions:read"]
    assert scopes_for_token(["sessions:read"], "agents") == (["sessions:read"], False)


async def _chunks(*parts: tuple[float, bytes]) -> AsyncIterator[bytes]:
    for delay, chunk in parts:
        await asyncio.sleep(delay)
        yield chunk


async def test_heartbeats_only_between_events() -> None:
    source = _chunks((0, b"event: A\ndata: 1"), (0.08, b"\n\n"), (0.08, b"event: B\ndata: 2\n\n"))
    out = [chunk async for chunk in with_heartbeats(source, 0.05)]
    first_heartbeat = out.index(HEARTBEAT)
    assert b"".join(out[:first_heartbeat]).endswith(b"\n\n")  # never inside "event: A"
    assert b"".join(c for c in out if c != HEARTBEAT) == b"event: A\ndata: 1\n\nevent: B\ndata: 2\n\n"


async def test_heartbeats_propagate_upstream_errors() -> None:
    async def broken() -> AsyncIterator[bytes]:
        yield b"data: 1\n\n"
        raise ConnectionError("reset")

    with pytest.raises(ConnectionError):
        _ = [chunk async for chunk in with_heartbeats(broken(), 1)]


async def test_body_size_limit() -> None:
    assert [c async for c in limited(_chunks((0, b"12"), (0, b"34")), 4)] == [b"12", b"34"]
    with pytest.raises(PayloadTooLargeError):
        _ = [c async for c in limited(_chunks((0, b"123"), (0, b"45")), 4)]


def test_circuit_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("agnostic_gateway.application.streaming.time.monotonic", lambda: clock[0])
    breaker = CircuitBreaker(threshold=2, cooldown=10)
    breaker.failure("ins")
    assert breaker.retry_after("ins") is None
    breaker.failure("ins")
    assert breaker.retry_after("ins") == pytest.approx(10)
    clock[0] += 11
    assert breaker.retry_after("ins") is None  # half-open: one probe goes through
    assert breaker.retry_after("ins") == pytest.approx(10)
    breaker.success("ins")
    assert breaker.retry_after("ins") is None
