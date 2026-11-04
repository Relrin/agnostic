# Observability

The control plane exports Prometheus metrics, OpenTelemetry traces and JSON logs, and has health endpoints for
orchestrators. These describe Agnostic itself; the agents' own traces and metrics are on the *Traces* and *Metrics*
pages.

## Health

| Endpoint | Answers |
|---|---|
| `GET /healthz` | the process is up (liveness) |
| `GET /readyz` | `ready`, or `degraded` when only the cache is down (still 200: the replica keeps serving); 503 `not_ready` when the database or migrations fail |

## Metrics

`agnostic api` and `agnostic worker` both serve `GET /metrics` on a port of their own, 9464
(`AGNOSTIC_METRICS__PORT`). An ingress routes the API's main port only, so metrics never reach the public side;
protect port 9464 with a network policy that lets only Prometheus in.

| Setting | Default | Notes |
|---|---|---|
| `AGNOSTIC_METRICS__ENABLED` | `true` | |
| `AGNOSTIC_METRICS__PORT` | `9464` | the metrics listener of the API and the worker |
| `AGNOSTIC_METRICS__TOKEN` | — | also serve `/metrics` on the API's main port, to scrapes sending `Authorization: Bearer <token>` |

With the Helm chart, `metrics.serviceMonitor.enabled: true` creates a ServiceMonitor that scrapes port 9464 of the API
and the workers.

| Metric | Type | Labels | What |
|---|---|---|---|
| `agnostic_http_requests_total` | counter | `method`, `route`, `status` | requests, by route template |
| `agnostic_http_request_duration_seconds` | histogram | `method`, `route` | time to the response headers (streams don't count their lifetime) |
| `agnostic_http_requests_in_flight` | gauge | | requests being handled |
| `agnostic_gateway_overhead_seconds` | histogram | `instance` | time the gateway spends before forwarding (policy, scopes, rate limit, token) |
| `agnostic_gateway_upstream_duration_seconds` | histogram | `instance`, `outcome` | AgentOS response time; `outcome` is `ok`, `error` or `unreachable` |
| `agnostic_gateway_denials_total` | counter | `instance`, `reason` | calls refused before AgentOS (`scope_missing`, `rate_limited`) |
| `agnostic_sse_streams` | gauge | `instance` | open server-sent event streams through the gateway |
| `agnostic_jwt_mints_total` | counter | `via` | runtime tokens signed (`gateway`, `direct`, …) |
| `agnostic_cache_lookups_total` | counter | `result` | cache reads, `hit` or `miss` |
| `agnostic_jobs_waiting` | gauge | `queue` | jobs waiting |
| `agnostic_jobs_running` | gauge | `queue` | jobs being worked on |
| `agnostic_jobs_failed` | gauge | `queue` | failed jobs kept for inspection |
| `agnostic_jobs_oldest_wait_seconds` | gauge | `queue` | age of the oldest due job not picked up yet |
| `agnostic_build_info` | gauge | `version` | the running version |

Process, platform and garbage-collector metrics come with them (`process_*`, `python_*`). Job gauges are refreshed
every 15 seconds on the API and every 30 on workers, from the database, so every process reports the same values:
use `max` across them.

### Suggested alerts

```yaml
groups:
  - name: agnostic
    rules:
      - alert: AgnosticGatewayOverhead
        expr: histogram_quantile(0.95, sum by (le) (rate(agnostic_gateway_overhead_seconds_bucket[5m]))) > 0.025
        for: 10m
      - alert: AgnosticJobsLagging
        expr: max by (queue) (agnostic_jobs_oldest_wait_seconds) > 300
        for: 10m
      - alert: AgnosticFailedJobs
        expr: max by (queue) (agnostic_jobs_failed) > 0
        for: 30m
      - alert: AgnosticStreamsNearCapacity
        expr: sum by (pod) (agnostic_sse_streams) > 900
        for: 5m
      - alert: AgnosticCacheHitRatioLow
        expr: sum(rate(agnostic_cache_lookups_total{result="hit"}[15m])) / sum(rate(agnostic_cache_lookups_total[15m])) < 0.5
        for: 30m
      - alert: AgnosticRuntimeErrors
        expr: sum by (instance) (rate(agnostic_gateway_upstream_duration_seconds_count{outcome!="ok"}[5m])) > 1
        for: 10m
```

The targets are a gateway p95 overhead under 25 ms and about 1,000 streams per API replica; the release notes say
where a release stands.

## Traces

Set `AGNOSTIC_OTEL__ENDPOINT` to an OTLP/HTTP collector (`AGNOSTIC_OTEL__HEADERS__<NAME>` for auth headers,
`AGNOSTIC_OTEL__TLS__*` for its CA). Requests, database queries, cache calls and outbound HTTP are traced, and the
W3C `traceparent` header is passed to AgentOS, so runtime traces exported to the same backend line up.

## Logs

JSON lines on stdout (`AGNOSTIC_LOG__FORMAT=json`, the default; `console` for development), level
`AGNOSTIC_LOG__LEVEL`. Every line carries the request id that responses return in `X-Request-Id` and error pages
show. Secrets and tokens are never logged.

## The System page

Owners see versions, endpoint checks, job queues, failed jobs and delivery backlogs in the product: see
[The System page](system-page.md).
