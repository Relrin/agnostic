"""``GET /agnostic/v1/capabilities``: what this AgentOS process runs, read from the AgentOS object itself."""

from __future__ import annotations

import os
import platform
import socket
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, Literal

from agno import __version__ as agno_version
from agno.db.base import BaseDb
from agno.os.auth import get_effective_auth_mode
from agno.workflow import cel as agno_cel
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agno.os import AgentOS
    from fastapi import FastAPI

try:
    __version__ = version("agnostic-bridge")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.1.0"

API_VERSION = "v1"


class BridgeQueueFeatures(BaseModel):
    """``AgentOS(queue=QueueConfig(...))``; all false/None when no queue config was passed."""

    configured: bool = Field(description="A QueueConfig was passed to AgentOS")
    durable: bool = Field(description="Accepted background runs are committed rows that survive restarts")
    redis_configured: bool = Field(
        description="Cross-replica coordination (cancel, stream resume) over Redis; needed with more than one replica"
    )
    max_concurrency: int | None = Field(description="Background runs per replica; None = process default")


class BridgeFeatures(BaseModel):
    """Switches set on the AgentOS object. The control plane still probes the routes before relying on them."""

    auth_mode: Literal["none", "security_key", "jwt"] = Field(description="Same value as /info.auth_mode")
    authorization: bool = Field(description="RBAC on verified JWTs (AgentOS(authorization=...))")
    user_isolation: bool = Field(description="Effective per-user data isolation, as /info reports it")
    tracing: bool
    scheduler: bool
    queue: BridgeQueueFeatures
    db: bool = Field(description="An AgentOS db is configured")
    components: bool = Field(description="The db is synchronous (BaseDb), which /components and Studio need")
    registry: bool
    mcp: bool = Field(description="The OS is served over MCP")
    telemetry: bool
    interfaces: list[str] = Field(description="Interface types mounted on the OS (a2a, slack, ...)")
    cel: bool = Field(description="cel-python is installed, so workflows evaluate CEL (agno[cel])")


class BridgeCapabilities(BaseModel):
    bridge_version: str = Field(description="agnostic-bridge package version")
    api_version: str = Field(description="Bridge route family, the /agnostic/<api_version> prefix")
    agno_version: str
    python_version: str
    os_id: str
    replica_id: str = Field(description="This process; differs per replica behind one URL")
    features: BridgeFeatures
    endpoints: list[str] = Field(description="Bridge routes this version serves, as 'METHOD /path'")


def default_replica_id() -> str:
    """``AGNOSTIC_BRIDGE_REPLICA_ID``, else ``<hostname>:<pid>`` (a pod name under Kubernetes)."""
    return os.environ.get("AGNOSTIC_BRIDGE_REPLICA_ID") or f"{socket.gethostname()}:{os.getpid()}"


def _queue_features(agent_os: AgentOS) -> BridgeQueueFeatures:
    queue = agent_os.queue
    if queue is None:
        return BridgeQueueFeatures(configured=False, durable=False, redis_configured=False, max_concurrency=None)
    return BridgeQueueFeatures(
        configured=True,
        durable=bool(queue.durable),
        redis_configured=queue.redis is not None,
        max_concurrency=queue.max_concurrency,
    )


def _scheduler_enabled(agent_os: AgentOS) -> bool:
    # AgentOS keeps the constructor flag privately; 3.1.x has no public accessor.
    return bool(getattr(agent_os, "_scheduler_enabled", False))


def _interface_types(agent_os: AgentOS) -> list[str]:
    names: list[str] = []
    for interface in agent_os.interfaces or []:
        name = getattr(interface, "type", None) or type(interface).__name__.lower()
        names.append(str(name))
    if getattr(agent_os, "a2a_interface", False) and "a2a" not in names:
        names.append("a2a")
    return sorted(names)


def build_capabilities(
    agent_os: AgentOS, app: FastAPI | Any, replica_id: str, endpoints: list[str]
) -> BridgeCapabilities:
    state = app.state
    return BridgeCapabilities(
        bridge_version=__version__,
        api_version=API_VERSION,
        agno_version=agno_version,
        python_version=platform.python_version(),
        os_id=agent_os.id or "Unnamed OS",
        replica_id=replica_id,
        features=BridgeFeatures(
            auth_mode=get_effective_auth_mode(
                settings=agent_os.settings, authorization=bool(agent_os.authorization), app=app
            ),
            authorization=bool(agent_os.authorization),
            user_isolation=bool(getattr(state, "user_isolation_enabled", False)),
            tracing=bool(agent_os.tracing),
            scheduler=_scheduler_enabled(agent_os),
            queue=_queue_features(agent_os),
            db=agent_os.db is not None,
            components=isinstance(agent_os.db, BaseDb),
            registry=agent_os.registry is not None,
            mcp=bool(agent_os.mcp),
            telemetry=bool(agent_os.telemetry),
            interfaces=_interface_types(agent_os),
            cel=agno_cel.CEL_AVAILABLE,
        ),
        endpoints=endpoints,
    )
