// Queue against stubbed APIs: prod-agentos's durable queue with three replicas and a failed support-triage run;
// open the failed job from the Failed tab and resume it from a checkpoint.
import { expect, test, type Page } from "@playwright/test";

import { instances, stubApi } from "./stubs";

const NOW = Date.now();
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();
const QUEUE = /\/api\/v1\/instances\/[^/]+\/queue\//;

const counts = { queued: 5, running: 7, paused: 3, failed: 3, completed: 1186, cancelled: 4 };
const summary = {
  instance_id: instances[0]?.id,
  counts,
  oldest_queued_age_seconds: 3,
  access: "elevated",
  explanation: null,
};
const worker = (index: number, busy: number) => ({
  name: `prod-agentos-${String(index)}`,
  worker_id: `wrk_${String(index)}`,
  heartbeat_at: ago(1),
  slots_busy: busy,
  slots_total: 4,
  deployment: "2026-10-31.2",
  source: "bridge",
});
const overview = {
  summary,
  config: {
    configured: true,
    durable: true,
    db: "PostgresDb",
    table: "agno_jobs",
    max_queue_depth: 1000,
    max_attempts: 2,
    retry_delay_seconds: 30,
    timeout_seconds: 3600,
    lock_grace_seconds: 60,
    stop_timeout_seconds: 30,
    poll_interval: 1.0,
    retention_seconds: 86400,
  },
  workers: [worker(0, 3), worker(1, 4), worker(2, 0)],
  slots_total: 12,
  paused_approvals: 3,
};
const failed = {
  id: "run_5c81e0",
  run_id: "run_5c81e0",
  component_type: "agent",
  component_id: "support-triage",
  session_id: "ses_5c81e0",
  user_id: "zd:50112",
  status: "failed",
  detail: "run ERROR",
  attempt: 2,
  max_attempts: 2,
  idempotency_key: "zd-50112-msg-3",
  locked_by: null,
  deployment: "2026-10-31.2",
  error: "ModelProviderError: claude-opus-5-5 returned 529 (overloaded).",
  created_at: ago(41 * 60),
  updated_at: ago(40 * 60),
  completed_at: ago(40 * 60),
};
const detail = {
  ...failed,
  run_status: "ERROR",
  run_content: null,
  attempts: [
    {
      text: "Accepted · 202 with run_id",
      at: failed.created_at,
      detail: "Idempotency-Key zd-50112-msg-3",
      state: "done",
    },
    {
      text: "Attempt 2 ended in ERROR · job marked failed",
      at: failed.completed_at,
      detail: "max_attempts 2 reached",
      state: "error",
    },
  ],
  checkpoints: [
    {
      number: 1,
      message_index: 3,
      title: "After kb_lookup",
      preview: "kb_lookup: 3 help-center articles",
      role: "tool",
      reason: null,
      created_at: failed.created_at,
      is_latest: false,
    },
    {
      number: 2,
      message_index: 5,
      title: "After zendesk_search",
      preview: "zendesk_search: ticket #50112 and 2 related tickets",
      role: "tool",
      reason: null,
      created_at: failed.created_at,
      is_latest: true,
    },
  ],
  checkpoints_unavailable: null,
  access: "elevated",
};

async function stubQueue(page: Page): Promise<{ resumed: unknown[] }> {
  const state = { resumed: [] as unknown[] };
  let current: Record<string, unknown> = detail;
  await page.route(QUEUE, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/queue\//, "");
    const method = route.request().method();
    if (method === "GET" && path === "summary") return route.fulfill({ json: summary });
    if (method === "GET" && path === "overview") return route.fulfill({ json: overview });
    if (method === "GET" && path === "jobs") {
      const status = url.searchParams.get("status");
      const rows = !status || status === "failed" ? [failed] : [];
      return route.fulfill({
        json: { data: rows, page: 1, limit: 50, total: rows.length, access: "elevated" },
      });
    }
    if (method === "GET" && path === "jobs/run_5c81e0") return route.fulfill({ json: current });
    if (method === "POST" && path === "jobs/run_5c81e0/resume") {
      state.resumed.push(route.request().postDataJSON());
      current = { ...detail, status: "running", run_status: "RUNNING", detail: "prod-agentos-2" };
      return route.fulfill({ json: current });
    }
    return route.fulfill({
      status: 404,
      json: { type: "x", title: "Not stubbed", status: 404, code: "not_found", detail: `${method} ${path}` },
    });
  });
  return state;
}

test("queue: open the failed job and resume it from a checkpoint", async ({ page }) => {
  await stubApi(page);
  const queue = await stubQueue(page);
  await page.goto("/i/prod-agentos/queue");

  await expect(page.getByRole("heading", { name: "Queue", level: 1 })).toBeVisible();
  await expect(page.getByText("Durable · PostgresDb · agno_jobs")).toBeVisible();
  await expect(page.getByRole("img", { name: "4 of 4 slots busy" })).toBeVisible();

  await page.getByRole("tab", { name: /Failed/ }).click();
  await expect(page).toHaveURL(/status=failed/);
  await page.getByRole("table", { name: "Jobs" }).getByRole("link", { name: "run_5c81e0" }).click();

  const aside = page.getByRole("complementary", { name: "Failed job run_5c81e0" });
  await expect(aside.getByText("Attempt 2 ended in ERROR · job marked failed")).toBeVisible();
  await expect(aside.getByRole("radio", { name: /#2 After zendesk_search/ })).toBeChecked();
  await aside.getByText("#1 After kb_lookup").click();
  await aside.getByRole("button", { name: "Resume from #1" }).click();

  await expect.poll(() => queue.resumed).toEqual([{ message_index: 3 }]);
  await expect(page.getByRole("complementary", { name: "Job run_5c81e0" })).toBeVisible();
});
