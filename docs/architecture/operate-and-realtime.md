# Operate: runs, approvals, Home and realtime

P02 makes the control plane usable day to day: Chat runs any agent, team or workflow and streams it; approvals are
decided inline; Sessions inspects what happened; Home says what needs attention; ⌘K finds things; a realtime stream
keeps badges current. This page explains how those pieces fit.

## Modules

| Backend module | Owns |
|---|---|
| `approvals` | `POST /instances/{instance}/approvals/{id}/decide`, `GET …/approvals/count`, the pending-count poller |
| `observe` | `GET /instances/{instance}/overview` (Home), the attention rules, the overview cache and its warmer job |
| `search` | `GET /search` and the `search_documents` index (Postgres full text; LIKE on SQLite) |
| `notifications` | `GET /events`, the realtime SSE stream (the inbox and channels come in P05) |

The kernel gained an `EventBus` (`agnostic_kernel.events`). The gateway gained delegated elevation and a facade.
Instances gained `elevation_enabled` and `InstancesFacade.system_call`.

| Frontend | Owns |
|---|---|
| `@agnostic/core` `run-stream/` | `RunStream`, the run reducer, stored-run adapter, the stream registry and hooks |
| `@agnostic/core` `realtime/` | `RealtimeClient` (leader tab), `RealtimeProvider`, `useApprovalsCount` |
| `@agnostic/core` `agentos.ts` | typed AgentOS reads and session actions through the gateway |
| `modules/home`, `modules/chat`, `modules/sessions` | the pages |
| `@agnostic/ui` | `RunBlock`, `ToolCallChip`, `ApprovalCard`, `StepTimeline`, `StepHitlForm`, `Composer`, `SessionList`, `KpiTile`, `AttentionCard`, `DataTable`, `StackedBarChart`, `MarkdownView`, `JsonEditor`, … |

AgentOS types come from the pinned AgentOS OpenAPI (`yarn api:gen` also writes `packages/api/src/agentos`) and are
exported as `AgentOS.*` from `@agnostic/api`.

## A run, end to end

```
Chat ──POST …/os/agents/{id}/runs (multipart, background=true, stream=true, Idempotency-Key)──▶ gateway ──▶ AgentOS
     ◀──────────────── SSE: RunStarted … ToolCallStarted … RunPaused (event_index 0…n) ◀────────────────────
```

- **Background + stream.** The run belongs to AgentOS's durable queue, not to the HTTP request: a closed tab, a
  dropped proxy or a restarted API replica doesn't stop it.
- **The reducer** (`reduceRun`) folds events into one `RunState`: status, content, reasoning, tool calls with
  durations, member runs of teams (by `parent_run_id`/`nested_depth`), team tasks, the workflow step tree (steps,
  loops with iterations, routers with the chosen route, parallel, conditions), the pause (tools, team requirements,
  or workflow step requirements), metrics, citations. Events at or below the last applied `event_index` are skipped,
  and unknown events are counted, not fatal.
- **Reconnect.** When a stream ends before the run settles, `RunStream` calls `…/runs/{id}/resume` with
  `last_event_index` and backs off (0.5, 1, 2, 4, 8, 15 s). Active runs are kept in `sessionStorage`, so a browser
  refresh resumes them too (`restoreRuns`).
- **Stored runs** (`GET /sessions/{id}/runs`) go through the same reducer when the component stores events
  (`store_events=True`, set on every reference component), so history and live runs render alike.

Fixtures: `packages/core/src/run-stream/__fixtures__/recorded/` holds runs recorded from the reference runtime
(`scripts/record_sse_fixtures.py`); `recorded.test.ts` asserts every event is understood. Re-record them for a new
agno minor.

## Deciding an approval

```
ApprovalCard ──POST /instances/{i}/approvals/{id}/decide {decision, note?, edited_args?}──▶ approvals
   approvals: require approvals:write ─▶ elevated GET /approvals/{id}
                                       ─▶ elevated POST /approvals/{id}/resolve {status, resolved_by, resolution_data}
                                       ─▶ elevated POST /{family}/{id}/runs/{run}/continue (background=true, stream=false)
                                       ─▶ audit approvals.decided (args diff) · publish approval.resolved
Chat ──POST …/runs/{run}/resume (from the start)──▶ the continuation streams in
```

- AgentOS keeps resolving and resuming separate; the control plane does both as one action.
- The continuation carries the decision: agents get `tools` (the paused tool executions with `confirmed` and the
  possibly edited `tool_args`), teams `requirements`, workflows `step_requirements`. The contract test
  `tests/contract/test_p02_approvals.py` proves an edited amount is what the tool runs with.
