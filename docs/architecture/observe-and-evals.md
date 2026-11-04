# Observe: traces, metrics and evaluations

**Traces** compares a run with the last good run of the same component. **Metrics** prices an instance's usage from
the customer's own price table. **Evaluations** runs a dataset against a component version, compares versions case
by case, and gates publishing. Narrative sentences (trace diagnosis, eval insight, gate consequence) come from fixed
templates (`generated: false`).

## Code

`…` is `/api/v1/instances/{instance}`.

| Where | Owns |
|---|---|
| `observe` | `…/traces/{id}/comparison`, `…/traces/span-stats`, `…/metrics/summary`, `…/metrics/export.csv`, `…/price-table` and org `/price-table`, Home's `…/overview`; `obs_price_tables`, `obs_trace_comparisons`; the `StepStats` facade |
| `evals` | `…/eval-datasets` (+ cases, import), `…/evaluations`, `…/eval-batches` (+ compare, cancel), `…/eval-results`, `…/evals/capabilities`, `…/eval-gates`; `eval_*` tables; `evals.run_batch`; the `EvalGates` facade |
| `gateway` | `GatewayFacade.call`: one AgentOS call as the person, through the passthrough pipeline |
| frontend | `modules/traces`, `metrics`, `evals`; `SpanWaterfall`, `SpanTree` in `@agnostic/ui`; `costs.ts` in `@agnostic/core` |

Reads on someone's behalf use `GatewayFacade.call`, so user isolation and per-component grants apply. Span
statistics are an instance-wide aggregate read as the control plane after checking `traces:read`.

## Trace comparison

`…/traces/{trace_id}/comparison` flattens the trace's span tree (each span keeps its **name path**), picks a baseline
as the viewer (the newest earlier `OK` trace of the same component, preferring the same version), aligns spans by
name path (repeats become `web_search ×2`), and marks rows `same`, `slower`, `faster` (≥ 250 ms and a quarter of the
baseline), `error`, `new` or `not_run`. The diagnosis names the version and input shape, the most significant changed
leaf (new failures first), and what never ran. Results are cached per (instance, trace, baseline) for
`AGNOSTIC_OBSERVE__COMPARISON_CACHE_DAYS` (7), and the baseline lookup always runs as the viewer first.

## Metrics and cost

AgentOS `/metrics` has daily totals and per-model run counts but no per-component split or per-model tokens; session
list items have both. `…/metrics/summary` combines `/metrics`, the range's sessions (up to
`AGNOSTIC_OBSERVE__MAX_SESSION_PAGES`) and optionally `/traces`.

Cost rules, identical in `agnostic_observe.domain.costs` and `costs.ts`: USD per million tokens per model, instance
rows override org rows; cache-read and reasoning tokens use their rates when set; tokens not tied to a model are
priced at the component's primary model (`≈`); the unexplained **gap** is split by run share and makes the total
approximate. The page recomputes as prices are typed.

## Evaluations

- **Datasets are org-wide**, so environments compare; routes check `evals:read` / `evals:write` on the instance used.
  Cases import from CSV or JSON Lines.
- **A batch** is one component version × one dataset, one AgentOS eval run per case. Starting one checks
  `evals:write` and the component's run scope, snapshots the cases, and queues `evals.run_batch` (queue `evals`).
- **The job** sends cases through the gateway as the starter, `AGNOSTIC_EVALS__CONCURRENCY` (4) at a time; a revoked
  grant stops it, a failing case doesn't. Progress goes out as `evals.batch.progress`.
- **Versions and the judge need agnostic-bridge**: plain `/eval-runs` evaluates only the current version and its
  `model_id` replaces the component's model, so without the bridge drafts answer `409 bridge_required`.
- **Scores**: 0–10 with a pass at 7 for accuracy and numeric judges, pass/fail for binary judges and reliability,
  average run time for performance.
- **Comparison** is case by case: a case regresses when it drops below 7, by 2 or more, or from pass to fail. A
  completed batch with regressions against the previous one publishes `evals.regression`, notifying its starter.

**Publish gates**: a minimum average on a dataset for one component (`evals:gates:write`), judged on the newest
finished batch of exactly the version being published. Studio enforces it, with an audited override for Owners and
Administrators.

Audit actions: `observe.price_table.updated`, `evals.dataset.*`, `evals.batch.started|cancelled`,
`evals.gate.updated|deleted`; eval calls through the gateway are also `gateway.request`.
