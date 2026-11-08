"""Route policies: which scopes each AgentOS route needs, how long GETs may be cached, how calls are audited.

Seeded from AgentOS 3.1.12 ``agno/os/scopes.py`` (``get_default_scope_mappings``), with ``*`` turned into named
single-segment parameters, plus the routes AgentOS leaves unmapped but checks in its handlers (run polling, resume,
checkpoints, session runs, queue, authz). Unknown routes require ``agent_os:admin``: the gateway fails closed and
logs them, so new AgentOS endpoints get noticed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

ADMIN = "agent_os:admin"
type AuditLevel = Literal["none", "decision", "full"]
type RateBucket = Literal["read", "write", "run"]
_PARAM = re.compile(r"\{(\w+)(\*?)\}")


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    method: str
    pattern: str
    """``/agents/{agent_id}/runs``; ``{name*}`` matches the rest of the path."""
    scopes: tuple[str, ...]
    """All of these are required; ``{param}`` placeholders are filled from the path."""
    cache_ttl_s: int = 0
    audit_level: AuditLevel = "decision"
    rate_bucket: RateBucket = "read"
    list_filter: bool = False
    """AgentOS filters this list by per-component grants instead of refusing it, so per-component scopes pass."""
    source: Literal["default", "override", "fallback"] = "default"

    @property
    def regex(self) -> re.Pattern[str]:
        return _compile(self.pattern)

    @property
    def specificity(self) -> tuple[int, int, int]:
        """More literal characters and fewer parameters win; a catch-all ``{x*}`` loses to anything."""
        literal = len(_PARAM.sub("", self.pattern))
        params = len(_PARAM.findall(self.pattern))
        return ("*}" not in self.pattern, literal, -params)

    def required(self, params: Mapping[str, str]) -> tuple[str, ...]:
        return tuple(scope.format_map(dict(params)) for scope in self.scopes)

    @property
    def family(self) -> str:
        return self.pattern.strip("/").split("/", 1)[0]


@lru_cache(maxsize=2048)
def _compile(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    position = 0
    for match in _PARAM.finditer(pattern):
        parts.append(re.escape(pattern[position : match.start()]))
        parts.append(f"(?P<{match.group(1)}>.+)" if match.group(2) else f"(?P<{match.group(1)}>[^/]+)")
        position = match.end()
    parts.append(re.escape(pattern[position:]))
    return re.compile("^" + "".join(parts) + "$")


def _p(
    method: str,
    pattern: str,
    *scopes: str,
    ttl: int = 0,
    audit: AuditLevel | None = None,
    bucket: RateBucket | None = None,
    list_filter: bool = False,
) -> RoutePolicy:
    write = method not in {"GET", "HEAD", "OPTIONS"}
    return RoutePolicy(
        method=method,
        pattern=pattern,
        scopes=tuple(scopes),
        cache_ttl_s=ttl,
        audit_level=audit or ("full" if write else "decision"),
        rate_bucket=bucket or ("write" if write else "read"),
        list_filter=list_filter,
    )


def _components(family: str, key: str) -> list[RoutePolicy]:
    """Agents, teams and workflows share one route shape (per-component scopes use the path id)."""
    base = f"/{family}/{{{key}}}"
    read, run = f"{family}:{{{key}}}:read", f"{family}:{{{key}}}:run"
    return [
        _p("GET", f"/{family}", f"{family}:read", list_filter=True),
        _p("GET", base, read),
        _p("POST", f"/{family}", f"{family}:write"),
        _p("PATCH", base, f"{family}:{{{key}}}:write"),
        _p("DELETE", base, f"{family}:{{{key}}}:delete"),
        _p("POST", f"{base}/runs", run, bucket="run"),
        _p("GET", f"{base}/runs", read, run),
        _p("GET", f"{base}/runs/{{run_id}}", read, run),
        _p("POST", f"{base}/runs/{{run_id}}/continue", run, bucket="run"),
        _p("POST", f"{base}/runs/{{run_id}}/cancel", run, bucket="run"),
        _p("POST", f"{base}/runs/{{run_id}}/resume", run, audit="decision", bucket="read"),
        _p("GET", f"{base}/runs/{{run_id}}/checkpoints", read, run),
        _p("GET", f"{base}/runs/{{run_id}}/checkpoints/{{message_index}}", read, run),
        _p("POST", f"{base}/sessions/{{session_id}}/fork", run),
        _p("POST", f"{base}/sessions/{{session_id}}/compact", run),
    ]


def _crud(family: str, path: str, key: str, *, collection_delete: bool = True) -> list[RoutePolicy]:
    item = f"{path}/{{{key}}}"
    policies = [
        _p("GET", path, f"{family}:read"),
        _p("POST", path, f"{family}:write"),
        _p("GET", item, f"{family}:read"),
        _p("PATCH", item, f"{family}:write"),
        _p("DELETE", item, f"{family}:delete"),
    ]
    if collection_delete:
        policies.append(_p("DELETE", path, f"{family}:delete"))
    return policies


DEFAULT_POLICIES: tuple[RoutePolicy, ...] = (
    _p("GET", "/health", audit="none"),
    _p("GET", "/info", ttl=30, audit="none"),
    _p("GET", "/config", "config:read", ttl=300),
    _p("GET", "/models", "config:read", ttl=300),
    _p("POST", "/databases/all/migrate", "config:write"),
    _p("POST", "/databases/{db_id}/migrate", "config:write"),
    _p("GET", "/registry", "registry:read", ttl=300),
    _p("GET", "/filesystem/{rest*}", "filesystem:read"),
    *_components("agents", "agent_id"),
    *_components("teams", "team_id"),
    *_components("workflows", "workflow_id"),
    *_crud("sessions", "/sessions", "session_id"),
    _p("POST", "/sessions/search", "sessions:read", audit="decision", bucket="read"),
    _p("GET", "/sessions/filter-schema", "sessions:read", ttl=3600),
    _p("POST", "/sessions/{session_id}/rename", "sessions:write"),
    _p("GET", "/sessions/{session_id}/runs", "sessions:read"),
    _p("GET", "/sessions/{session_id}/runs/{run_id}", "sessions:read"),
    _p("GET", "/sessions/{session_id}/run-previews", "sessions:read"),
    # Storage keys carry folders (``<session>/<media id>.<ext>``), so the key takes the rest of the path.
    _p("GET", "/sessions/{session_id}/media/{storage_key*}", "sessions:read"),
    *_crud("memories", "/memories", "memory_id"),
    _p("GET", "/memory_topics", "memories:read"),
    _p("GET", "/user_memory_stats", "memories:read"),
    _p("POST", "/optimize-memories", "memories:write"),
    *_crud("learnings", "/learnings", "learning_id", collection_delete=False),
    _p("GET", "/learnings/users", "learnings:read"),
    _p("DELETE", "/learnings/users/{user_id}", "learnings:delete"),
    _p("GET", "/knowledge/config", "knowledge:read", ttl=300),
    _p("GET", "/knowledge/content", "knowledge:read"),
    _p("POST", "/knowledge/content", "knowledge:write"),
    _p("DELETE", "/knowledge/content", "knowledge:delete"),
    _p("GET", "/knowledge/content/{content_id}", "knowledge:read"),
    _p("GET", "/knowledge/content/{content_id}/status", "knowledge:read"),
    _p("PATCH", "/knowledge/content/{content_id}", "knowledge:write"),
    _p("DELETE", "/knowledge/content/{content_id}", "knowledge:delete"),
    _p("POST", "/knowledge/content/{content_id}/refresh", "knowledge:write"),
    _p("POST", "/knowledge/remote-content", "knowledge:write"),
    _p("POST", "/knowledge/search", "knowledge:read", audit="decision", bucket="read"),
    _p("GET", "/knowledge/{knowledge_id}/sources", "knowledge:read"),
    _p("GET", "/knowledge/{knowledge_id}/sources/{source_id}/files", "knowledge:read"),
    _p("GET", "/metrics", "metrics:read", ttl=60),
    _p("POST", "/metrics/refresh", "metrics:write"),
    _p("GET", "/metrics/refresh/status", "metrics:read"),
    *_crud("evals", "/eval-runs", "eval_run_id"),
    _p("GET", "/traces", "traces:read"),
    _p("GET", "/traces/filter-schema", "traces:read", ttl=3600),
    _p("GET", "/traces/{trace_id}", "traces:read"),
    _p("POST", "/traces/search", "traces:read", audit="decision", bucket="read"),
    _p("GET", "/trace_session_stats", "traces:read"),
    *_crud("schedules", "/schedules", "schedule_id", collection_delete=False),
    _p("POST", "/schedules/{schedule_id}/enable", "schedules:write"),
    _p("POST", "/schedules/{schedule_id}/disable", "schedules:write"),
    _p("POST", "/schedules/{schedule_id}/trigger", "schedules:write", bucket="run"),
    _p("GET", "/schedules/{schedule_id}/runs", "schedules:read"),
    _p("GET", "/schedules/{schedule_id}/runs/{run_id}", "schedules:read"),
    _p("GET", "/approvals", "approvals:read"),
    _p("GET", "/approvals/count", "approvals:read"),
    _p("GET", "/approvals/{approval_id}", "approvals:read"),
    _p("GET", "/approvals/{approval_id}/status", "approvals:read"),
    _p("POST", "/approvals/{approval_id}/resolve", "approvals:write"),
    _p("DELETE", "/approvals/{approval_id}", "approvals:delete"),
    _p("GET", "/components", "components:read"),
    _p("POST", "/components", "components:write"),
    _p("GET", "/components/{component_id}", "components:read"),
    _p("PATCH", "/components/{component_id}", "components:write"),
    _p("DELETE", "/components/{component_id}", "components:delete"),
    _p("POST", "/components/{component_id}/restore", "components:delete"),
    _p("GET", "/components/{component_id}/configs", "components:read"),
    _p("POST", "/components/{component_id}/configs", "components:write"),
    _p("GET", "/components/{component_id}/configs/current", "components:read"),
    _p("GET", "/components/{component_id}/configs/{version}", "components:read"),
    _p("PATCH", "/components/{component_id}/configs/{version}", "components:write"),
    _p("DELETE", "/components/{component_id}/configs/{version}", "components:delete"),
    _p("POST", "/components/{component_id}/configs/{version}/set-current", "components:write"),
    _p("GET", "/service-accounts", "service_accounts:read"),
    _p("POST", "/service-accounts", "service_accounts:write"),
    _p("DELETE", "/service-accounts/{service_account_id}", "service_accounts:delete"),
    # Admin-only for JWT callers in AgentOS itself.
    _p("GET", "/queue/{rest*}", ADMIN),
    _p("POST", "/queue/jobs/{job_id}/requeue", ADMIN),
    _p("GET", "/authz/{rest*}", ADMIN),
    _p("GET", "/users", ADMIN),
    _p("GET", "/agnostic/v1/capabilities", "config:read", ttl=60),
    # Version-pinned (draft) evals run the component with real model calls: audited in full, rate-limited as runs.
    _p("POST", "/agnostic/v1/evals/run", "evals:write", audit="full", bucket="run"),
    # Which runs wrote and read a file: joined from tool spans, so it needs both families.
    _p("GET", "/agnostic/v1/files/provenance", "filesystem:read", "traces:read"),
    # Studio checks: agno's strict load and canonical form of a config, read-only against the live registry.
    _p("POST", "/agnostic/v1/components/validate", "components:read", audit="decision", bucket="read"),
    _p("POST", "/agnostic/v1/components/normalize", "components:read", audit="decision", bucket="read"),
    _p("GET", "/agnostic/v1/introspect/components", "components:read", ttl=60),
    _p("GET", "/agnostic/v1/registry/{resource_type}/{name}/source", "registry:read", ttl=300),
    # Artefacts: the media a session's runs stored, and collecting them from sandbox checkpoints.
    _p("GET", "/agnostic/v1/artifacts", "sessions:read"),
    _p("GET", "/agnostic/v1/artifacts/recent", "sessions:read"),
    _p("POST", "/agnostic/v1/artifacts/sync", "sessions:write", audit="decision", bucket="read"),
    # Coding agents the bridge built from published components. Its ``/agnostic/v1/coding/*`` routes are sandbox
    # callbacks authenticated by run grants, not people: they stay unmapped so the gateway refuses them.
    _p("GET", "/agnostic/v1/coding-agents", "agents:read", ttl=30),
    _p("POST", "/agnostic/v1/coding-agents/refresh", "config:write", audit="full", bucket="write"),
    # The reasoning effort levels a component's model accepts, for the chat composer's picker.
    _p("GET", "/agnostic/v1/reasoning/{family}/{component_id}", "agents:read", ttl=30),
)

UPLOAD_ROUTES: frozenset[tuple[str, str]] = frozenset({("POST", "/knowledge/content")})
"""Routes whose bodies are file uploads: they get the gateway's upload size limit instead of the body limit."""


