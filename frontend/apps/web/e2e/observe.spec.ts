// Observe flows against stubbed APIs: evaluate support-triage's v4 draft on a 5-case dataset against v3 (through the
// bridge), compare case by case, and see the publish gate block the draft; compare a failed trace with the last good
// run; recompute the Metrics cost from the price table, and read the charts as tables.
import { expect, test, type Page } from "@playwright/test";

import { access, stubApi } from "./stubs";

const API = /\/api\/v1\/instances\/[^/]+/;
const CASES: [string, string][] = [
  ["Charged twice for #4471, refund one", "billing / high; call refund_customer"],
  ["Refund for last year's annual plan?", "billing / normal; explain 30-day policy, no refund call"],
  ["App crashes when I export a report", "technical / high"],
  ["Invoice shows the wrong VAT number", "billing / normal; route to billing-agent"],
  ["Cancel my plan and refund this month", "billing / normal; prorated refund via refund_customer"],
];
const V3 = [10, 9, 10, 9, 6];
const V4 = [10, 3, 4, 9, 10];

function summary(scores: number[]) {
  const avg = scores.reduce((sum, value) => sum + value, 0) / scores.length;
  const below = scores.filter((value) => value < 7).length;
  return {
    runs: 5,
    completed: 5,
    errors: 0,
    avg,
    mean: avg,
    min: Math.min(...scores),
    max: Math.max(...scores),
    std_dev: 1.2,
    passed: 5 - below,
    failed: below,
    pass_ratio: (5 - below) / 5,
    avg_latency_ms: null,
    below_threshold: below,
    gate_value: avg,
  };
}

function batch(id: string, version: number, draft: boolean, scores: number[], status = "completed") {
  return {
    id,
    instance_id: "ins_01M6A0EEZEQ373S26F2014PRD",
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
    status,
    progress: status === "completed" ? 1 : 0,
    started_by: "usr_dana",
    started_by_name: "Daniel Okafor",
    started_at: "2026-11-01T09:12:00Z",
    finished_at: status === "completed" ? "2026-11-01T09:14:00Z" : null,
    summary: status === "completed" ? summary(scores) : null,
    result: status === "completed" ? `${summary(scores).avg.toFixed(2)} avg` : "Queued",
    error: null,
  };
}

function items(prefix: string, scores: number[]) {
  return CASES.map(([input, expected], index) => ({
    id: `${prefix}_${String(index + 1)}`,
    case_id: `evc_${String(index + 1)}`,
    position: index + 1,
    input,
    expected,
    status: "done",
    score: scores[index],
    passed: (scores[index] ?? 0) >= 7,
    reason: `reason ${String(index + 1)}`,
    actual: `answer ${String(index + 1)}`,
    latency_ms: null,
    eval_run_id: null,
    trace_id: null,
    error: null,
  }));
}

function row(source: ReturnType<typeof batch>) {
  return {
    source: "batch",
    id: source.id,
    name: source.name,
    eval_type: source.eval_type,
    component_kind: "agent",
    component_id: "support-triage",
    version_label: source.version_label,
    model: "claude-opus-5-5",
    judge: true,
    result: source.result,
    bad: source.summary ? source.summary.avg < 7.5 : false,
    status: source.status,
    progress: source.progress,
    created_at: source.started_at,
    dataset_name: source.dataset_name,
    case_count: 5,
  };
}

