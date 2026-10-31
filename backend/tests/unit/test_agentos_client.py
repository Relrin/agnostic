"""AgentOS client transport, auth and error mapping (no live runtime)."""

from collections.abc import Iterator

import httpx
import pytest
import respx

from agnostic_agentos_client import (
    AgentOSClient,
    BearerAuth,
    CapabilityDisabledError,
    ForbiddenError,
    InstanceAuthFailedError,
    InstanceUnreachableError,
    NotFoundError,
    SecurityKeyAuth,
    UnexpectedResponseError,
)

BASE = "http://os.test"
INFO = {"os_id": "dev-prod", "os_version": "1.0", "agno_version": "3.1.12", "auth_mode": "jwt", "agent_count": 6}


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


def client(**kwargs: object) -> AgentOSClient:
    return AgentOSClient(BASE, transport=httpx.AsyncHTTPTransport(retries=0), backoff=0, **kwargs)  # pyright: ignore[reportArgumentType]


async def test_typed_responses(router: respx.MockRouter) -> None:
    router.get("/health").respond(json={"status": "ok", "instantiated_at": "2026-10-31T22:29:53Z"})
    router.get("/info").respond(json=INFO)
    router.get("/config").respond(json={"os_id": "dev-prod", "agents": [{"id": "support-triage"}], "queue": {}})
    async with client() as os_client:
        assert (await os_client.health()).status == "ok"
        info = await os_client.info()
        assert (info.os_id, info.agno_version, info.agent_count) == ("dev-prod", "3.1.12", 6)
        config = await os_client.config()
        assert config.agents[0].id == "support-triage"
        assert config.queue == {}


async def test_auth_headers(router: respx.MockRouter) -> None:
    route = router.get("/info").respond(json=INFO)

    async def token() -> str:
        return "jwt-123"

    async with client(auth=BearerAuth(token)) as os_client:
        await os_client.info()
    assert route.calls.last.request.headers["Authorization"] == "Bearer jwt-123"
    async with client(auth=SecurityKeyAuth("key")) as os_client:
        await os_client.info()
    assert route.calls.last.request.headers["Authorization"] == "Bearer key"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, InstanceAuthFailedError),
        (403, ForbiddenError),
        (404, NotFoundError),
        (503, CapabilityDisabledError),
        (500, UnexpectedResponseError),
    ],
)
async def test_status_mapping(router: respx.MockRouter, status: int, error: type[Exception]) -> None:
    router.get("/info").respond(status_code=status, text="nope")
    async with client(retries=0) as os_client:
        with pytest.raises(error):
            await os_client.info()


async def test_retries_transient_failures(router: respx.MockRouter) -> None:
    route = router.get("/info")
    route.side_effect = [httpx.ConnectError("down"), httpx.Response(503), httpx.Response(200, json=INFO)]
    async with client(retries=2) as os_client:
        assert (await os_client.info()).os_id == "dev-prod"
    assert route.call_count == 3


async def test_unreachable_after_retries(router: respx.MockRouter) -> None:
    router.get("/info").side_effect = httpx.ConnectTimeout("slow")
    async with client(retries=1) as os_client:
        with pytest.raises(InstanceUnreachableError):
            await os_client.info()


async def test_schema_mismatch(router: respx.MockRouter) -> None:
    router.get("/info").respond(json={"unexpected": True})
    async with client() as os_client:
        with pytest.raises(UnexpectedResponseError, match="pinned AgentOS schema"):
            await os_client.info()


async def test_request_id_header(router: respx.MockRouter) -> None:
    route = router.get("/health").respond(json={"status": "ok", "instantiated_at": "2026-10-31T22:29:53Z"})
    async with client() as os_client:
        await os_client._get("/health", request_id="req_1")
    assert route.calls.last.request.headers["X-Request-Id"] == "req_1"
