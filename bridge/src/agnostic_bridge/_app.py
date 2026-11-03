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

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from starlette.routing import BaseRoute, Mount

from agnostic_bridge._capabilities import BridgeCapabilities, build_capabilities, default_replica_id
from agnostic_bridge._evals import RUN_EVAL_PATH, add_eval_routes
from agnostic_bridge._events import EVENTS_PATH, add_event_routes
from agnostic_bridge._files import PROVENANCE_PATH, add_file_routes
from agnostic_bridge._workers import WORKERS_PATH, add_worker_routes

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
}


def create_router(agent_os: AgentOS, *, replica_id: str | None = None, include_in_schema: bool = True) -> APIRouter:
    """The bridge routes as a router. :func:`install` is the usual entry point; use this to include the routes
    yourself (then also merge :data:`SCOPE_MAPPINGS` into ``app.state.scope_mappings`` after ``get_app()``)."""
    replica = replica_id or default_replica_id()
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
        return build_capabilities(agent_os, request.app, replica, endpoints)

    add_eval_routes(router, agent_os)
    add_file_routes(router, agent_os)
    add_worker_routes(router, agent_os, replica)
    add_event_routes(router, agent_os)
    return router


def install(agent_os: AgentOS, *, replica_id: str | None = None, include_in_schema: bool = True) -> FastAPI:
    """Build the AgentOS app (``agent_os.get_app()``), add the bridge routes and their scopes, and return the app.

    Serve the returned app; don't call ``get_app()`` again afterwards (without a ``base_app`` that builds a new app
    without the bridge). Works with or without ``base_app``, ``mcp=True`` and any auth mode.

    Args:
        agent_os: the configured AgentOS.
        replica_id: identifies this process in ``/capabilities`` and ``/workers``; defaults to
            ``AGNOSTIC_BRIDGE_REPLICA_ID`` or ``<hostname>:<pid>``.
        include_in_schema: list the bridge routes in the app's OpenAPI document.
    """
    app = agent_os.get_app()
    router = create_router(agent_os, replica_id=replica_id, include_in_schema=include_in_schema)

    existing = {id(route) for route in app.router.routes}
    app.include_router(router)
    added = [route for route in app.router.routes if id(route) not in existing]
    _move_ahead_of_mounts(app.router.routes, added)

    mappings = getattr(app.state, "scope_mappings", None)
    if isinstance(mappings, dict):
        mappings.update(SCOPE_MAPPINGS)
    else:  # get_app() always sets it in 3.1.x; keep the table discoverable if a later agno stops doing so
        app.state.scope_mappings = dict(SCOPE_MAPPINGS)

    app.openapi_schema = None  # drop a cached document so /openapi.json lists the new routes
    return app


def _move_ahead_of_mounts(routes: list[BaseRoute], added: list[BaseRoute]) -> None:
    for route in added:
        routes.remove(route)
    first_mount = next((index for index, route in enumerate(routes) if isinstance(route, Mount)), len(routes))
    routes[first_mount:first_mount] = added