def is_upload(method: str, path: str) -> bool:
    return (method.upper(), "/" + path.strip("/")) in UPLOAD_ROUTES


def fallback(method: str, path: str) -> RoutePolicy:
    """Unknown route: fail closed."""
    return RoutePolicy(method=method, pattern=path, scopes=(ADMIN,), audit_level="full", source="fallback")


@dataclass(slots=True)
class PolicyTable:
    policies: Sequence[RoutePolicy]
    _by_method: dict[str, list[RoutePolicy]] = field(default_factory=dict[str, list[RoutePolicy]])

    def __post_init__(self) -> None:
        for policy in sorted(self.policies, key=lambda p: p.specificity, reverse=True):
            self._by_method.setdefault(policy.method, []).append(policy)

    def match(self, method: str, path: str) -> tuple[RoutePolicy, dict[str, str]]:
        lookup = "GET" if method == "HEAD" else method
        for policy in self._by_method.get(lookup, []):
            found = policy.regex.match(path)
            if found:
                return policy, found.groupdict()
        return fallback(method, path), {}


def merged(defaults: Iterable[RoutePolicy], overrides: Iterable[RoutePolicy]) -> list[RoutePolicy]:
    """Overrides replace defaults with the same method and pattern, or add new routes."""
    table = {(p.method, p.pattern): p for p in defaults}
    for override in overrides:
        table[(override.method, override.pattern)] = override
    return list(table.values())