async function stubEvals(page: Page) {
  const v3 = batch("evb_v3", 3, false, V3);
  const v4 = batch("evb_v4", 4, true, V4);
  let started = false;
  let gateOn = false;
  await page.route(/\/api\/v1\/me\/access/, (route) =>
    route.fulfill({
      json: { ...access, control_plane_scopes: [...access.control_plane_scopes, "evals:gates:write"] },
    }),
  );
  await page.route(/\/os\/agents$/, (route) =>
    route.fulfill({
      json: [{ id: "support-triage", name: "Support triage", current_version: 3, is_component: true }],
    }),
  );
  await page.route(/\/os\/teams$/, (route) => route.fulfill({ json: [] }));
  await page.route(/\/os\/components\/support-triage\/configs$/, (route) =>
    route.fulfill({
      json: [
        { component_id: "support-triage", version: 4, stage: "draft", config: {} },
        { component_id: "support-triage", version: 3, stage: "published", config: {} },
      ],
    }),
  );
  await page.route(/\/os\/config$/, (route) =>
    route.fulfill({ json: { available_models: [{ id: "claude-opus-5-5", provider: "anthropic" }] } }),
  );
  await page.route(new RegExp(`${API.source}/evals/capabilities$`), (route) =>
    route.fulfill({ json: { bridge_installed: true, versions: true, reason: null } }),
  );
  await page.route(new RegExp(`${API.source}/eval-datasets`), (route) =>
    route.fulfill({
      json: [
        {
          id: "ds_billing",
          name: "billing-tickets-v2",
          description: "",
          eval_type: "accuracy",
          tags: [],
          version: 1,
          case_count: 5,
          created_by: "usr_dana",
          created_at: "2026-10-20T09:00:00Z",
          updated_at: "2026-10-20T09:00:00Z",
        },
      ],
    }),
  );
  await page.route(new RegExp(`${API.source}/evaluations`), (route) =>
    route.fulfill({ json: { data: started ? [row(v4), row(v3)] : [row(v3)], standalone_unavailable: null } }),
  );
  await page.route(new RegExp(`${API.source}/eval-batches$`), async (route) => {
    const body = route.request().postDataJSON() as { version: number | null; dataset_id: string };
    expect(body).toMatchObject({ version: 4, dataset_id: "ds_billing", component_id: "support-triage" });
    started = true;
    await route.fulfill({ status: 202, json: batch("evb_v4", 4, true, V4, "queued") });
  });
  await page.route(new RegExp(`${API.source}/eval-batches/evb_v4$`), (route) =>
    route.fulfill({ json: { batch: v4, items: items("v4", V4), baseline: v3 } }),
  );
  await page.route(new RegExp(`${API.source}/eval-batches/evb_v4/compare`), (route) =>
    route.fulfill({
      json: {
        before: v3,
        after: v4,
        rows: items("v4", V4).map((after, index) => ({
          case_id: after.case_id,
          position: after.position,
          input: after.input,
          expected: after.expected,
          before: items("v3", V3)[index],
          after,
          change: index === 1 || index === 2 ? "regression" : index === 4 ? "fix" : "same",
        })),
        counts: { regressions: 2, fixes: 1, below_before: 1, below_after: 2 },
        insight: "v4 draft fixes case 5 but regresses cases 2 and 3 (9 → 3, 10 → 4) compared with v3.",
        generated: false,
      },
    }),
  );
  const gate = () => ({
    id: "gate_1",
    component_kind: "agent",
    component_id: "support-triage",
    dataset_id: "ds_billing",
    dataset_name: "billing-tickets-v2",
    eval_type: "accuracy",
    min_average: 8.5,
    enabled: gateOn,
    updated_by: "usr_dana",
    updated_at: "2026-11-01T09:20:00Z",
    latest: { batch_id: "evb_v4", version_label: "v4 draft", value: 7.2 },
    state: gateOn ? "would_block" : "off",
    consequence: gateOn
      ? "v4 draft (7.20) would be blocked from publishing."
      : "Off: Publish ignores this eval.",
  });
  await page.route(new RegExp(`${API.source}/eval-gates`), async (route) => {
    if (route.request().method() === "PUT") {
      gateOn = (route.request().postDataJSON() as { enabled: boolean }).enabled;
      await route.fulfill({ json: gate() });
      return;
    }
    await route.fulfill({ json: gateOn ? [gate()] : [] });
  });
}

