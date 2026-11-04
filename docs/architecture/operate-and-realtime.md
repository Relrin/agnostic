# Operate: runs, approvals, Home and realtime

Chat runs any agent, team or workflow and streams it; approvals are decided inline; Sessions shows history; Home
says what needs attention; ⌘K finds things; one realtime stream per browser keeps badges current.

## Code

`…` is `/api/v1/instances/{instance}`.

| Where | Owns |
|---|---|
| `approvals` | `…/approvals/{id}/decide`, `…/approvals/count`, the pending-count poller (inbox: [control](control.md)) |
| `observe` | `…/overview` (Home), attention rules, overview cache, `observe.warm_overviews` |
| `search` | `GET /search`, the `search_documents` index |
| `notifications` | `GET /events`, the realtime SSE stream |
| `gateway` | `GatewayFacade.elevated(...)` |
| `@agnostic/core` | `run-stream/` (`RunStream`, `reduceRun`, `RunView`), `realtime/` (`RealtimeClient`, `RealtimeProvider`, `useApprovalsCount`), `agentos.ts` |
| `modules/home`, `chat`, `sessions` | the pages |

AgentOS types are generated from the pinned AgentOS OpenAPI into `packages/api/src/agentos` (`yarn api:gen`) and
exported as `AgentOS.*` from `@agnostic/api`.

## A run

Chat posts `…/os/{family}/{id}/runs` with `background=true`, `stream=true` and an `Idempotency-Key`; the run belongs
to AgentOS's durable queue, so a closed tab doesn't stop it. `reduceRun` folds SSE events into one `RunState`
(content, tool calls, team members, the workflow step tree, the pause, metrics), skipping events at or below the last
`event_index` and counting unknown ones. When a stream ends early, `RunStream` calls `…/runs/{id}/resume` with
`last_event_index`, backing off 0.5 to 15 s; active runs survive a refresh via `sessionStorage`. Stored runs go
through the same reducer.

![Run stream: Chat, gateway, AgentOS run SSE, the RunStream reducer, pause for approval](images/run-stream.svg)

Recorded fixtures (`packages/core/src/run-stream/__fixtures__/recorded/`, `scripts/record_sse_fixtures.py`) are
checked by `recorded.test.ts`; re-record them for a new agno minor.

## Deciding an approval

`POST …/approvals/{id}/decide {decision, note?, edited_args?}` checks `approvals:write`, then, elevated, resolves the
approval and continues the run (`background=true`), audits `approvals.decided` and publishes `approval.resolved`;
Chat resumes the stream. The continuation carries the decision (`tools` with edited `tool_args`, `requirements`, or
`step_requirements`); `tests/contract/test_inline_approvals.py` proves an edited amount is what the tool runs with.
Decide is idempotent, and a 409 from the queue is retried with backoff.

![Approval decision: ApprovalCard, approvals module, delegated elevation, AgentOS continue, audit and realtime publish](images/approval-decision.svg)

### Delegated elevation

Under `user_isolation` AgentOS answers 404 when a non-admin resolves someone else's approval. For typed actions
only, `GatewayFacade.elevated(...)` refuses when the instance has `elevation_enabled` off, checks the justifying
scope, mints a 60 s `agent_os:admin` token with `sub` = the person and `agnostic.via = "elevated"`, consumes its
`jti` on the single request, and audits `gateway.elevated`.

## Home

`GET …/overview?range=24h|7d|30d` is computed as the control plane from `/config`, `/components`, `/metrics`,
`/traces` (up to `AGNOSTIC_OBSERVE__MAX_TRACE_PAGES` × 100; sampled tiles are dashed), approvals, schedules and the
audit log. It is cached 60 s per (instance, range) and warmed every minute; each viewer gets only the sections their
scopes allow, and a missing scope or failing source becomes `unavailable[section]`, never a 500.

Attention rules (`observe/domain/attention.py`): pending approvals; error rate ≥ 5 % or double the previous period
(≥ 20 runs); a schedule whose latest run failed. Eval regressions arrive as `evals.regression` notifications.

## Realtime

`GET /api/v1/events` (`agnostic_kernel.events`):

- channels `evt:user:{id}`, `evt:org`, and `evt:instance:{id}` for every instance where the person holds a runtime
  scope; events filtered per scope;
- each channel keeps ~1000 events for 15 minutes for `Last-Event-ID` replay (`MemoryEventBus` in one process);
- when the access generation moves, the stream sends `access.changed` and ends, and the browser reconnects;
- `RealtimeClient` takes a Web Lock so only one tab connects, re-broadcasting over a `BroadcastChannel`;
- one replica per instance polls `/approvals/count` every 15 s (`AGNOSTIC_APPROVALS__POLL_SECONDS`) and publishes
  `approvals.count` on change.

`approvals.count` sets the badge; `approval.resolved` refetches badge and Home; `access.changed` refetches `/me` and
`/me/access`; `instance.health` refetches health. Other events are listed with their pages.

## Search (⌘K)

`search_documents` is rebuilt every 5 minutes from each module's `SearchProvider` (org members; instances and the
components in their `/config` snapshot), ranked by PostgreSQL full text (LIKE on SQLite) and filtered by scopes. The
palette adds live AgentOS lookups as the person: pasted session, trace or run ids, session names, "New session
with…".