# ---------------------------------------------------------------- header hygiene

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)
REQUEST_DROP = HOP_BY_HOP | {
    "host",
    "cookie",
    "authorization",
    "x-csrf-token",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "forwarded",
    "x-request-id",
    "origin",
    "referer",
}
RESPONSE_DROP = HOP_BY_HOP | {
    "set-cookie",
    "server",
    "date",
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "access-control-allow-headers",
    "access-control-allow-methods",
    "access-control-expose-headers",
}


def request_headers(incoming: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Headers forwarded to AgentOS: everything except credentials, cookies and hop-by-hop headers."""
    return {name: value for name, value in incoming if name.lower() not in REQUEST_DROP}


def response_headers(upstream: Iterable[tuple[str, str]], *, streaming: bool) -> dict[str, str]:
    dropped = RESPONSE_DROP | ({"content-length"} if streaming else frozenset[str]())
    return {name: value for name, value in upstream if name.lower() not in dropped}


MAX_TOKEN_SCOPE_BYTES = 8 * 1024


def scopes_for_token(scopes: Sequence[str], family: str) -> tuple[list[str], bool]:
    """Keep the JWT small: past 8 KB, only the requested route family's scopes go in. Never widens."""
    if sum(len(scope) + 3 for scope in scopes) <= MAX_TOKEN_SCOPE_BYTES:
        return list(scopes), False
    relevant = [scope for scope in scopes if scope == ADMIN or scope.split(":", 1)[0] == family]
    return relevant, True
