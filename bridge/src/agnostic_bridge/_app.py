"""Mount the bridge routes on an AgentOS app.

Where the routes go, and why:

- **Ahead of the MCP catch-all.** With ``mcp=True`` AgentOS mounts its MCP app at ``/`` as the last thing in
  ``get_app()``; a route registered after that mount is never reached. ``install`` puts the bridge routes in front
  of the first mount, which is where AgentOS registers its own late routers (``/authz``, ``/users``).
- **Behind AgentOS auth, with explicit scopes.** AgentOS's auth middleware reads its route → scopes table from
  ``app.state.scope_mappings``, the dict ``get_app()`` builds from ``agno.os.scopes``. Unmapped routes need only a
  valid token, so ``install`` adds :data:`SCOPE_MAPPINGS` to that same dict (in place, so a middleware that already
  holds it sees the entries). Admin tokens (``agent_os:admin``) pass as for any built-in route; service-account
  tokens (``agno_pat_…``) are checked against the same table.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from starlette.routing import BaseRoute, Mount

from agnostic_bridge._artifacts import (
    ARTIFACTS_PATH,
    RECENT_ARTIFACTS_PATH,
    SYNC_ARTIFACTS_PATH,
    add_artifact_routes,
)
from agnostic_bridge._capabilities import BridgeCapabilities, build_capabilities, default_replica_id
from agnostic_bridge._catalog import (
    PROBE_PATH,
    STATUS_PATH,
    SYNC_PATH,
    TOOLKITS_PATH,
    CatalogHolder,
    ToolCatalogConfig,
    add_catalog_routes,
)
from agnostic_bridge._cel import EVALUATE_CEL_PATH, add_cel_routes
from agnostic_bridge._components import NORMALIZE_PATH, VALIDATE_PATH, add_component_routes
from agnostic_bridge._evals import RUN_EVAL_PATH, add_eval_routes
from agnostic_bridge._events import EVENTS_PATH, add_event_routes
from agnostic_bridge._files import PROVENANCE_PATH, add_file_routes
from agnostic_bridge._introspect import INTROSPECT_COMPONENTS_PATH, REGISTRY_SOURCE_PATH, add_introspect_routes
from agnostic_bridge._reasoning import REASONING_PATH, add_reasoning_hooks, add_reasoning_routes
from agnostic_bridge._workers import WORKERS_PATH, add_worker_routes
from agnostic_bridge.coding._callback import CallbackMiddleware
from agnostic_bridge.coding._materialize import CodingAgentSync
from agnostic_bridge.coding._routes import CODING_AGENTS_PATH, REFRESH_CODING_AGENTS_PATH, add_coding_routes
from agnostic_bridge.coding._runtime import CodingConfig, CodingRuntime, configure_coding

if TYPE_CHECKING:
    from agno.os import AgentOS
    from fastapi import FastAPI

BRIDGE_PREFIX = "/agnostic/v1"
CAPABILITIES_PATH = f"{BRIDGE_PREFIX}/capabilities"

# "METHOD /path" → scopes, in agno's scope_mappings format (agno.os.scopes.get_default_scope_mappings).
SCOPE_MAPPINGS: dict[str, list[str]] = {
    f"GET {CAPABILITIES_PATH}": ["config:read"],
    f"POST {BRIDGE_PREFIX}{RUN_EVAL_PATH}": ["evals:write"],
    f"GET {BRIDGE_PREFIX}{PROVENANCE_PATH}": ["filesystem:read", "traces:read"],
    # Admin, as AgentOS gates its /queue operator routes: worker and queue internals are a cross-tenant surface.
    f"GET {BRIDGE_PREFIX}{WORKERS_PATH}": ["agent_os:admin"],
    f"GET {BRIDGE_PREFIX}{EVENTS_PATH}": ["approvals:read", "schedules:read"],
    f"POST {BRIDGE_PREFIX}{VALIDATE_PATH}": ["components:read"],
    f"POST {BRIDGE_PREFIX}{NORMALIZE_PATH}": ["components:read"],
    f"GET {BRIDGE_PREFIX}{INTROSPECT_COMPONENTS_PATH}": ["components:read"],
    f"GET {BRIDGE_PREFIX}{REGISTRY_SOURCE_PATH}": ["registry:read"],
    f"POST {BRIDGE_PREFIX}{EVALUATE_CEL_PATH}": ["components:read"],
    f"GET {BRIDGE_PREFIX}{STATUS_PATH}": ["registry:read"],
    f"POST {BRIDGE_PREFIX}{SYNC_PATH}": ["config:write"],
    # Admin: probing connects to a server from this runtime with the runtime's credentials.
    f"POST {BRIDGE_PREFIX}{PROBE_PATH}": ["agent_os:admin"],
    f"GET {BRIDGE_PREFIX}{TOOLKITS_PATH}": ["registry:read"],
    f"GET {BRIDGE_PREFIX}{ARTIFACTS_PATH}": ["sessions:read"],
    f"GET {BRIDGE_PREFIX}{RECENT_ARTIFACTS_PATH}": ["sessions:read"],
    f"POST {BRIDGE_PREFIX}{SYNC_ARTIFACTS_PATH}": ["sessions:write"],
    f"GET {BRIDGE_PREFIX}{CODING_AGENTS_PATH}": ["agents:read"],
    f"POST {BRIDGE_PREFIX}{REFRESH_CODING_AGENTS_PATH}": ["config:write"],
    f"GET {BRIDGE_PREFIX}{REASONING_PATH}": ["agents:read"],
}


def create_router(
    agent_os: AgentOS,
    *,
    replica_id: str | None = None,
    include_in_schema: bool = True,
    catalog: CatalogHolder | None = None,
    coding_sync: CodingAgentSync | None = None,
) -> APIRouter:
    """The bridge routes as a router. :func:`install` is the usual entry point; use this to include the routes
    yourself (then also merge :data:`SCOPE_MAPPINGS` into ``app.state.scope_mappings`` after ``get_app()``, and
    run ``catalog.lifespan()`` inside the app's lifespan when the tool catalog is on)."""
    replica = replica_id or default_replica_id()
    holder = catalog or CatalogHolder(agent_os, None, replica)
    endpoints = sorted(SCOPE_MAPPINGS)
    router = APIRouter(prefix=BRIDGE_PREFIX, tags=["Agnostic bridge"], include_in_schema=include_in_schema)

    @router.get(
        "/capabilities",
        operation_id="agnostic_bridge_get_capabilities",
        summary="Get bridge capabilities",
        description="Bridge, agno and Python versions, and the features this AgentOS process runs. Needs config:read.",
        response_model=BridgeCapabilities,
    )
    async def get_capabilities(request: Request) -> BridgeCapabilities:
        return build_capabilities(agent_os, request.app, replica, endpoints, catalog=holder, coding_sync=coding_sync)

    add_eval_routes(router, agent_os)
    add_file_routes(router, agent_os)
    add_artifact_routes(router, agent_os)
    add_worker_routes(router, agent_os, replica)
    add_event_routes(router, agent_os)
    add_component_routes(router, agent_os)
    add_introspect_routes(router, agent_os)
    add_cel_routes(router, agent_os)
    add_catalog_routes(router, holder)
    add_coding_routes(router, agent_os, coding_sync)
    add_reasoning_routes(router, agent_os)
    return router


def install(
    agent_os: AgentOS,
    *,
    replica_id: str | None = None,
    include_in_schema: bool = True,
    tool_catalog: ToolCatalogConfig | None = None,
    coding: CodingConfig | None = None,
) -> FastAPI:
    """Build the AgentOS app (``agent_os.get_app()``), add the bridge routes and their scopes, and return the app.

    Serve the returned app; don't call ``get_app()`` again afterwards (without a ``base_app`` that builds a new app
    without the bridge). Works with or without ``base_app``, ``mcp=True`` and any auth mode.

    Args:
        agent_os: the configured AgentOS.
        replica_id: identifies this process in ``/capabilities`` and ``/workers``; defaults to
            ``AGNOSTIC_BRIDGE_REPLICA_ID`` or ``<hostname>:<pid>``.
        include_in_schema: list the bridge routes in the app's OpenAPI document.
        tool_catalog: pull the control plane's tool catalog and register its entries; defaults to
            :meth:`ToolCatalogConfig.from_env` (off unless ``AGNOSTIC_CONTROL_PLANE_URL``,
            ``AGNOSTIC_INSTANCE_ID`` and ``AGNOSTIC_TOOL_CATALOG_TOKEN`` are set).
        coding: coding agents (Pi, OpenCode in sandboxes): where sandboxes call back on and whether Studio agents
            marked as coding agents are served; defaults to :meth:`CodingConfig.from_env`. The callback routes
            answer only the run tokens this process mints, ahead of the AgentOS auth layer.

    It also gives the code-defined agents and teams the pre-hook that applies a run's ``reasoning_effort`` to their
    model (see :mod:`agnostic_bridge.reasoning`).
    """
    app = agent_os.get_app()
    add_reasoning_hooks(agent_os)
    replica = replica_id or default_replica_id()
    holder = CatalogHolder(agent_os, tool_catalog or ToolCatalogConfig.from_env(), replica)
    coding_runtime = configure_coding(coding or CodingConfig.from_env())
    coding_sync = (
        CodingAgentSync(agent_os, interval=coding_runtime.config.sync_interval)
        if coding_runtime.config.materialize and agent_os.db is not None
        else None
    )
    router = create_router(
        agent_os, replica_id=replica, include_in_schema=include_in_schema, catalog=holder, coding_sync=coding_sync
    )

    existing = {id(route) for route in app.router.routes}
    app.include_router(router)
    added = [route for route in app.router.routes if id(route) not in existing]
    _move_ahead_of_mounts(app.router.routes, added)

    mappings = getattr(app.state, "scope_mappings", None)
    if isinstance(mappings, dict):
        mappings.update(SCOPE_MAPPINGS)
    else:  # get_app() always sets it in 3.1.x; keep the table discoverable if a later agno stops doing so
        app.state.scope_mappings = dict(SCOPE_MAPPINGS)

    # Outermost, so sandbox callbacks are answered before AgentOS's own auth sees them.
    app.add_middleware(CallbackMiddleware, grants=coding_runtime.grants)
    _wrap_lifespan(app, holder, coding_runtime, coding_sync)
    app.openapi_schema = None  # drop a cached document so /openapi.json lists the new routes
    return app


def _wrap_lifespan(
    app: FastAPI, holder: CatalogHolder, coding: CodingRuntime, coding_sync: CodingAgentSync | None
) -> None:
    """Run the tool catalog puller, the coding sandbox reaper and the Studio coding agent sync inside the app's
    lifespan, after AgentOS's own (MCP connects, db)."""
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_: Any) -> AsyncIterator[Any]:
        async with inner(app_) as state, AsyncExitStack() as stack:
            if holder.config is not None:
                await stack.enter_async_context(holder.lifespan())
            await coding.start()
            stack.push_async_callback(coding.stop)
            if coding_sync is not None:
                await stack.enter_async_context(coding_sync.lifespan())
            yield state

    app.router.lifespan_context = lifespan


def _move_ahead_of_mounts(routes: list[BaseRoute], added: list[BaseRoute]) -> None:
    for route in added:
        routes.remove(route)
    first_mount = next((index for index, route in enumerate(routes) if isinstance(route, Mount)), len(routes))
    routes[first_mount:first_mount] = added
