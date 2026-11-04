"""The content security policy: what it allows, and that the web app's preview server sends the same one."""

import re
from pathlib import Path

from agnostic_kernel.security_headers import ConnectSources, content_security_policy, origin_of

PREVIEW_HEADERS = Path(__file__).resolve().parents[3] / "frontend" / "apps" / "web" / "security-headers.ts"


def test_policy_allows_only_this_origin_and_direct_runtimes() -> None:
    policy = content_security_policy(["https://agentos.corp"])
    directives = dict(part.split(" ", 1) for part in policy.split("; "))
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self' 'wasm-unsafe-eval'"
    assert directives["connect-src"] == "'self' https://agentos.corp"
    assert directives["require-trusted-types-for"] == "'script'"
    assert directives["trusted-types"] == "default"
    assert "unsafe-eval'" not in directives["script-src"].replace("wasm-unsafe-eval", "")


def test_preview_server_sends_the_same_policy() -> None:
    match = re.search(r'CONTENT_SECURITY_POLICY\s*=\s*"([^"]+)"', PREVIEW_HEADERS.read_text(encoding="utf-8"))
    assert match is not None
    assert match.group(1) == content_security_policy()


def test_origin_of() -> None:
    assert origin_of("https://agentos.corp:8443/os/") == "https://agentos.corp:8443"
    assert origin_of("agentos.corp") is None
    assert origin_of("javascript:alert(1)") is None


async def test_connect_sources_cache_and_survive_provider_errors() -> None:
    calls = 0

    async def provider() -> list[str]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("database down")
        return ["https://a.corp/os", "not a url"]

    sources = ConnectSources(["https://extra.corp"], ttl=3600)
    sources.add_provider(provider)
    assert await sources.origins() == ("https://a.corp", "https://extra.corp")
    assert await sources.origins() == ("https://a.corp", "https://extra.corp")
    assert calls == 1
    sources.invalidate()
    assert await sources.origins() == ("https://a.corp", "https://extra.corp")  # kept on failure
