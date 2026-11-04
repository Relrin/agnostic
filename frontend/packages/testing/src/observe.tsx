// Observe fixtures from the prototype's sample org: the daily-brief trace that timed out, the Metrics page numbers,
// and the support-triage v3 vs v4 draft evaluation; plus MSW handlers for them.
import type {
  AgentOS,
  BatchComparisonOut,
  BatchDetailOut,
  BatchOut,
  DatasetOut,
  EvalCapabilitiesOut,
  EvaluationsOut,
  GateOut,
  ItemOut,
  MetricsSummaryOut,
  SpanStatsOut,
  TraceComparisonOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { PROD } from "./sample-org";
import { GATEWAY } from "./operate";

const T0 = Date.parse("2026-11-01T03:00:02Z");
const at = (seconds: number) => new Date(T0 + seconds * 1000).toISOString();

function node(
  id: string,
  type: string,
  start: number,
  seconds: number,
  extra: Partial<AgentOS.TraceNode> = {},
): AgentOS.TraceNode {
  return {
    id,
    name: id.split("@")[0] ?? id,
    type,
    duration: `${seconds.toFixed(2)}s`,
    start_time: at(start),
    end_time: at(start + seconds),
    status: "OK",
    ...extra,
  };
}

export const sampleTraceDetail = {
  trace_id: "tr_9c1e7d40",
  name: "daily-brief.run",
  status: "ERROR",
  duration: "64.00s",
  start_time: at(0),
  end_time: at(64),
  total_spans: 7,
  error_count: 2,
  run_id: "run_d3b18a",
  session_id: "ses_6f12bd09",
  user_id: "sa:scheduler",
  workflow_id: "daily-brief",
  created_at: at(0),
  tree: [
    node("daily-brief.run@0", "WORKFLOW", 0, 64, {
      status: "ERROR",
      metadata: { total_input_tokens: 10_516, total_output_tokens: 1_888 },
      spans: [
        node("Gather news@0.1", "WORKFLOW", 0.1, 63.8, {
          status: "ERROR",
          step_type: "Step",
          spans: [
            node("news-scout.run@0.1", "AGENT", 0.1, 63.7, {
              status: "ERROR",
              spans: [
                node("chat.completion@0.2", "LLM", 0.2, 1.4, {
                  metadata: { model: "claude-haiku-5-5", input_tokens: 10_516, output_tokens: 1_888 },
                }),
                node("web_search@1.7", "TOOL", 1.7, 30, {
                  status: "ERROR",
                  input: '{"query": "agent platform news Oct 31 2026", "max_results": 8}',
                  error: "TimeoutError: web_search exceeded the 30 s tool timeout",
                }),
                node("chat.completion@31.8", "LLM", 31.8, 1.2),
                node("web_search@33.1", "TOOL", 33.1, 30, {
                  status: "ERROR",
                  error: "TimeoutError: web_search exceeded the 30 s tool timeout",
                }),
              ],
            }),
          ],
        }),
      ],
    }),
  ],
} as unknown as AgentOS.TraceDetail;

export const sampleTraceSearch = {
  data: [
    sampleTraceDetail,
    {
      trace_id: "tr_77aa01",
      name: "support-triage.run",
      status: "OK",
      duration: "1.20s",
      start_time: "2026-11-01T10:45:00Z",
      end_time: "2026-11-01T10:45:01.200Z",
      total_spans: 6,
      error_count: 0,
      user_id: "cust_8812",
      agent_id: "support-triage",
      created_at: "2026-11-01T10:45:00Z",
    },
  ],
  meta: { page: 1, limit: 20, total_pages: 1, total_count: 2 },
};

const group = (count: number, mean: number, errors = 0) => ({
  count,
  total_ms: count * mean,
  mean_ms: mean,
  max_ms: mean,
  errors,
});

export const sampleTraceComparison: TraceComparisonOut = {
  trace_id: "tr_9c1e7d40",
  baseline: {
    trace_id: "tr_51ab0e93",
    name: "daily-brief.run",
    start_time: "2026-10-31T03:00:02Z",
    duration_ms: 22_800,
    version: 3,
  },
  reason: null,
  same_version: true,
  same_input_shape: true,
  current_duration_ms: 64_000,
  rows: [
    {
      path: ["daily-brief.run"],
      name: "daily-brief.run",
      depth: 0,
      kind: "workflow",
      state: "error",
      baseline: group(1, 22_800),
      current: group(1, 64_000, 1),
      delta_ms: 41_200,
    },
    {
      path: ["daily-brief.run", "Gather news", "news-scout.run", "chat.completion"],
      name: "chat.completion",
      depth: 3,
      kind: "model",
      state: "same",
      baseline: group(2, 1_250),
      current: group(2, 1_300),
      delta_ms: 100,
    },
    {
      path: ["daily-brief.run", "Gather news", "news-scout.run", "web_search"],
      name: "web_search",
      depth: 3,
      kind: "tool",
      state: "error",
      baseline: group(1, 4_100),
      current: group(2, 30_000, 2),
      delta_ms: 55_900,
    },
    {
      path: ["daily-brief.run", "Write brief"],
      name: "Write brief",
      depth: 1,
      kind: "step",
      state: "not_run",
      baseline: group(1, 15_600),
      current: null,
      delta_ms: null,
    },
  ],
  ghosts: [
    { span_id: "web_search@1.7", start_ms: 1_600, duration_ms: 4_100 },
    { span_id: "chat.completion@0.2", start_ms: 200, duration_ms: 1_300 },
  ],
  diagnosis:
    "Same version, same input shape. The only change is `web_search`, which now fails with TimeoutError (30.0 s ×2 instead of 4.1 s), so the workflow never reached `Write brief`.",
  generated: false,
  cached: false,
};

export const sampleSpanStats: SpanStatsOut = {
  window: "7d",
  generated_at: "2026-11-01T10:00:00Z",
  traces_scanned: 100,
  sampled: true,
  cached: false,
  stats: [
    { name: "research-team.run", kind: "team", avg_duration_ms: 31_840, count: 288, errors: 0 },
    { name: "web_search", kind: "tool", avg_duration_ms: 6_420, count: 212, errors: 9 },
    { name: "chat.completion", kind: "model", avg_duration_ms: 1_380, count: 9_904, errors: 0 },
  ],
};

const tokens = (input: number, output: number, cache_read = 0, reasoning = 0) => ({
  input,
  output,
  cache_read,
  reasoning,
  total: input + output,
});
const DAYS = [
  "2026-10-25",
  "2026-10-26",
  "2026-10-27",
  "2026-10-28",
  "2026-10-29",
  "2026-10-30",
  "2026-10-31",
];
const AGENT = [367, 325, 424, 442, 464, 485, 401];
const TEAM = [36, 31, 42, 44, 46, 48, 41];
const WORKFLOW = [216, 191, 250, 261, 274, 287, 237];
const TOKENS = [2.26, 2.0, 2.61, 2.72, 2.86, 2.99, 2.47];

export const sampleMetricsSummary: MetricsSummaryOut = {
  instance_id: PROD,
  start: "2026-10-25",
  end: "2026-10-31",
  generated_at: "2026-11-01T10:00:00Z",
  last_aggregated_at: "2026-11-01T09:42:00Z",
  totals: {
    runs: { agent: 2_908, team: 288, workflow: 1_716, total: 4_912 },
    sessions: 1_284,
    runs_per_session: 3.8,
    active_users: 312,
    tokens: tokens(14_600_000, 3_300_000, 5_100_000, 300_000),
  },
  days: DAYS.map((date, index) => ({
    date,
    runs: {
      agent: AGENT[index] ?? 0,
      team: TEAM[index] ?? 0,
      workflow: WORKFLOW[index] ?? 0,
      total: (AGENT[index] ?? 0) + (TEAM[index] ?? 0) + (WORKFLOW[index] ?? 0),
    },
    tokens: tokens(Math.round((TOKENS[index] ?? 0) * 800_000), Math.round((TOKENS[index] ?? 0) * 200_000)),
  })),
  model_usage: [
    { model_id: "claude-opus-5-5", provider: "anthropic", runs: 2_849, share: 0.58 },
    { model_id: "claude-haiku-5-5", provider: "anthropic", runs: 1_326, share: 0.27 },
    { model_id: "gpt-6.1-sol", provider: "openai", runs: 737, share: 0.15 },
  ],
  components: [
    {
      id: "support-triage",
      type: "agent",
      sessions: 520,
      runs: 1_840,
      tokens: tokens(5_200_000, 1_100_000),
      models: [{ model_id: "claude-opus-5-5", provider: "anthropic", tokens: tokens(5_200_000, 1_100_000) }],
      unattributed: tokens(0, 0),
      extra_models: 0,
      estimated_cost: 53.5,
      approximate: false,
    },
    {
      id: "ticket-router",
      type: "workflow",
      sessions: 470,
      runs: 1_702,
      tokens: tokens(3_900_000, 900_000),
      models: [
        { model_id: "claude-haiku-5-5", provider: "anthropic", tokens: tokens(3_000_000, 700_000) },
        { model_id: "gpt-6.1-sol", provider: "openai", tokens: tokens(500_000, 100_000) },
        { model_id: "claude-opus-5-5", provider: "anthropic", tokens: tokens(400_000, 100_000) },
      ],
      unattributed: tokens(0, 0),
      extra_models: 2,
      estimated_cost: 11.1,
      approximate: false,
    },
  ],
  gap_tokens: tokens(0, 0),
  prices: [
    {
      model_id: "claude-opus-5-5",
      provider: "anthropic",
      input_per_1m: 5,
      output_per_1m: 25,
      cache_read_per_1m: null,
      reasoning_per_1m: null,
      currency: "USD",
      source: "instance",
      updated_at: "2026-11-01T09:00:00Z",
      updated_by: "usr_dana",
    },
    {
      model_id: "claude-haiku-5-5",
      provider: "anthropic",
      input_per_1m: 1,
      output_per_1m: 5,
      cache_read_per_1m: null,
      reasoning_per_1m: null,
      currency: "USD",
      source: "org",
      updated_at: "2026-11-01T09:00:00Z",
      updated_by: "usr_dana",
    },
  ],
  cost: { currency: "USD", total: 64.6, approximate: false, gap: 0, unpriced_models: ["gpt-6.1-sol"] },
  sampled: false,
  unavailable: {},
};

const CASES: [string, string][] = [
  ["Charged twice for #4471, refund one", "billing / high; call refund_customer"],
  ["Refund for last year's annual plan?", "billing / normal; explain 30-day policy, no refund call"],
  ["App crashes when I export a report", "technical / high"],
  ["Invoice shows the wrong VAT number", "billing / normal; route to billing-agent"],
  ["Cancel my plan and refund this month", "billing / normal; prorated refund via refund_customer"],
];
const V3 = [10, 9, 10, 9, 6];
const V4 = [10, 3, 4, 9, 10];
const REASONS_V4 = [
  "Category, urgency and action match.",
  "Refund is outside the 30-day window; it should have explained the policy.",
  "Read “report” as an invoice report; wrong category and urgency.",
  "Correct; did not mention routing.",
  "Correct action through the tool.",
];

function items(batch: string, scores: number[]): ItemOut[] {
  return CASES.map(([input, expected], index) => ({
    id: `${batch}_${String(index + 1)}`,
    case_id: `evc_${String(index + 1)}`,
    position: index + 1,
    input,
    expected,
    status: "done",
    score: scores[index] ?? null,
    passed: (scores[index] ?? 0) >= 7,
    reason: REASONS_V4[index] ?? null,
    actual: `answer ${String(index + 1)}`,
    latency_ms: null,
    eval_run_id: `eval_${batch}_${String(index + 1)}`,
    trace_id: null,
    error: null,
  }));
}

function summary(scores: number[]) {
  const avg = scores.reduce((sum, value) => sum + value, 0) / scores.length;
  return {
    runs: scores.length,
    completed: scores.length,
    errors: 0,
    avg,
    mean: avg,
    min: Math.min(...scores),
    max: Math.max(...scores),
    std_dev: 1.2,
    passed: scores.filter((value) => value >= 7).length,
    failed: scores.filter((value) => value < 7).length,
    pass_ratio: scores.filter((value) => value >= 7).length / scores.length,
    avg_latency_ms: null,
    below_threshold: scores.filter((value) => value < 7).length,
    gate_value: avg,
  };
}

function batch(id: string, version: number, draft: boolean, scores: number[], startedAt: string): BatchOut {
  return {
    id,
    instance_id: PROD,
    name: "support-triage accuracy",
    dataset_id: "ds_billing",
    dataset_name: "billing-tickets-v2",
    case_count: 5,
    eval_type: "accuracy",
    component_kind: "agent",
    component_id: "support-triage",
    version,
    draft,
    version_label: draft ? `v${String(version)} draft` : `v${String(version)}`,
    judge: { model_id: "claude-opus-5-5", provider: "anthropic" },
    via_bridge: true,
    params: {},
    status: "completed",
    progress: 1,
    started_by: "usr_priya",
    started_by_name: "Priya Nair",
    started_at: startedAt,
    finished_at: startedAt,
    summary: summary(scores),
    result: `${(scores.reduce((sum, value) => sum + value, 0) / scores.length).toFixed(2)} avg`,
    error: null,
  };
}

export const sampleBatchV3 = batch("evb_v3", 3, false, V3, "2026-10-20T09:12:00Z");
export const sampleBatchV4 = batch("evb_v4", 4, true, V4, "2026-11-01T09:12:00Z");

export const sampleBatchDetail: BatchDetailOut = {
  batch: sampleBatchV4,
  items: items("v4", V4),
  baseline: sampleBatchV3,
};

export const sampleBatchComparison: BatchComparisonOut = {
  before: sampleBatchV3,
  after: sampleBatchV4,
  rows: items("v4", V4).map((after, index) => ({
    case_id: after.case_id,
    position: after.position,
    input: after.input,
    expected: after.expected,
    before: items("v3", V3)[index] ?? null,
    after,
    change: index === 1 || index === 2 ? "regression" : index === 4 ? "fix" : "same",
  })),
  counts: { regressions: 2, fixes: 1, below_before: 1, below_after: 2 },
  insight: "v4 draft fixes case 5 but regresses cases 2 and 3 (9 → 3, 10 → 4) compared with v3.",
  generated: false,
};

export const sampleEvaluations: EvaluationsOut = {
  data: [
    {
      source: "batch",
      id: "evb_v4",
      name: "support-triage accuracy",
      eval_type: "accuracy",
      component_kind: "agent",
      component_id: "support-triage",
      version_label: "v4 draft",
      model: "claude-opus-5-5",
      judge: true,
      result: "7.20 avg",
      bad: true,
      status: "completed",
      progress: 1,
      created_at: "2026-11-01T09:12:00Z",
      dataset_name: "billing-tickets-v2",
      case_count: 5,
    },
    {
      source: "agentos",
      id: "eval_cli",
      name: "billing tool calls",
      eval_type: "reliability",
      component_kind: "agent",
      component_id: "billing-agent",
      version_label: null,
      model: "claude-opus-5-5",
      judge: false,
      result: "Failed",
      bad: true,
      status: "completed",
      progress: 1,
      created_at: "2026-10-26T09:00:00Z",
      dataset_name: null,
      case_count: null,
    },
  ],
  standalone_unavailable: null,
};

export const sampleGate: GateOut = {
  id: "gate_1",
  component_kind: "agent",
  component_id: "support-triage",
  dataset_id: "ds_billing",
  dataset_name: "billing-tickets-v2",
  eval_type: "accuracy",
  min_average: 8.5,
  enabled: true,
  updated_by: "usr_dana",
  updated_at: "2026-11-01T09:20:00Z",
  latest: { batch_id: "evb_v4", version_label: "v4 draft", value: 7.2 },
  state: "would_block",
  consequence: "v4 draft (7.20) would be blocked from publishing.",
};

export const sampleDatasets: DatasetOut[] = [
  {
    id: "ds_billing",
    name: "billing-tickets-v2",
    description: "",
    eval_type: "accuracy",
    tags: [],
    version: 3,
    case_count: 5,
    created_by: "usr_priya",
    created_at: "2026-10-20T09:00:00Z",
    updated_at: "2026-10-20T09:00:00Z",
  },
];

export const sampleEvalCapabilities: EvalCapabilitiesOut = {
  bridge_installed: true,
  versions: true,
  reason: null,
};

export function observeHandlers() {
  return [
    http.post(`${GATEWAY}/traces/search`, () => HttpResponse.json(sampleTraceSearch)),
    http.get(`${GATEWAY}/traces/filter-schema`, () =>
      HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
    ),
    http.get(`${GATEWAY}/traces/:trace`, ({ params }) =>
      params.trace === sampleTraceDetail.trace_id
        ? HttpResponse.json(sampleTraceDetail)
        : HttpResponse.json({ detail: "Trace not found" }, { status: 404 }),
    ),
    http.get(`${API}/instances/:instance/traces/span-stats`, () => HttpResponse.json(sampleSpanStats)),
    http.get(`${API}/instances/:instance/traces/:trace/comparison`, () =>
      HttpResponse.json(sampleTraceComparison),
    ),
    http.get(`${API}/instances/:instance/metrics/summary`, () => HttpResponse.json(sampleMetricsSummary)),
    http.put(`${API}/instances/:instance/price-table`, async ({ request }) =>
      HttpResponse.json(await request.json()),
    ),
    http.get(`${GATEWAY}/metrics/refresh/status`, () =>
      HttpResponse.json({ status: "completed", finished_at: new Date().toISOString() }),
    ),
    http.post(`${GATEWAY}/metrics/refresh`, () => HttpResponse.json({ status: "accepted" }, { status: 202 })),
    http.get(`${API}/instances/:instance/evaluations`, () => HttpResponse.json(sampleEvaluations)),
    http.get(`${API}/instances/:instance/eval-batches/:batch`, () => HttpResponse.json(sampleBatchDetail)),
    http.get(`${API}/instances/:instance/eval-batches/:batch/compare`, () =>
      HttpResponse.json(sampleBatchComparison),
    ),
    http.get(`${API}/instances/:instance/eval-gates`, () => HttpResponse.json([sampleGate])),
    http.put(`${API}/instances/:instance/eval-gates`, async ({ request }) => {
      const body = (await request.json()) as { enabled: boolean; min_average: number };
      return HttpResponse.json({
        ...sampleGate,
        enabled: body.enabled,
        min_average: body.min_average,
        state: body.enabled ? "would_block" : "off",
        consequence: body.enabled ? sampleGate.consequence : "Off: Publish ignores this eval.",
      });
    }),
    http.get(`${API}/instances/:instance/eval-datasets`, () => HttpResponse.json(sampleDatasets)),
    http.get(`${API}/instances/:instance/evals/capabilities`, () =>
      HttpResponse.json(sampleEvalCapabilities),
    ),
    http.post(`${API}/instances/:instance/eval-batches`, () =>
      HttpResponse.json(sampleBatchV4, { status: 202 }),
    ),
    http.get(`${GATEWAY}/config`, () =>
      HttpResponse.json({ available_models: [{ id: "claude-opus-5-5", provider: "anthropic" }] }),
    ),
  ];
}
