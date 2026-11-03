"""A small in-process AgentOS 3.1 stand-in: verifies control-plane JWTs and enforces scopes the way agno does.

Only the routes the tests need: health/info/config, sessions, an SSE run, approvals (list, get, resolve, count),
run continuation, metrics, traces (list, detail), schedules, components with their configs (guards, publish,
set-current, links), the registry, eval runs, and the bridge's
capabilities and version-pinned eval routes (when ``bridge`` is on), and the context routes (memories, optimize,
session runs, knowledge content and config, learnings, agents and teams, and the bridge's file provenance when
``bridge_files`` is on), schedule CRUD with enable/disable/trigger, the durable queue (``queue_enabled``; admin
only, like agno), run checkpoints and cancel, the bridge's workers and events feed, workflows (listing and
streamed draft runs) and the bridge's CEL route (``bridge_cel``). Approvals answer 503 unless ``approvals_enabled``.
Under ``user_isolation`` non-admins get 404 for other people's approvals, runs and traces, like agno.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import string
import time
from collections.abc import AsyncIterator
from typing import Any, cast
from urllib.parse import parse_qs

import jwt
import orjson
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from agnostic_cel import CelError
from agnostic_cel import activation as cel_activation
from agnostic_cel import evaluate as evaluate_cel

ADMIN = "agent_os:admin"
PAT_PREFIX = "agno_pat_"
RESERVED_SUBJECT_PREFIX = "sa:"
_BASE62 = string.ascii_letters + string.digits
_SA_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


# Container events, as agno names them: (started, completed).
_CONTAINER_EVENTS = {
    "Steps": ("StepsExecutionStarted", "StepsExecutionCompleted"),
    "Parallel": ("ParallelExecutionStarted", "ParallelExecutionCompleted"),
    "Condition": ("ConditionExecutionStarted", "ConditionExecutionCompleted"),
    "Loop": ("LoopExecutionStarted", "LoopExecutionCompleted"),
    "Router": ("RouterExecutionStarted", "RouterExecutionCompleted"),
}


def workflow_events(workflow_id: str, steps: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """The events of a run that takes every step once: a Router its first choice, a Condition its ``steps``."""
    found: list[tuple[str, dict[str, Any]]] = [("WorkflowStarted", {"workflow_name": workflow_id})]

    def walk(nodes: list[dict[str, Any]]) -> None:
        for index, node in enumerate(nodes):
            node_type = str(node.get("type") or "Step")
            name = str(node.get("name") or f"step_{index + 1}")
            if node_type == "Step":
                found.append(("StepStarted", {"step_name": name, "step_index": index}))
                found.append(("StepCompleted", {"step_name": name, "step_index": index, "content": f"done: {name}"}))
                continue
            started, completed = _CONTAINER_EVENTS[node_type]
            found.append((started, {"step_name": name, "step_index": index}))
            if node_type == "Router":
                choices = cast("list[dict[str, Any]]", node.get("choices") or [])
                walk(choices[:1])
            elif node_type == "Loop":
                found.append(("LoopIterationStarted", {"step_name": name, "iteration": 1}))
                walk(cast("list[dict[str, Any]]", node.get("steps") or []))
                found.append(("LoopIterationCompleted", {"step_name": name, "iteration": 1}))
            else:
                walk(cast("list[dict[str, Any]]", node.get("steps") or []))
            found.append((completed, {"step_name": name, "step_index": index}))

    walk(steps)
    found.append(("WorkflowCompleted", {"content": "done"}))
    return found


def _privileged(scope: str) -> bool:
    parts = scope.split(":")
    return scope == ADMIN or parts[0] == "service_accounts" or parts[-1] in {"write", "delete"}


def _holds(scopes: list[str], required: str, resource_id: str | None = None) -> bool:
    if ADMIN in scopes or required in scopes:
        return True
    resource, action = required.split(":")
    return resource_id is not None and f"{resource}:{resource_id}:{action}" in scopes


class FakeAgentOS:
    authz_decisions: list[dict[str, Any]] | None = None
    """Rows of ``GET /authz/decisions`` like agno's ``DbAuditSink.read_decisions`` (``None``: no authz store)."""
    authz_changes: list[dict[str, Any]] | None = None
    """Rows of ``GET /authz/audit`` (``None``: change audit off, 404 like agno)."""

    def __init__(  # noqa: PLR0915
        self,
        *,
        os_id: str = "fake-prod",
        name: str = "Fake prod",
        agno_version: str = "3.1.12",
        auth_mode: str = "jwt",
        user_isolation: bool = True,
    ) -> None:
        self.os_id = os_id
        self.name = name
        self.agno_version = agno_version
        self.auth_mode = auth_mode
        self.user_isolation = user_isolation
        self.public_keys: list[str] = []
        self.audience: str | None = os_id
        self.enforce_scopes = True
        self.calls: list[dict[str, Any]] = []
        self.approvals_enabled = False
        self.approvals: dict[str, dict[str, Any]] = {}
        self.resolutions: list[dict[str, Any]] = []
        self.continuations: list[dict[str, Any]] = []
        self.continue_conflicts = 0
        self.metrics_rows: list[dict[str, Any]] = []
        self.traces: list[dict[str, Any]] = []
        self.schedules: list[dict[str, Any]] = []
        self.schedule_runs: dict[str, list[dict[str, Any]]] = {}
        self.trace_details: dict[str, dict[str, Any]] = {}
        self.session_items: list[dict[str, Any]] | None = None
        self.component_stages: dict[tuple[str, int], str] = {}
        """Stages of configs the tests only refer to (stored components below answer first)."""
        self.components: dict[str, dict[str, Any]] = {}
        self.configs: dict[str, dict[int, dict[str, Any]]] = {}
        self.config_patches: list[dict[str, Any]] = []
        self.registry_items: list[dict[str, Any]] = []
        self.registry_sources: dict[tuple[str, str], dict[str, Any]] = {}
        self.code_components: list[dict[str, Any]] = []
        self.bridge_studio = False
        """The bridge also serves Studio's validate, normalize, introspect and source routes."""
        self.bridge_validations: list[dict[str, Any]] = []
        self.bridge_cel = False
        """The bridge serves ``POST /agnostic/v1/cel/evaluate`` (answered with agnostic-cel, standing in for agno)."""
        self.bridge_cel_installed = True
        """``False``: the CEL route answers 503, as without cel-python."""
        self.cel_requests: list[dict[str, Any]] = []
        self.workflow_items: list[dict[str, Any]] = []
        """``GET /workflows``: code-defined workflows."""
        self._clock = 0
        self.eval_runs: list[dict[str, Any]] = []
        self.eval_requests: list[dict[str, Any]] = []
        self.eval_responder: Any = None
        """``(body, path) -> EvalSchema dict`` (or a ``(status, body)`` tuple to fail)."""
        self.bridge = False
        self.bridge_files = False
        self.file_events: list[dict[str, Any]] = []
        self.memories: list[dict[str, Any]] = []
        self.optimized: list[dict[str, Any]] = []
        self.session_runs: dict[str, list[dict[str, Any]]] = {}
        self.knowledge_instances: list[dict[str, Any]] = []
        self.knowledge_content: dict[str, list[dict[str, Any]]] = {}
        self.agent_items: list[dict[str, Any]] = []
        self.learnings: list[dict[str, Any]] = []
        self.queue_enabled = False
        self.queue_jobs: dict[str, dict[str, Any]] = {}
        self.requeued: list[dict[str, Any]] = []
        self.cancelled: list[dict[str, Any]] = []
        self.checkpoints: dict[str, list[dict[str, Any]]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.bridge_workers: dict[str, Any] | None = None
        self.bridge_events: list[dict[str, Any]] = []
        self.service_accounts: dict[str, dict[str, Any]] = {}
        """``agno_service_accounts`` rows by id (with the token's ``token_hash``)."""
        self.run_requests: list[dict[str, Any]] = []
        """Agent runs: ``{agent_id, user_id (as attributed), form, sub}``."""
        self.app = self._build()

    def _claims(self, request: Request) -> dict[str, Any] | Response:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return JSONResponse({"detail": "Authorization header missing"}, status_code=401)
        token = header.removeprefix("Bearer ")
        if token.startswith(PAT_PREFIX):
            return self._pat_claims(token)
        for key in self.public_keys:
            try:
                claims: dict[str, Any] = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256"],
                    audience=self.audience,
                    options={"verify_aud": self.audience is not None},
                )
            except jwt.InvalidAudienceError:
                return JSONResponse({"detail": "Invalid audience"}, status_code=401)
            except jwt.PyJWTError:
                continue
            if str(claims.get("sub", "")).startswith(RESERVED_SUBJECT_PREFIX):
                return JSONResponse({"detail": "Reserved subject prefix 'sa:'"}, status_code=401)
            return claims
        return JSONResponse({"detail": "Invalid token"}, status_code=401)

    async def _guard(
        self, request: Request, required: str, resource_id: str | None = None
    ) -> dict[str, Any] | Response:
        claims = self._claims(request)
        if isinstance(claims, Response):
            return claims
        self.calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "claims": claims,
                "headers": dict(request.headers),
            }
        )
        if self.enforce_scopes and not _holds(list(claims.get("scopes", [])), required, resource_id):
            return JSONResponse({"detail": f"Insufficient permissions. Required: {required}"}, status_code=403)
        return claims

    def _build(self) -> FastAPI:  # noqa: C901, PLR0915
        app = FastAPI()
        self._service_account_routes(app)
        self._authz_routes(app)
        self._component_routes(app)

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "ok", "instantiated_at": "2026-11-01T00:00:00Z"}

        @app.get("/info")
        async def info() -> dict[str, Any]:
            return {
                "os_id": self.os_id,
                "name": self.name,
                "os_version": "3.1.12",
                "agno_version": self.agno_version,
                "agent_count": 2,
                "team_count": 1,
                "workflow_count": 1,
                "auth_mode": self.auth_mode,
                "user_isolation": self.user_isolation,
                "mcp": {"enabled": False},
            }

        @app.get("/config")
        async def config(request: Request) -> Any:
            guarded = await self._guard(request, "config:read")
            if isinstance(guarded, Response):
                return guarded
            return {
                "os_id": self.os_id,
                "name": self.name,
                "description": "Fake runtime",
                "available_models": [{"id": "mock-1", "provider": "mock"}],
                "os_database": "prod-db",
                "databases": ["prod-db"],
                "interfaces": [{"type": "slack", "version": "1", "route": "/slack"}],
                "traces": {"enabled": True},
                "queue": {"durable": True, "queue_per_session": False},
                "memory": {"dbs": []},
                "knowledge": {"dbs": [], "knowledge_instances": self.knowledge_instances},
                "agents": [{"id": "support-triage", "name": "Support triage"}, {"id": "billing-agent"}],
                "teams": [],
                "workflows": [],
            }

        @app.get("/sessions")
        async def sessions(request: Request) -> Any:
            guarded = await self._guard(request, "sessions:read")
            if isinstance(guarded, Response):
                return guarded
            if self.session_items is not None:
                items = [i for i in self.session_items if visible(guarded, i.get("user_id"))]
                items.sort(key=lambda i: str(i.get(request.query_params.get("sort_by", "created_at")) or ""))
                if request.query_params.get("sort_order", "desc") == "desc":
                    items.reverse()
                return page(items, request)
            return {
                "data": [{"session_id": "ses_1", "user_id": guarded["sub"]}],
                "meta": {"page": 1, "limit": 20, "total_pages": 1, "total_count": 1},
            }

        @app.delete("/sessions/{session_id}")
        async def delete_session(session_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "sessions:delete")
            if isinstance(guarded, Response):
                return guarded
            return Response(status_code=204, headers={"X-Deleted": session_id})

        @app.post("/sessions")
        async def create_session(request: Request) -> Any:
            guarded = await self._guard(request, "sessions:write")
            if isinstance(guarded, Response):
                return guarded
            body = await request.body()
            return JSONResponse({"received_bytes": len(body)}, status_code=201)

        @app.post("/agents/{agent_id}/runs")
        async def run(agent_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "agents:run", agent_id)
            if isinstance(guarded, Response):
                return guarded
            form = parse_qs((await request.body()).decode())
            message = form.get("message", [""])[0]
            version = form.get("version", [None])[0]
            pinned = self.configs.get(agent_id, {}).get(int(version)) if version else None
            owner = self.components.get(agent_id, {}).get("user_id")
            if (
                pinned is not None
                and pinned["stage"] == "draft"
                and ADMIN not in guarded.get("scopes", [])
                and guarded.get("sub") != owner
            ):
                # Drafts run only for their owner or an admin, like agno.
                return JSONResponse({"detail": f"Agent {agent_id} not found"}, status_code=404)
            self.run_requests.append(
                {
                    "agent_id": agent_id,
                    "user_id": self._run_user(guarded, form.get("user_id", [None])[0]),
                    "form": {key: values[0] for key, values in form.items()},
                    "query": dict(request.query_params),
                    "sub": guarded.get("sub"),
                }
            )

            async def events() -> AsyncIterator[bytes]:
                for index, name in enumerate(("RunStarted", "RunContent", "RunCompleted")):
                    payload = {"event": name, "event_index": index, "content": message if index == 1 else None}
                    yield b"event: " + name.encode() + b"\ndata: " + orjson.dumps(payload) + b"\n\n"
                    await asyncio.sleep(0.05)

            return StreamingResponse(events(), media_type="text/event-stream")

        disabled = {"detail": "Approvals are not enabled: pass db= to AgentOS"}

        def page(items: list[dict[str, Any]], request: Request) -> dict[str, Any]:
            limit = int(request.query_params.get("limit", "20"))
            number = int(request.query_params.get("page", "1"))
            chunk = items[(number - 1) * limit : number * limit]
            return {"data": chunk, "meta": {"page": number, "limit": limit, "total_count": len(items)}}

        def visible(claims: dict[str, Any], owner: object) -> bool:
            return not self.user_isolation or ADMIN in claims.get("scopes", []) or owner == claims.get("sub")

        @app.get("/approvals/count")
        async def approvals_count(request: Request) -> Response:
            guarded = await self._guard(request, "approvals:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.approvals_enabled:
                return JSONResponse(disabled, status_code=503)
            pending = [
                a for a in self.approvals.values() if a["status"] == "pending" and visible(guarded, a["user_id"])
            ]
            return JSONResponse({"count": len(pending)})

        @app.get("/approvals")
        async def approvals_list(request: Request) -> Response:
            guarded = await self._guard(request, "approvals:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.approvals_enabled:
                return JSONResponse(disabled, status_code=503)
            status = request.query_params.get("status")
            items = [
                a
                for a in self.approvals.values()
                if (status is None or a["status"] == status) and visible(guarded, a["user_id"])
            ]
            return JSONResponse(page(items, request))

        @app.get("/approvals/{approval_id}")
        async def approval(approval_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "approvals:read")
            if isinstance(guarded, Response):
                return guarded
            item = self.approvals.get(approval_id)
            if item is None or not visible(guarded, item["user_id"]):
                return JSONResponse({"detail": "Approval not found"}, status_code=404)
            return JSONResponse(item)

        @app.post("/approvals/{approval_id}/resolve")
        async def resolve(approval_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "approvals:write")
            if isinstance(guarded, Response):
                return guarded
            item = self.approvals.get(approval_id)
            if item is None or not visible(guarded, item["user_id"]):
                return JSONResponse({"detail": "Approval not found"}, status_code=404)
            if item["status"] != "pending":
                return JSONResponse({"detail": f"Approval is already {item['status']}"}, status_code=409)
            body = orjson.loads(await request.body())
            item.update(
                status=body["status"], resolved_by=body.get("resolved_by"), resolution_data=body.get("resolution_data")
            )
            self.resolutions.append({"approval_id": approval_id, "body": body, "claims": guarded})
            return JSONResponse(item)

        @app.post("/agents/{agent_id}/runs/{run_id}/continue")
        async def continue_run(agent_id: str, run_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "agents:run", agent_id)
            if isinstance(guarded, Response):
                return guarded
            form = {key: values[0] for key, values in parse_qs((await request.body()).decode()).items()}
            owner = next((a["user_id"] for a in self.approvals.values() if a["run_id"] == run_id), None)
            if not visible(guarded, owner):
                return JSONResponse({"detail": "Run not found"}, status_code=404)
            if self.continue_conflicts > 0:
                self.continue_conflicts -= 1
                return JSONResponse({"detail": "A durable ticket owns this continuation"}, status_code=409)
            self.continuations.append({"agent_id": agent_id, "run_id": run_id, "form": form, "claims": guarded})
            return JSONResponse(
                {"run_id": run_id, "session_id": form.get("session_id"), "status": "PENDING"}, status_code=202
            )

        @app.get("/metrics")
        async def metrics(request: Request) -> Response:
            guarded = await self._guard(request, "metrics:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse({"metrics": self.metrics_rows, "updated_at": "2026-11-01T00:00:00Z"})

        @app.get("/traces")
        async def traces(request: Request) -> Response:
            guarded = await self._guard(request, "traces:read")
            if isinstance(guarded, Response):
                return guarded
            query = request.query_params
            status = query.get("status")
            items = [t for t in self.traces if status is None or t["status"] == status]
            for key in ("agent_id", "team_id", "workflow_id", "run_id", "session_id"):
                if query.get(key):
                    items = [t for t in items if t.get(key) == query[key]]
            if query.get("end_time"):
                items = [t for t in items if str(t.get("start_time") or "") <= query["end_time"]]
            items = [t for t in items if visible(guarded, t.get("user_id", guarded.get("sub")))]
            items.sort(key=lambda t: str(t.get("start_time") or ""), reverse=True)
            return JSONResponse(page(items, request))

        @app.get("/traces/{trace_id}")
        async def trace_detail(trace_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "traces:read")
            if isinstance(guarded, Response):
                return guarded
            detail = self.trace_details.get(trace_id)
            if detail is None or not visible(guarded, detail.get("user_id", guarded.get("sub"))):
                return JSONResponse({"detail": "Trace not found"}, status_code=404)
            return JSONResponse(detail)

        @app.get("/schedules")
        async def schedules(request: Request) -> Response:
            guarded = await self._guard(request, "schedules:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse(page(self.schedules, request))

        @app.get("/schedules/{schedule_id}/runs")
        async def schedule_runs(schedule_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "schedules:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse(page(self.schedule_runs.get(schedule_id, []), request))

        @app.get("/eval-runs")
        async def eval_runs(request: Request) -> Response:
            guarded = await self._guard(request, "evals:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse(page(self.eval_runs, request))

        async def run_eval(request: Request, path: str) -> Response:
            guarded = await self._guard(request, "evals:write")
            if isinstance(guarded, Response):
                return guarded
            body = orjson.loads(await request.body())
            self.eval_requests.append({"path": path, "body": body, "claims": guarded})
            result = self.eval_responder(body, path) if self.eval_responder else None
            if isinstance(result, tuple):
                status_code, payload = cast("tuple[int, Any]", result)
                return JSONResponse(payload, status_code=status_code)
            created = {
                "id": f"eval_{len(self.eval_requests)}",
                "eval_type": body["eval_type"],
                "agent_id": body.get("agent_id") or body.get("component_id"),
                "eval_data": {},
                "created_at": "2026-11-01T09:00:00Z",
                **(result or {}),
            }
            self.eval_runs.append(created)
            return JSONResponse(created)

        @app.post("/eval-runs")
        async def create_eval_run(request: Request) -> Response:
            return await run_eval(request, "/eval-runs")

        @app.get("/agnostic/v1/capabilities")
        async def bridge_capabilities(request: Request) -> Response:
            guarded = await self._guard(request, "config:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.bridge:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            endpoints = ["GET /agnostic/v1/capabilities", "POST /agnostic/v1/evals/run"]
            if self.bridge_files:
                endpoints.append("GET /agnostic/v1/files/provenance")
            if self.bridge_studio:
                endpoints.extend(
                    [
                        "POST /agnostic/v1/components/validate",
                        "POST /agnostic/v1/components/normalize",
                        "GET /agnostic/v1/introspect/components",
                        "GET /agnostic/v1/registry/{resource_type}/{name}/source",
                    ]
                )
            if self.bridge_cel:
                endpoints.append("POST /agnostic/v1/cel/evaluate")
            return JSONResponse({"bridge_version": "0.2.0", "endpoints": endpoints})

        @app.post("/agnostic/v1/evals/run")
        async def bridge_eval(request: Request) -> Response:
            if not self.bridge:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return await run_eval(request, "/agnostic/v1/evals/run")

        @app.get("/memories")
        async def memories(request: Request) -> Response:
            guarded = await self._guard(request, "memories:read")
            if isinstance(guarded, Response):
                return guarded
            user = request.query_params.get("user_id")
            items = [
                m for m in self.memories if (user is None or m["user_id"] == user) and visible(guarded, m["user_id"])
            ]
            items.sort(key=lambda m: str(m.get("updated_at") or ""), reverse=True)
            return JSONResponse(page(items, request))

        @app.get("/memories/{memory_id}")
        async def memory(memory_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "memories:read")
            if isinstance(guarded, Response):
                return guarded
            item = next((m for m in self.memories if m["memory_id"] == memory_id), None)
            if item is None or not visible(guarded, item["user_id"]):
                return JSONResponse({"detail": "Memory not found"}, status_code=404)
            return JSONResponse(item)

        @app.post("/optimize-memories")
        async def optimize(request: Request) -> Response:
            guarded = await self._guard(request, "memories:write")
            if isinstance(guarded, Response):
                return guarded
            body = orjson.loads(await request.body())
            before = [m for m in self.memories if m["user_id"] == body["user_id"]]
            after = [{**m, "user_id": body["user_id"]} for m in self.optimized]
            if body.get("apply", True):
                self.memories = [m for m in self.memories if m["user_id"] != body["user_id"]] + after
            return JSONResponse(
                {
                    "memories": after,
                    "memories_before": len(before),
                    "memories_after": len(after),
                    "tokens_before": 120,
                    "tokens_after": 80,
                    "tokens_saved": 40,
                    "reduction_percentage": 33.3,
                }
            )

        @app.get("/sessions/{session_id}/runs")
        async def session_runs(session_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "sessions:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse(self.session_runs.get(session_id, []))

        @app.get("/workflows")
        async def workflows(request: Request) -> Response:
            guarded = await self._guard(request, "workflows:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse(self.workflow_items)

        @app.post("/workflows/{workflow_id}/runs")
        async def run_workflow(workflow_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "workflows:run", workflow_id)
            if isinstance(guarded, Response):
                return guarded
            form = parse_qs((await request.body()).decode())
            version = form.get("version", [None])[0]
            pinned = self.configs.get(workflow_id, {}).get(int(version)) if version else None
            owner = self.components.get(workflow_id, {}).get("user_id")
            if (
                pinned is not None
                and pinned["stage"] == "draft"
                and ADMIN not in guarded.get("scopes", [])
                and guarded.get("sub") != owner
            ):
                return JSONResponse({"detail": f"Workflow {workflow_id} not found"}, status_code=404)
            self.run_requests.append(
                {
                    "workflow_id": workflow_id,
                    "user_id": self._run_user(guarded, form.get("user_id", [None])[0]),
                    "form": {key: values[0] for key, values in form.items()},
                    "query": dict(request.query_params),
                    "sub": guarded.get("sub"),
                }
            )
            steps = cast("list[dict[str, Any]]", (pinned or {}).get("config", {}).get("steps") or [])

            async def events() -> AsyncIterator[bytes]:
                for index, (name, payload) in enumerate(workflow_events(workflow_id, steps)):
                    body = {"event": name, "event_index": index, "workflow_id": workflow_id, **payload}
                    yield b"event: " + name.encode() + b"\ndata: " + orjson.dumps(body) + b"\n\n"
                    await asyncio.sleep(0.01)

            return StreamingResponse(events(), media_type="text/event-stream")

        @app.post("/agnostic/v1/cel/evaluate")
        async def bridge_cel(request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.bridge_cel:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            if not self.bridge_cel_installed:
                return JSONResponse({"detail": "cel-python isn't installed; install agno[cel]"}, status_code=503)
            body = cast("dict[str, Any]", orjson.loads(await request.body()))
            self.cel_requests.append(body)
            context = body["context"]
            choices = body.get("step_choices") if context == "router" else None
            try:
                value = evaluate_cel(body["expression"], cel_activation(context, body, choices=choices))
            except CelError as exc:
                return JSONResponse({"error": f"Failed to evaluate CEL expression: {exc.message}"}, status_code=422)
            result = bool(value) if context != "router" else str(value)
            return JSONResponse({"result": result, "type": "string" if context == "router" else "bool"})

        @app.get("/agents")
        async def agents(request: Request) -> Response:
            guarded = await self._guard(request, "agents:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse(self.agent_items)

        @app.get("/teams")
        async def teams(request: Request) -> Response:
            guarded = await self._guard(request, "teams:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse([])

        @app.get("/knowledge/content")
        async def knowledge_content(request: Request) -> Response:
            guarded = await self._guard(request, "knowledge:read")
            if isinstance(guarded, Response):
                return guarded
            rows = list(self.knowledge_content.get(request.query_params.get("knowledge_id", ""), []))
            rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
            return JSONResponse(page(rows, request))

        @app.get("/knowledge/config")
        async def knowledge_config(request: Request) -> Response:
            guarded = await self._guard(request, "knowledge:read")
            if isinstance(guarded, Response):
                return guarded
            return JSONResponse(
                {"vector_dbs": [{"id": "pgvector", "name": "PgVector", "search_types": ["vector", "hybrid"]}]}
            )

        @app.get("/learnings")
        async def learnings(request: Request) -> Response:
            guarded = await self._guard(request, "learnings:read")
            if isinstance(guarded, Response):
                return guarded
            query = request.query_params
            items = [
                item
                for item in self.learnings
                if all(query.get(key) is None or item.get(key) == query[key] for key in ("learning_type", "user_id"))
                and visible(guarded, item.get("user_id"))
            ]
            return JSONResponse(page(items, request))

        @app.delete("/learnings/users/{user_id}")
        async def delete_learnings(user_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "learnings:delete")
            if isinstance(guarded, Response):
                return guarded
            kind = request.query_params.get("learning_type")
            self.learnings = [
                item
                for item in self.learnings
                if not (item.get("user_id") == user_id and (kind is None or item["learning_type"] == kind))
            ]
            return Response(status_code=204)

        @app.get("/agnostic/v1/files/provenance")
        async def file_provenance(request: Request) -> Response:
            if not self.bridge_files:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            for scope in ("filesystem:read", "traces:read"):
                guarded = await self._guard(request, scope)
                if isinstance(guarded, Response):
                    return guarded
            path = request.query_params["path"]
            return JSONResponse({"path": path, "scanned_traces": 3, "events": self.file_events})

        run_endpoint = re.compile(r"^/(agents|teams|workflows)/([^/]+)/runs/?$")

        def schedule_or_404(schedule_id: str) -> dict[str, Any] | None:
            return next((item for item in self.schedules if item["id"] == schedule_id), None)

        async def schedule_write(request: Request, body: dict[str, Any]) -> dict[str, Any] | Response:
            guarded = await self._guard(request, "schedules:write")
            if isinstance(guarded, Response):
                return guarded
            endpoint = str(body.get("endpoint") or "")
            custom = (body.get("method") or "POST") != "POST" or not run_endpoint.match(endpoint)
            if custom and endpoint and ADMIN not in guarded.get("scopes", []):
                detail = "Only admins can schedule an endpoint that is not a run endpoint"
                return JSONResponse({"detail": detail}, status_code=403)
            return guarded

        @app.post("/schedules")
        async def create_schedule(request: Request) -> Response:
            body = orjson.loads(await request.body())
            guarded = await schedule_write(request, body)
            if isinstance(guarded, Response):
                return guarded
            item = {
                "id": f"sch_{len(self.schedules) + 1}",
                "user_id": guarded.get("sub"),
                "enabled": True,
                "next_run_at": 1793000000,
                "disabled_reason": None,
                "created_at": 1792000000,
                **body,
            }
            self.schedules.append(item)
            return JSONResponse(item, status_code=201)

        @app.get("/schedules/{schedule_id}")
        async def get_schedule(schedule_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "schedules:read")
            if isinstance(guarded, Response):
                return guarded
            item = schedule_or_404(schedule_id)
            return JSONResponse(item) if item else JSONResponse({"detail": "Schedule not found"}, status_code=404)

        @app.patch("/schedules/{schedule_id}")
        async def patch_schedule(schedule_id: str, request: Request) -> Response:
            body = orjson.loads(await request.body())
            item = schedule_or_404(schedule_id)
            if item is None:
                return JSONResponse({"detail": "Schedule not found"}, status_code=404)
            guarded = await schedule_write(request, {**item, **body})
            if isinstance(guarded, Response):
                return guarded
            item.update(body)
            return JSONResponse(item)

        @app.delete("/schedules/{schedule_id}")
        async def delete_schedule(schedule_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "schedules:delete")
            if isinstance(guarded, Response):
                return guarded
            self.schedules = [item for item in self.schedules if item["id"] != schedule_id]
            return Response(status_code=204)

        @app.post("/schedules/{schedule_id}/{action}")
        async def schedule_action(schedule_id: str, action: str, request: Request) -> Response:
            guarded = await self._guard(request, "schedules:write")
            if isinstance(guarded, Response):
                return guarded
            item = schedule_or_404(schedule_id)
            if item is None:
                return JSONResponse({"detail": "Schedule not found"}, status_code=404)
            if action in {"enable", "disable"}:
                item["enabled"] = action == "enable"
                return JSONResponse({"id": schedule_id, "name": item["name"], "enabled": item["enabled"]})
            if action == "trigger":
                if not item.get("enabled"):
                    return JSONResponse({"detail": "Schedule is disabled"}, status_code=409)
                runs = self.schedule_runs.setdefault(schedule_id, [])
                run = {
                    "id": f"srun_{len(runs) + 1}",
                    "schedule_id": schedule_id,
                    "attempt": 1,
                    "status": "running",
                    "triggered_at": 1792900000,
                }
                runs.insert(0, run)
                return JSONResponse(run)
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        def queue_guard(guarded: dict[str, Any] | Response) -> Response | None:
            if isinstance(guarded, Response):
                return guarded
            if ADMIN not in guarded.get("scopes", []):
                return JSONResponse({"detail": "Queue endpoints require admin"}, status_code=403)
            if not self.queue_enabled:
                return JSONResponse({"detail": "Durable queue is not configured"}, status_code=503)
            return None

        @app.get("/queue/stats")
        async def queue_stats(request: Request) -> Response:
            refused = queue_guard(await self._guard(request, ADMIN))
            if refused:
                return refused
            counts: dict[str, int] = {}
            for job in self.queue_jobs.values():
                counts[job["status"]] = counts.get(job["status"], 0) + 1
            return JSONResponse({"counts": counts, "oldest_queued_age_seconds": 3.0})

        @app.get("/queue/jobs")
        async def queue_jobs(request: Request) -> Response:
            refused = queue_guard(await self._guard(request, ADMIN))
            if refused:
                return refused
            status = request.query_params.get("status")
            items = [job for job in self.queue_jobs.values() if status is None or job["status"] == status]
            return JSONResponse(page(items, request))

        @app.get("/queue/jobs/{job_id}")
        async def queue_job(job_id: str, request: Request) -> Response:
            refused = queue_guard(await self._guard(request, ADMIN))
            if refused:
                return refused
            job = self.queue_jobs.get(job_id)
            return JSONResponse(job) if job else JSONResponse({"detail": "Job not found"}, status_code=404)

        @app.post("/queue/jobs/{job_id}/requeue")
        async def requeue(job_id: str, request: Request) -> Response:
            guarded = await self._guard(request, ADMIN)
            refused = queue_guard(guarded)
            if refused:
                return refused
            job = self.queue_jobs.get(job_id)
            if job is None:
                return JSONResponse({"detail": "Job not found"}, status_code=404)
            job.update(status="queued", max_attempts=job["max_attempts"] + 1, locked_by=None)
            self.requeued.append({"job_id": job_id, "params": dict(request.query_params), "claims": guarded})
            return JSONResponse(job)

        @app.get("/agents/{agent_id}/runs/{run_id}/checkpoints")
        async def checkpoints(agent_id: str, run_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "agents:run", agent_id)
            if isinstance(guarded, Response):
                return guarded
            session_id = request.query_params.get("session_id")
            return JSONResponse(
                {"run_id": run_id, "session_id": session_id, "checkpoints": self.checkpoints.get(run_id, [])}
            )

        @app.post("/agents/{agent_id}/runs/{run_id}/cancel")
        async def cancel(agent_id: str, run_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "agents:run", agent_id)
            if isinstance(guarded, Response):
                return guarded
            self.cancelled.append({"agent_id": agent_id, "run_id": run_id, "claims": guarded})
            if run_id in self.queue_jobs:
                self.queue_jobs[run_id]["status"] = "cancelled"
            return JSONResponse({})

        @app.get("/sessions/{session_id}/runs/{run_id}")
        async def session_run(session_id: str, run_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "sessions:read")
            if isinstance(guarded, Response):
                return guarded
            run = self.runs.get(run_id)
            if run is None or run.get("session_id", session_id) != session_id:
                return JSONResponse({"detail": "Run not found"}, status_code=404)
            return JSONResponse(run)

        @app.get("/agnostic/v1/workers")
        async def bridge_workers(request: Request) -> Response:
            guarded = await self._guard(request, ADMIN)
            if isinstance(guarded, Response):
                return guarded
            if self.bridge_workers is None:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return JSONResponse(self.bridge_workers)

        @app.get("/agnostic/v1/events")
        async def bridge_events(request: Request) -> Response:
            guarded = await self._guard(request, "schedules:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.bridge:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            since = int(request.query_params.get("since", "0"))
            events = [event for event in self.bridge_events if event["at"] > since]
            return JSONResponse({"events": events, "next_since": max([e["at"] for e in events], default=since)})

        return app

    # ------------------------------------------------------------------ service accounts (agno_pat_ tokens)

    def _pat_claims(self, token: str) -> dict[str, Any] | Response:
        digest = hashlib.sha256(token.encode()).hexdigest()
        account = next((a for a in self.service_accounts.values() if a["token_hash"] == digest), None)
        now = int(time.time())
        if account is None or account["revoked_at"] is not None:
            return JSONResponse({"detail": "Invalid or revoked service account token"}, status_code=401)
        if account["expires_at"] is not None and account["expires_at"] <= now:
            return JSONResponse({"detail": "Service account token expired"}, status_code=401)
        account["last_used_at"] = now
        return {
            "sub": account["principal"],
            "scopes": [item["scope"] for item in account["scopes"]],
            "service_account_id": account["id"],
        }

    def _run_user(self, claims: dict[str, Any], requested: str | None) -> str | None:
        """Who a run belongs to, like agno: PATs always ``sa:<name>``; JWTs under isolation their ``sub``."""
        scopes = claims.get("scopes", [])
        if "service_account_id" in claims and ADMIN not in scopes:
            return claims["sub"]
        if self.user_isolation and ADMIN not in scopes:
            return claims.get("sub")
        return requested or claims.get("sub")

    def touch_service_account(self, name: str, at: int | None = None) -> None:
        """Pretend the account's token was just used (``last_used_at``, epoch seconds)."""
        for account in self.service_accounts.values():
            if account["name"] == name and account["revoked_at"] is None:
                account["last_used_at"] = at if at is not None else int(time.time())

    @staticmethod
    def _public(account: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in account.items() if key not in {"token_hash", "token"}}

    def _service_account_routes(self, app: FastAPI) -> None:  # noqa: C901
        @app.post("/service-accounts")
        async def create_service_account(request: Request) -> Response:  # noqa: PLR0911
            guarded = await self._guard(request, "service_accounts:write")
            if isinstance(guarded, Response):
                return guarded
            body: dict[str, Any] = orjson.loads(await request.body())
            name = str(body.get("name", ""))
            if not _SA_NAME.fullmatch(name):
                return JSONResponse(
                    {"detail": "name must be a lowercase slug of at most 63 characters"}, status_code=400
                )
            if any(a["name"] == name and a["revoked_at"] is None for a in self.service_accounts.values()):
                return JSONResponse({"detail": f"A service account named {name!r} already exists"}, status_code=409)
            raw_scopes = body.get("scopes")
            if raw_scopes is None:
                raw_scopes = [
                    {"scope": s, "effect": "allow"}
                    for s in ("agents:run", "teams:run", "workflows:run", "sessions:read", "config:read")
                ]
            scopes = [{"scope": str(item["scope"]), "effect": item.get("effect", "allow")} for item in raw_scopes]
            privileged = [item["scope"] for item in scopes if _privileged(item["scope"])]
            if privileged and not body.get("allow_privileged_scopes", False):
                return JSONResponse(
                    {"detail": f"Privileged scopes need allow_privileged_scopes=true: {', '.join(privileged)}"},
                    status_code=400,
                )
            granted = guarded.get("scopes", [])
            if ADMIN not in granted and any(item["scope"] not in granted for item in scopes):
                return JSONResponse({"detail": "You can only grant scopes you hold"}, status_code=403)
            now = int(time.time())
            days = int(body.get("expires_in_days", 90))
            if not 1 <= days <= 3650:
                return JSONResponse({"detail": "expires_in_days must be between 1 and 3650"}, status_code=400)
            token = PAT_PREFIX + "".join(secrets.choice(_BASE62) for _ in range(32))
            account_id = f"sa_{secrets.token_hex(8)}"
            account: dict[str, Any] = {
                "id": account_id,
                "name": name,
                "principal": f"sa:{name}",
                "token_prefix": token[: len(PAT_PREFIX) + 4],
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                "scopes": scopes,
                "user_id": guarded.get("sub"),
                "created_by": guarded.get("sub"),
                "created_at": now,
                "expires_at": None if body.get("never_expires") else now + days * 86400,
                "last_used_at": None,
                "revoked_at": None,
            }
            self.service_accounts[account_id] = account
            return JSONResponse({**self._public(account), "token": token}, status_code=201)

        @app.get("/service-accounts")
        async def list_service_accounts(request: Request) -> Response:
            guarded = await self._guard(request, "service_accounts:read")
            if isinstance(guarded, Response):
                return guarded
            include_revoked = request.query_params.get("include_revoked", "false").lower() == "true"
            items = [
                self._public(a) for a in self.service_accounts.values() if include_revoked or a["revoked_at"] is None
            ]
            items.sort(key=lambda a: a["created_at"], reverse=True)
            limit = int(request.query_params.get("limit", "20"))
            number = int(request.query_params.get("page", "1"))
            chunk = items[(number - 1) * limit : number * limit]
            total_pages = max(1, -(-len(items) // limit))
            meta = {"page": number, "limit": limit, "total_pages": total_pages, "total_count": len(items)}
            return JSONResponse({"data": chunk, "meta": meta})

        @app.delete("/service-accounts/{account_id}")
        async def revoke_service_account(account_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "service_accounts:delete")
            if isinstance(guarded, Response):
                return guarded
            account = self.service_accounts.get(account_id)
            if account is None:
                return JSONResponse({"detail": "Service account not found"}, status_code=404)
            if account["revoked_at"] is None:
                account["revoked_at"] = int(time.time())
            return Response(status_code=204)

    # ------------------------------------------------------------------ authorization trails (admin only, like agno)

    def _authz_routes(self, app: FastAPI) -> None:  # noqa: C901  (one route each)
        def trail(rows: list[dict[str, Any]], request: Request) -> Response:
            limit = int(request.query_params.get("limit", "100"))
            number = int(request.query_params.get("page", "1"))
            descending = request.query_params.get("sort_order", "desc") == "desc"
            ordered = sorted(rows, key=lambda row: row["created_at"], reverse=descending)
            chunk = ordered[(number - 1) * limit : number * limit]
            total_pages = (len(rows) + limit - 1) // limit
            meta = {"page": number, "limit": limit, "total_pages": total_pages, "total_count": len(rows)}
            return JSONResponse({"data": chunk, "meta": meta})

        @app.get("/authz/scopes")
        async def authz_scopes(request: Request) -> Response:
            guarded = await self._guard(request, ADMIN)
            if isinstance(guarded, Response):
                return guarded
            if self.authz_decisions is None:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return JSONResponse([{"scope": "agents:read", "resource": "agents", "action": "read"}])

        @app.get("/authz/decisions")
        async def authz_decisions(request: Request) -> Response:
            guarded = await self._guard(request, ADMIN)
            if isinstance(guarded, Response):
                return guarded
            if self.authz_decisions is None:
                return JSONResponse({"detail": "Decision audit is not enabled"}, status_code=404)
            return trail(self.authz_decisions, request)

        @app.get("/authz/audit")
        async def authz_audit(request: Request) -> Response:
            guarded = await self._guard(request, ADMIN)
            if isinstance(guarded, Response):
                return guarded
            if self.authz_changes is None:
                return JSONResponse({"detail": "Change audit is not enabled"}, status_code=404)
            return trail(self.authz_changes, request)

    # ---------------------------------------------------------------- components, registry, Studio bridge routes

    def _component_routes(self, app: FastAPI) -> None:  # noqa: C901, PLR0915  (one route each)
        def now() -> int:
            self._clock = max(int(time.time()), self._clock + 1)
            return self._clock

        def not_found(what: str) -> JSONResponse:
            return JSONResponse({"detail": f"{what} not found"}, status_code=404)

        def guard_failed(component_id: str, guard: dict[str, Any] | None) -> JSONResponse | None:
            if not guard:
                return None
            versions = self.configs.get(component_id, {})
            latest = guard.get("latest_version")
            if latest is not None and latest != max(versions, default=0):
                return JSONResponse({"detail": "Stale latest_version"}, status_code=409)
            current = guard.get("current_version")
            stored = self.components[component_id].get("current_version") or 0
            if current is not None and current != stored:
                return JSONResponse({"detail": "Stale current_version"}, status_code=409)
            return None

        def paged(items: list[dict[str, Any]], request: Request) -> dict[str, Any]:
            limit = int(request.query_params.get("limit", "20"))
            number = int(request.query_params.get("page", "1"))
            pages = (len(items) + limit - 1) // limit
            return {
                "data": items[(number - 1) * limit : number * limit],
                "meta": {"page": number, "limit": limit, "total_pages": pages, "total_count": len(items)},
            }

        def stored_config(component_id: str, version: int, body: dict[str, Any], stamp: int) -> dict[str, Any]:
            return {
                "component_id": component_id,
                "version": version,
                "stage": body.get("stage") or "draft",
                "label": body.get("label"),
                "notes": body.get("notes"),
                "config": body["config"],
                "links": body.get("links") or [],
                "created_at": stamp,
                "updated_at": stamp,
            }

        @app.get("/components")
        async def list_components(request: Request) -> Any:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            kind = request.query_params.get("component_type")
            deleted = request.query_params.get("include_deleted") == "true"
            items = [
                item
                for item in self.components.values()
                if (kind is None or item["component_type"] == kind) and (deleted or item.get("deleted_at") is None)
            ]
            return paged(items, request)

        @app.post("/components")
        async def create_component(request: Request) -> Response:
            guarded = await self._guard(request, "components:write")
            if isinstance(guarded, Response):
                return guarded
            body = orjson.loads(await request.body())
            component_id = body.get("component_id") or re.sub(r"[^a-z0-9]+", "-", body["name"].lower()).strip("-")
            if component_id in self.components:
                return JSONResponse({"detail": f"Component {component_id} already exists"}, status_code=409)
            stamp = now()
            published = (body.get("stage") or "draft") == "published"
            self.components[component_id] = {
                "component_id": component_id,
                "component_type": body["component_type"],
                "name": body["name"],
                "description": body.get("description"),
                "metadata": body.get("metadata"),
                "current_version": 1 if published else None,
                "user_id": guarded.get("sub"),
                "created_at": stamp,
                "updated_at": stamp,
                "deleted_at": None,
            }
            self.configs[component_id] = {}
            if body.get("config") is not None:
                self.configs[component_id][1] = stored_config(component_id, 1, body, stamp)
            return JSONResponse(self.components[component_id], status_code=201)

        @app.get("/components/{component_id}")
        async def get_component(component_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            item = self.components.get(component_id)
            if item is None or (item.get("deleted_at") and request.query_params.get("include_deleted") != "true"):
                return not_found("Component")
            return JSONResponse(item)

        @app.patch("/components/{component_id}")
        async def patch_component(component_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "components:write")
            if isinstance(guarded, Response):
                return guarded
            if component_id not in self.components:
                return not_found("Component")
            body = orjson.loads(await request.body())
            for key in ("name", "description", "metadata"):
                if body.get(key) is not None:
                    self.components[component_id][key] = body[key]
            self.components[component_id]["updated_at"] = now()
            return JSONResponse(self.components[component_id])

        @app.delete("/components/{component_id}")
        async def archive_component(component_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "components:delete")
            if isinstance(guarded, Response):
                return guarded
            if component_id not in self.components:
                return not_found("Component")
            dependents = sorted(
                {
                    parent
                    for parent, versions in self.configs.items()
                    for item in versions.values()
                    for link in item.get("links") or []
                    if link.get("child_component_id") == component_id and parent != component_id
                }
            )
            if dependents:
                return JSONResponse({"detail": "Pinned by other components", "dependents": dependents}, status_code=409)
            self.components[component_id]["deleted_at"] = now()
            return Response(status_code=204)

        @app.post("/components/{component_id}/restore")
        async def restore_component(component_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "components:delete")
            if isinstance(guarded, Response):
                return guarded
            if component_id not in self.components:
                return not_found("Component")
            self.components[component_id]["deleted_at"] = None
            return JSONResponse(self.components[component_id])

        @app.get("/components/{component_id}/configs")
        async def list_configs(component_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            if component_id not in self.components:
                return not_found("Component")
            with_config = request.query_params.get("include_config", "true") == "true"
            versions = self.configs.get(component_id, {})
            return JSONResponse(
                [
                    {key: value for key, value in versions[number].items() if key != "config" or with_config}
                    for number in sorted(versions)
                ]
            )

        @app.post("/components/{component_id}/configs")
        async def create_config(component_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "components:write")
            if isinstance(guarded, Response):
                return guarded
            if component_id not in self.components:
                return not_found("Component")
            body = orjson.loads(await request.body())
            failed = guard_failed(component_id, body.get("guard"))
            if failed is not None:
                return failed
            versions = self.configs.setdefault(component_id, {})
            version = max(versions, default=0) + 1
            versions[version] = stored_config(component_id, version, body, now())
            if versions[version]["stage"] == "published" and body.get("set_current", True):
                self.components[component_id]["current_version"] = version
            return JSONResponse(versions[version], status_code=201)

        @app.get("/components/{component_id}/configs/current")
        async def current_config(component_id: str, request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            item = self.components.get(component_id)
            current = item.get("current_version") if item else None
            if current is None:
                return not_found("Current config")
            return JSONResponse(self.configs[component_id][current])

        @app.get("/components/{component_id}/configs/{version}")
        async def component_config(component_id: str, version: int, request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            stored = self.configs.get(component_id, {}).get(version)
            if stored is not None:
                return JSONResponse(stored)
            stage = self.component_stages.get((component_id, version))
            if stage is None:
                return not_found("Config")
            return JSONResponse({"component_id": component_id, "version": version, "stage": stage, "config": {}})

        @app.patch("/components/{component_id}/configs/{version}")
        async def patch_config(component_id: str, version: int, request: Request) -> Response:
            guarded = await self._guard(request, "components:write")
            if isinstance(guarded, Response):
                return guarded
            stored = self.configs.get(component_id, {}).get(version)
            if stored is None:
                return not_found("Config")
            if stored["stage"] == "published":
                return JSONResponse({"detail": "Published configs are immutable"}, status_code=400)
            body = orjson.loads(await request.body())
            failed = guard_failed(component_id, body.get("guard"))
            if failed is not None:
                return failed
            for key in ("config", "label", "notes", "links"):
                if body.get(key) is not None:
                    stored[key] = body[key]
            if body.get("stage") == "published":
                stored["stage"] = "published"
                self.components[component_id]["current_version"] = version
            stored["updated_at"] = now()
            self.config_patches.append({"component_id": component_id, "version": version, "body": body})
            return JSONResponse(stored)

        @app.delete("/components/{component_id}/configs/{version}")
        async def delete_config(component_id: str, version: int, request: Request) -> Response:
            guarded = await self._guard(request, "components:delete")
            if isinstance(guarded, Response):
                return guarded
            stored = self.configs.get(component_id, {}).get(version)
            if stored is None:
                return not_found("Config")
            if stored["stage"] != "draft":
                return JSONResponse({"detail": "Only drafts can be deleted"}, status_code=400)
            del self.configs[component_id][version]
            return Response(status_code=204)

        @app.post("/components/{component_id}/configs/{version}/set-current")
        async def set_current(component_id: str, version: int, request: Request) -> Response:
            guarded = await self._guard(request, "components:write")
            if isinstance(guarded, Response):
                return guarded
            stored = self.configs.get(component_id, {}).get(version)
            if stored is None:
                return not_found("Config")
            if stored["stage"] != "published":
                return JSONResponse({"detail": "Only published versions can be current"}, status_code=400)
            raw = await request.body()
            failed = guard_failed(component_id, (orjson.loads(raw) if raw else {}).get("guard"))
            if failed is not None:
                return failed
            self.components[component_id]["current_version"] = version
            return JSONResponse(self.components[component_id])

        @app.get("/registry")
        async def registry(request: Request) -> Response:
            guarded = await self._guard(request, "registry:read")
            if isinstance(guarded, Response):
                return guarded
            kind = request.query_params.get("resource_type")
            needle = (request.query_params.get("name") or "").lower()
            items = [
                item
                for item in self.registry_items
                if (kind is None or item["type"] == kind) and needle in str(item["name"]).lower()
            ]
            return JSONResponse(paged(items, request))

        @app.post("/agnostic/v1/components/validate")
        async def bridge_validate(request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.bridge_studio:
                return not_found("Route")
            body = orjson.loads(await request.body())
            self.bridge_validations.append(body)
            known = {(item["type"], item["name"]) for item in self.registry_items}
            errors = [
                {"path": f"tools[{index}]", "message": f"Tool '{tool.get('name')}' is not in the registry"}
                for index, tool in enumerate(body["config"].get("tools") or [])
                if ("tool", tool.get("toolkit") or tool.get("name")) not in known
            ]
            return JSONResponse({"valid": not errors, "errors": errors})

        @app.post("/agnostic/v1/components/normalize")
        async def bridge_normalize(request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.bridge_studio:
                return not_found("Route")
            return JSONResponse({"config": orjson.loads(await request.body())["config"]})

        @app.get("/agnostic/v1/introspect/components")
        async def bridge_introspect(request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.bridge_studio:
                return not_found("Route")
            return JSONResponse(self.code_components)

        @app.get("/agnostic/v1/registry/{resource_type}/{name}/source")
        async def bridge_source(resource_type: str, name: str, request: Request) -> Response:
            guarded = await self._guard(request, "registry:read")
            if isinstance(guarded, Response):
                return guarded
            if not self.bridge_studio:
                return not_found("Route")
            if not any(item["type"] == resource_type and item["name"] == name for item in self.registry_items):
                return not_found("Registry entry")
            source = {"type": resource_type, "name": name, "module": "app.tools", "file": "app/tools.py", "line": 10}
            return JSONResponse({**source, "declared": True, **self.registry_sources.get((resource_type, name), {})})
