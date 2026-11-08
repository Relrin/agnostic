"""The reference AgentOS, assembled from settings.

    uv run python -m app.main               # serves on RUNTIME_HOST:RUNTIME_PORT
    uvicorn app.main:app --port 7777        # same app, any ASGI server

Recipe: sync ``PostgresDb`` (Studio needs it), tracing, scheduler with a shared internal token, durable queue with
Redis coordination, a ``Registry``, telemetry off, local media storage (run media and artefacts, ``RUNTIME_MEDIA_DIR``)
and ``agnostic-bridge`` installed (``/agnostic/v1/*``).

JWT authorization switches on when ``JWT_VERIFICATION_KEY`` (or ``JWT_JWKS_FILE``) is set: tokens must be RS256, carry
``aud`` = this runtime's id (the ``os_id`` the control plane mints for) and, if ``RUNTIME_JWT_ISSUER`` is set, that
``iss``. Without a key the runtime runs in ``auth_mode=none`` for local development. User isolation is on for the
prod runtime (``dev-prod``) and follows ``RUNTIME_USER_ISOLATION`` elsewhere.
"""

from agno.db.postgres import PostgresDb
from agno.os import AgentOS, QueueConfig
from agno.os.authz import Authorization
from agnostic_bridge import direct_mode_cors, install

from app.agents import AGENTS
from app.agents.report_writer import report_writer
from app.agents.sandbox_analyst import build_sandbox_analyst
from app.media import media_storage
from app.registry import build_registry
from app.settings import RuntimeSettings, get_settings
from app.teams import TEAMS
from app.workflows import WORKFLOWS


def build_authorization(settings: RuntimeSettings) -> Authorization | bool:
    if not settings.jwt_enabled:
        return False
    # Keys come from JWT_VERIFICATION_KEY / JWT_JWKS_FILE (agno reads them); verify-only, no role store.
    return Authorization(
        algorithm="RS256",
        verify_audience=True,
        audience=settings.id,
        issuer=settings.jwt_issuer or None,
        audit=settings.authz_audit,
    )


def artifact_agents() -> list:
    """Agents whose files become artefacts; kept apart from AGENTS, the golden-file set."""
    sandbox_analyst = build_sandbox_analyst()
    return [report_writer, *([sandbox_analyst] if sandbox_analyst is not None else [])]


def build_agent_os(settings: RuntimeSettings) -> AgentOS:
    db = PostgresDb(id=f"{settings.id}-db", db_url=settings.database_url)
    return AgentOS(
        id=settings.id,
        name=settings.name,
        description=settings.description,
        db=db,
        agents=[*AGENTS, *artifact_agents()],
        teams=list(TEAMS),
        workflows=list(WORKFLOWS),
        registry=build_registry(db),
        tracing=True,
        scheduler=True,
        scheduler_base_url=f"http://{settings.host}:{settings.port}",
        internal_service_token=settings.internal_service_token,
        queue=QueueConfig(durable=True, redis=settings.redis_url, max_concurrency=settings.max_concurrency),
        authorization=build_authorization(settings),
        user_isolation=settings.user_isolation_enabled,
        telemetry=False,
        media_storage=media_storage(),
        cors=direct_mode_cors(settings.cors_origin_list) if settings.cors_origin_list else None,
    )


settings = get_settings()
agent_os = build_agent_os(settings)
app = install(agent_os)  # agent_os.get_app() plus the bridge routes


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", host=settings.host, port=settings.port)