test("evals: v4 draft regresses two of five cases against v3, and the gate would block it", async ({
  page,
}) => {
  await stubApi(page);
  await stubEvals(page);
  await page.goto("/i/prod-agentos/evals");

  await page.getByRole("button", { name: "Run evaluation" }).click();
  const panel = page.getByRole("region", { name: "New evaluation" });
  await panel.getByLabel("Version").click();
  await page.getByRole("option", { name: "v4 draft" }).click();
  await expect(panel.getByText("5 runs of the draft")).toBeVisible();
  await panel.getByRole("button", { name: "Run evaluation" }).click();

  const stats = page.getByRole("table", { name: "Score statistics" });
  await expect(stats.getByText("v3", { exact: true })).toBeVisible();
  await expect(page.getByText("Showing 5 of 5 · v3 → v4 draft · below 7: 1 → 2")).toBeVisible();
  const cases = page.getByRole("table", { name: "Cases" });
  await expect(cases.getByText("9 → 3")).toBeVisible();
  await expect(cases.getByText("10 → 4")).toBeVisible();
  await expect(page.getByText(/regresses cases 2 and 3/)).toBeVisible();

  const gate = page.getByRole("switch", { name: "Gate publish on this eval" });
  await expect(gate).toHaveAttribute("aria-checked", "false");
  await gate.click();
  await expect(page.getByText("v4 draft (7.20) would be blocked from publishing.")).toBeVisible();
  await expect(gate).toHaveAttribute("aria-checked", "true");
});

const at = (seconds: number) => new Date(Date.parse("2026-11-01T03:00:02Z") + seconds * 1000).toISOString();
const span = (
  id: string,
  type: string,
  start: number,
  seconds: number,
  extra: Record<string, unknown> = {},
) => ({
  id,
  name: id.split("@")[0],
  type,
  duration: `${String(seconds)}s`,
  start_time: at(start),
  end_time: at(start + seconds),
  status: "OK",
  ...extra,
});
const TRACE = {
  trace_id: "tr_9c1e7d40",
  name: "daily-brief.run",
  status: "ERROR",
  duration: "64.00s",
  start_time: at(0),
  end_time: at(64),
  total_spans: 4,
  error_count: 2,
  run_id: "run_d3b18a",
  session_id: "ses_6f12bd09",
  user_id: "sa:scheduler",
  workflow_id: "daily-brief",
  created_at: at(0),
  tree: [
    span("daily-brief.run@0", "WORKFLOW", 0, 64, {
      status: "ERROR",
      spans: [
        span("Gather news@0.1", "WORKFLOW", 0.1, 63.8, {
          status: "ERROR",
          step_type: "Step",
          spans: [
            span("web_search@1.7", "TOOL", 1.7, 30, {
              status: "ERROR",
              error: "TimeoutError: web_search exceeded the 30 s tool timeout",
            }),
            span("web_search@33.1", "TOOL", 33.1, 30, { status: "ERROR", error: "TimeoutError: again" }),
          ],
        }),
      ],
    }),
  ],
};

test("traces: a failed run compared with the last successful one", async ({ page }) => {
  await stubApi(page);
  await page.route(/\/os\/agents$|\/os\/teams$|\/os\/workflows$/, (route) => route.fulfill({ json: [] }));
  await page.route(/\/os\/traces\/filter-schema$/, (route) =>
    route.fulfill({ status: 404, json: { detail: "x" } }),
  );
  await page.route(/\/os\/traces\/search$/, (route) =>
    route.fulfill({ json: { data: [TRACE], meta: { page: 1, limit: 20, total_count: 1 } } }),
  );
  await page.route(/\/os\/traces\/tr_9c1e7d40$/, (route) => route.fulfill({ json: TRACE }));
  await page.route(new RegExp(`${API.source}/traces/span-stats`), (route) =>
    route.fulfill({
      json: {
        window: "24h",
        generated_at: at(0),
        traces_scanned: 1,
        sampled: false,
        cached: false,
        stats: [],
      },
    }),
  );
  await page.route(new RegExp(`${API.source}/traces/tr_9c1e7d40/comparison$`), (route) =>
    route.fulfill({
      json: {
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
            path: ["daily-brief.run", "Gather news", "web_search"],
            name: "web_search",
            depth: 2,
            kind: "tool",
            state: "error",
            baseline: { count: 1, total_ms: 4_100, mean_ms: 4_100, max_ms: 4_100, errors: 0 },
            current: { count: 2, total_ms: 60_000, mean_ms: 30_000, max_ms: 30_000, errors: 2 },
            delta_ms: 55_900,
          },
          {
            path: ["daily-brief.run", "Write brief"],
            name: "Write brief",
            depth: 1,
            kind: "step",
            state: "not_run",
            baseline: { count: 1, total_ms: 15_600, mean_ms: 15_600, max_ms: 15_600, errors: 0 },
            current: null,
            delta_ms: null,
          },
        ],
        ghosts: [{ span_id: "web_search@1.7", start_ms: 1_600, duration_ms: 4_100 }],
        diagnosis:
          "Same version, same input shape. The only change is `web_search`, which now fails with TimeoutError (30 s ×2 instead of 4.1 s), so the workflow never reached `Write brief`.",
        generated: false,
        cached: false,
      },
    }),
  );
  await page.goto("/i/prod-agentos/traces/tr_9c1e7d40");
  await expect(page.getByRole("heading", { name: /daily-brief\.run/ })).toBeVisible();
  await page.getByRole("button", { name: "Compare with last successful run" }).click();
  await expect(page.getByText(/so the workflow never reached `Write brief`/)).toBeVisible();
  await expect(
    page.getByRole("table", { name: /compared with the last successful run/ }).getByText("not run"),
  ).toBeVisible();
  await expect(page).toHaveURL(/compare=true/);
});

