"""The reference AgentOS, assembled from settings.

    uv run python -m app.main               # serves on RUNTIME_HOST:RUNTIME_PORT
    uvicorn app.main:app --port 7777        # same app, any ASGI server

Recipe: sync ``PostgresDb`` (Studio needs it), tracing, scheduler with a shared internal token, durable queue with
Redis coordination, a ``Registry``, user isolation, telemetry off. JWT authorization switches on when
``JWT_VERIFICATION_KEY`` (or ``JWT_JWKS_FILE``) is set; without it the runtime runs in ``auth_mode=none`` for local
development.
"""

from agno.db.postgres import PostgresDb
from agno.os import AgentOS, QueueConfig

from app.agents import AGENTS
from app.registry import build_registry
from app.settings import get_settings
from app.teams import TEAMS
from app.workflows import WORKFLOWS

settings = get_settings()

db = PostgresDb(id=f"{settings.id}-db", db_url=settings.database_url)

agent_os = AgentOS(
    id=settings.id,
    name=settings.name,
    description=settings.description,
    db=db,
    agents=list(AGENTS),
    teams=list(TEAMS),
    workflows=list(WORKFLOWS),
    registry=build_registry(db),
    tracing=True,
    scheduler=True,
    scheduler_base_url=f"http://{settings.host}:{settings.port}",
    internal_service_token=settings.internal_service_token,
    queue=QueueConfig(durable=True, redis=settings.redis_url, max_concurrency=settings.max_concurrency),
    authorization=settings.jwt_enabled,
    user_isolation=settings.user_isolation,
    telemetry=False,
)

app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="app.main:app", host=settings.host, port=settings.port)
