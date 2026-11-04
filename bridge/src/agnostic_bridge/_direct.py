"""Direct mode: let browsers on the control plane's origin call this AgentOS themselves.

The control plane mints the same short-lived, scoped JWTs it uses for the gateway and hands them to the browser,
which then calls AgentOS directly. That needs CORS for the control plane's origin (and TLS on AgentOS)::

    from agnostic_bridge import direct_mode_cors

    agent_os = AgentOS(..., authorization=Authorization(..., audit=True), cors=direct_mode_cors(["https://agnostic.corp"]))

``Authorization(audit=True)`` keeps a decision log the control plane ingests, since it no longer sees each call.
"""

from collections.abc import Iterable
from urllib.parse import urlsplit

from agno.os.config import CORSConfig


def direct_mode_cors(origins: Iterable[str]) -> CORSConfig:
    """CORS for the control plane's public origin(s), keeping whatever the base app already allows."""
    cleaned: list[str] = []
    for origin in origins:
        parts = urlsplit(origin.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
            msg = f"{origin!r} isn't an origin like https://agnostic.example.com"
            raise ValueError(msg)
        cleaned.append(f"{parts.scheme}://{parts.netloc}")
    return CORSConfig(origins=cleaned, merge_base_app=True)
