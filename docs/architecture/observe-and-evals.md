# Observe: traces, metrics and evaluations

Three pages explain how agents behave. **Traces** shows why a run did what it did and lines it up with the last
successful run of the same component. **Metrics** shows what an instance costs, from the customer's own price table.
**Evaluations** runs a dataset against a component version and compares versions case by case, with a publish gate
that Studio enforces. Every narrative sentence here (trace diagnosis, eval insight, gate consequence) comes from
fixed templates and is marked `generated: false`.

## Modules

| Backend | Owns |
|---|---|
| `observe` | `GET …/traces/{id}/comparison`, `GET …/traces/span-stats`, `GET …/metrics/summary`, `GET …/metrics/export.csv`, `GET/PUT …/price-table`, `GET/PUT /price-table` (org defaults); tables `obs_price_tables`, `obs_trace_comparisons` |
| `evals` | `…/eval-datasets` (+ cases, import), `…/evaluations`, `…/eval-batches` (+ compare, cancel), `…/eval-results`, `…/evals/capabilities`, `…/eval-gates`; tables `eval_datasets`, `eval_cases`, `eval_batches`, `eval_batch_items`, `eval_publish_gates`; the `evals.run_batch` job |
| `gateway` | `GatewayFacade.call`: one AgentOS call as the signed-in person, through the same pipeline as the passthrough |

All routes are under `/api/v1/instances/{instance}` except the org price table.

| Frontend | Owns |
|---|---|
| `modules/traces`, `modules/metrics`, `modules/evals` | the pages |
| `@agnostic/ui` | `SpanWaterfall` (virtualized), `SpanTree`, `SpanAttributes`, `RadioCards`, `ThinBar`; `StackedBarChart` gained end labels and value formats |
| `@agnostic/core` | `costs.ts` (the cost arithmetic, mirrored from the backend), `useDebouncedCallback` |

## Calling AgentOS as the person

Typed endpoints that read AgentOS data on someone's behalf use `GatewayFacade.call(principal, instance, …)`. It runs
the passthrough pipeline (route policy, scope pre-check, scoped JWT, audit), so user isolation and per-component
grants apply exactly as in the browser. Two reads are instance-wide aggregates computed as the control plane, like
the Home overview: span statistics and the bridge capability check. They still require the caller's scope first
(`traces:read`).

## Trace comparison

`GET …/traces/{trace_id}/comparison`:

1. Read the trace as the viewer and parse its `TraceNode` tree into flat spans (depth first, children by start
   time). Each span keeps its **name path** from the root and OpenInference attributes rebuilt from the node's
   `metadata`, `input`, `output` and `error`.
2. Find the baseline as the viewer: the newest trace of the same agent, team or workflow with status `OK`, no
   failed spans, that started before this one. When the trace carries a component version, the newest of the first
   few candidates with the same version wins.
3. Align spans by name path. Repeats of a path become one row with a count (`web_search ×2`); occurrence *i* of a path
   is drawn over occurrence *i* of the baseline (the ghost bars). Row states: `same`, `slower`, `faster` (a change of
   at least 250 ms and a quarter of the baseline time), `error` (more failures than before), `new`, `not_run`.