- Runs submitted through the durable queue must be continued with `background=true`; the queue owns the
  continuation, and a 409 (a ticket still owns the run) is retried with backoff.
- Decide is idempotent per approval: a repeat returns the first outcome, and an approval someone already resolved
  is reported as such.

### Delegated elevation

Under `user_isolation` AgentOS returns 404 when a non-admin resolves someone else's approval or continues their run.
For typed actions only (never the passthrough), `GatewayFacade.elevated(...)`:

1. refuses when the instance has elevation turned off (`elevation_disabled`, "Only Instance admins can …");
2. checks the justifying scope in the control plane (`approvals:write` for decisions);
3. mints a 60-second token with `scopes=["agent_os:admin"]`, `sub` = the person deciding, `agnostic.via =
   "elevated"`; registers its `jti` in the ephemeral store and consumes it right before the single request (a retry
   mints a new one);
4. audits `gateway.elevated` with the route, scope and `jti`.

Admins turn it off per instance in Settings › Authorization (`elevation_enabled`).

## Home

`GET /instances/{instance}/overview?range=24h|7d|30d` is computed as the control plane (system token), because it is
instance-wide by nature:

| Section | Source |
|---|---|
| counts, primitives | `/config`, versions from `/components`, runs and errors per component from the trace sample |
| runs, sessions, runs per day, model usage | `/metrics` daily rows (current and previous period) |
| error rate, failed runs, p95 latency, last run | `/traces` (up to `max_trace_pages` × 100 newest traces; the tiles turn dashed when sampled) |
| attention | approvals backlog (`/approvals?status=pending`), error spike, failing schedules (`/schedules/{id}/runs`) |
| activity | the audit log (`AuditReader.recent`) |

The result is cached for 60 s per (instance, range) and kept warm by `observe.warm_overviews` every minute. Each
viewer then gets only the sections their scopes allow (`metrics:read`, `traces:read`, `approvals:read`,
`schedules:read`, `config:read`, `audit:read`); a missing scope, a disabled capability or a failing source turns a
section into `unavailable[section]` with the reason, never a 500.

Attention rules (`observe/domain/attention.py`): any pending approval; error rate ≥ 5 % or at least double the
previous period (≥ 20 runs); a schedule whose latest run failed ("failed twice" after two). Eval regressions arrive
with P03.

## Realtime

`GET /api/v1/events` is one SSE stream per browser:

- **Channels**: `evt:user:{id}`, `evt:org`, and `evt:instance:{id}` for every instance where the person holds any
  runtime scope. Events are filtered per scope (`approvals.count` and `approval.resolved` need `approvals:read`).
- **Replay**: every channel keeps ~1000 events for 15 minutes; reconnecting with `Last-Event-ID` gets what was
  missed. `MemoryEventBus` does the same in one process (SQLite installs, tests).
- **Access changes**: the stream checks the access generation on every heartbeat; when it moved it sends
  `access.changed` and ends, and the browser reconnects with fresh permissions.
- **Leader tab**: `RealtimeClient` takes a Web Lock; only the holder connects and re-broadcasts over a
  `BroadcastChannel`. When it closes, another tab gets the lock at once.
- **The approvals badge**: one API replica per instance polls `/approvals/count` every 15 s
  (`AGNOSTIC_APPROVALS__POLL_SECONDS`, a short lock keeps replicas from doubling up) and publishes `approvals.count`
  only when it changes; `GET …/approvals/count` serves the last value for the first paint.

| Event | Effect in the browser |
|---|---|
| `approvals.count` | sets the badge count in place |
| `approval.resolved` | refetches the badge and Home |
| `access.changed` | refetches `/me` and `/me/access` |
| `instance.health` | refetches instance health |

## Search (⌘K)

`search_documents` is rebuilt every 5 minutes (and on first use) from each module's `SearchProvider.documents`:
org members (org), instances and the agents, teams and workflows in their latest `/config` snapshot (instances).
PostgreSQL ranks prefix full-text matches (`to_tsquery('simple', 'supp:* & tri:*')`), title prefixes and exact ids;
SQLite uses LIKE. Hits are filtered through the person's scopes. The palette adds live AgentOS lookups as the person:
a pasted session id opens that session, a trace or run id opens Traces, a name finds sessions, and "New session
with…" lists what they can run.