test("metrics: the estimate follows the price table, and charts read as tables", async ({ page }) => {
  await stubApi(page);
  const tokens = (input: number, output: number) => ({
    input,
    output,
    cache_read: 0,
    reasoning: 0,
    total: input + output,
  });
  await page.route(new RegExp(`${API.source}/metrics/summary`), (route) =>
    route.fulfill({
      json: {
        instance_id: "ins_01M6A0EEZEQ373S26F2014PRD",
        start: "2026-10-25",
        end: "2026-10-31",
        generated_at: at(0),
        last_aggregated_at: at(0),
        totals: {
          runs: { agent: 2_908, team: 288, workflow: 1_716, total: 4_912 },
          sessions: 1_284,
          runs_per_session: 3.8,
          active_users: 312,
          tokens: tokens(5_200_000, 1_100_000),
        },
        days: [
          {
            date: "2026-10-30",
            runs: { agent: 485, team: 48, workflow: 287, total: 820 },
            tokens: tokens(2_000_000, 990_000),
          },
          {
            date: "2026-10-31",
            runs: { agent: 401, team: 41, workflow: 237, total: 679 },
            tokens: tokens(2_000_000, 470_000),
          },
        ],
        model_usage: [{ model_id: "claude-opus-5-5", provider: "anthropic", runs: 2_849, share: 1 }],
        components: [
          {
            id: "support-triage",
            type: "agent",
            sessions: 520,
            runs: 1_840,
            tokens: tokens(5_200_000, 1_100_000),
            models: [
              { model_id: "claude-opus-5-5", provider: "anthropic", tokens: tokens(5_200_000, 1_100_000) },
            ],
            unattributed: tokens(0, 0),
            extra_models: 0,
            estimated_cost: 53.5,
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
            updated_at: at(0),
            updated_by: "usr_dana",
          },
        ],
        cost: { currency: "USD", total: 53.5, approximate: false, gap: 0, unpriced_models: [] },
        sampled: false,
        unavailable: {},
      },
    }),
  );
  await page.route(new RegExp(`${API.source}/price-table$`), (route) =>
    route.fulfill({ json: { prices: [] } }),
  );
  await page.goto("/i/prod-agentos/metrics");
  const totals = page.getByRole("region", { name: "Totals" });
  await expect(totals.getByText("$53.50")).toBeVisible();
  const input = page.getByRole("spinbutton", { name: "claude-opus-5-5 input price" });
  await input.fill("10");
  await expect(totals.getByText("$79.50")).toBeVisible();

  await page.getByRole("button", { name: "View as table" }).first().click();
  await expect(
    page.getByRole("table", { name: /Runs per day by component type/ }).getByText("Fri"),
  ).toBeVisible();
});