4. Diagnose with templates, in order: version and input shape ("Same version, same input shape."), then the most
   significant changed leaf span, preferring new failures ("The only change is `web_search`, which now fails with
   TimeoutError (30 s ×2 instead of 4.1 s)"), then what never ran ("so the workflow never reached `Write brief`"),
   then new spans.

Results are cached in `obs_trace_comparisons` by `(instance, trace, baseline)` for
`AGNOSTIC_OBSERVE__COMPARISON_CACHE_DAYS`. The baseline lookup always runs as the viewer first, so a cache hit never
shows a comparison against a trace the viewer can't list.

## Metrics and cost

AgentOS `/metrics` rows give runs and sessions per component type, distinct users, token totals and per-model
**run counts** per day; they have no per-component split and no tokens per model. Session list items have both
(`metrics.details[model_type][]` with tokens per model, plus the component id), so `GET …/metrics/summary` reads:

- `/metrics` for the range: totals, runs per day by type, tokens per day, model usage;
- `/sessions` sorted by `updated_at`, the sessions active in the range (up to `MAX_SESSION_PAGES` pages): per-component
  sessions and tokens per model, distinct users;
- `/traces` in the range: runs per component (optional; its absence is reported in `unavailable`).

Cost rules, identical in `agnostic_observe.domain.costs` and `@agnostic/core` `costs.ts`:

- prices are USD per million tokens, per model; an instance row overrides the org row for the same model and provider;
- cache-read tokens are part of input tokens and are billed at the cache-read rate when set, otherwise at the input
  rate; reasoning tokens are part of output tokens and use the reasoning rate when set;
- a component's tokens are priced per model; tokens its sessions didn't tie to a model are priced at its primary
  model (the row is marked `≈` when it used several models);
- the **gap** (daily-total tokens the range's sessions don't explain) is split across models by run share, and makes
  the total approximate.

The page recomputes everything in the browser as prices are typed and saves the table (debounced). Refresh runs
AgentOS's own `POST /metrics/refresh?background=true` through the passthrough and polls `GET /metrics/refresh/status`.

## Evaluations

- **Datasets are org-wide.** Every instance evaluates against the same cases, so staging and production results are
  comparable. The routes run through an instance and check `evals:read` / `evals:write` there. Each eval type needs
  its expectation: accuracy an expected output, agent-as-judge criteria, reliability expected tool calls. Cases can
  be imported from CSV or JSON Lines.
- **A batch** evaluates one component version on one dataset: one AgentOS eval run per case. Starting one checks
  `evals:write` and `<agents|teams>:<id>:run`, snapshots every case into `eval_batch_items` (later dataset edits
  don't rewrite results) and queues `evals.run_batch` on the `evals` queue with a per-instance lock.
- **The job** rebuilds the starter's principal and sends each case through the gateway as that person, at most
  `AGNOSTIC_EVALS__CONCURRENCY` at a time, each call in its own request scope. A revoked grant stops the remaining
  cases; a failing case is recorded and doesn't fail the batch; cancelling stops between cases. Progress goes to the
  batch row and to `evals.batch.progress` events on the instance channel.
- **Versions and the judge need agnostic-bridge.** AgentOS `/eval-runs` evaluates the current component, and its
  `model_id` replaces the evaluated component's model, so without the bridge the judge is the instance default and
  drafts can't be evaluated (the API answers `409 bridge_required`). With the bridge, every batch goes through
  `POST /agnostic/v1/evals/run` (current version too), which pins the version and uses `model_id` for the judge only;
  results land in the AgentOS eval DB and show up in `/eval-runs`.
- **Scores** are normalised per type: accuracy and numeric judges score 0–10 (pass at 7), binary judges and
  reliability pass or fail, performance reports average run time. Batch statistics are average, mean, min, max,
  standard deviation, pass ratio and cases below 7.
- **Comparison** matches two batches of the same dataset case by case. A case regresses when its score drops below 7
  or by 2 or more (or it goes from pass to fail), and is fixed the other way round. The insight names the cases:
  "v4 draft fixes case 5 but regresses cases 2 and 3 (9 → 3, 10 → 4) compared with v3."
- **Evaluations table** merges batches with AgentOS eval runs made elsewhere (agno scripts, other tools) that no
  batch owns.

### Publish gates

A gate is a minimum average on a dataset for one component (`evals:gates:write`). Its consequence is computed from
the newest finished batch for that component, dataset and type: "v4 draft (7.20) would be blocked from publishing."
For pass/fail eval types the gate compares the pass ratio scaled to ten. Studio's Publish enforces the gate, with an
audited override for Owners and Administrators.

## Audit actions

`observe.price_table.updated`, `evals.dataset.created|updated|imported|deleted`, `evals.batch.started|cancelled`,
`evals.gate.updated|deleted`. Eval runs sent through the gateway are also audited as `gateway.request`.
