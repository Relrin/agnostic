"""A small in-process AgentOS 3.1 stand-in: verifies control-plane JWTs and enforces scopes the way agno does.

Only the routes the tests need: health/info/config, sessions, an SSE run, approvals (list, get, resolve, count),
run continuation, metrics, traces (list, detail), schedules, component configs, eval runs, and the bridge's
capabilities and version-pinned eval routes (when ``bridge`` is on), and the context routes (memories, optimize,
session runs, knowledge content and config, learnings, agents and teams, and the bridge's file provenance when
``bridge_files`` is on), schedule CRUD with enable/disable/trigger, the durable queue (``queue_enabled``; admin
only, like agno), run checkpoints and cancel, and the bridge's workers and events feed. Approvals answer 503 unless
``approvals_enabled``. Under ``user_isolation`` non-admins get 404 for other people's approvals, runs and traces,
like agno.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any, cast
from urllib.parse import parse_qs

import jwt
import orjson
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

ADMIN = "agent_os:admin"


def _holds(scopes: list[str], required: str, resource_id: str | None = None) -> bool:
    if ADMIN in scopes or required in scopes:
        return True
    resource, action = required.split(":")
    return resource_id is not None and f"{resource}:{resource_id}:{action}" in scopes


class FakeAgentOS:
    def __init__(
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
        self.app = self._build()

    def _claims(self, request: Request) -> dict[str, Any] | Response:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return JSONResponse({"detail": "Authorization header missing"}, status_code=401)
        token = header.removeprefix("Bearer ")
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

        @app.get("/components/{component_id}/configs/{version}")
        async def component_config(component_id: str, version: int, request: Request) -> Response:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            stage = self.component_stages.get((component_id, version))
            if stage is None:
                return JSONResponse({"detail": "Config not found"}, status_code=404)
            return JSONResponse({"component_id": component_id, "version": version, "stage": stage, "config": {}})

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
            return JSONResponse({"bridge_version": "0.2.0", "endpoints": endpoints})

        @app.post("/agnostic/v1/evals/run")
        async def bridge_eval(request: Request) -> Response:
            if not self.bridge:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return await run_eval(request, "/agnostic/v1/evals/run")

        @app.get("/components")
        async def components(request: Request) -> Any:
            guarded = await self._guard(request, "components:read")
            if isinstance(guarded, Response):
                return guarded
            return {"data": [], "meta": {"page": 1, "limit": 1, "total_pages": 0, "total_count": 0}}

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
