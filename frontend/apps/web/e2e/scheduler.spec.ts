// Scheduler flows against stubbed APIs: daily-brief failing twice (the banner), the five sample schedules with their
// timing in each schedule's own timezone, stale-ticket-sweep's next runs with a daylight-saving note, and turning
// kb-sync off with a reason. Each test keeps a full-page screenshot in its output folder.
import { expect, test, type Page, type Route } from "@playwright/test";

import { instances, stubApi } from "./stubs";

const SCHEDULES = /\/api\/v1\/instances\/[^/]+\/schedules(\/.*)?(\?.*)?$/;
const CREATED = "2026-10-18T10:00:00Z";

type Row = Record<string, unknown> & { id: string; name: string; enabled: boolean };

function run(id: string, at: string, states: string[], extra: Record<string, unknown> = {}) {
  return {
    id,
    schedule_id: "x",
    attempt: 1,
    attempt_label: "first attempt",
    status: states[states.length - 1],
    states,
    status_code: 200,
    run_id: `run_${id}`,
    session_id: `ses_${id}`,
    error: null,
    triggered_at: at,
    completed_at: at,
    duration_seconds: 40,
    ...extra,
  };
}

const TIMEOUT = "Timed out in web_search after 30 s";
const DAILY_RUNS = [
  run("db5", "2026-11-01T03:05:00Z", ["ERROR"], {
    attempt: 2,
    attempt_label: "retry 1 of 1",
    error: TIMEOUT,
    duration_seconds: 31.2,
  }),
  run("db4", "2026-11-01T03:00:00Z", ["ERROR"], { error: TIMEOUT, duration_seconds: 30.8 }),
  run("db3", "2026-10-30T03:00:00Z", ["COMPLETED"], { duration_seconds: 41 }),
];

function schedule(
  id: string,
  name: string,
  kind: string,
  target: string,
  values: Record<string, unknown>,
): Row {
  const family = { agent: "agents", team: "teams", workflow: "workflows" }[kind] ?? "agents";
  return {
    id,
    name,
    description: null,
    method: "POST",
    endpoint: `/${family}/${target}/runs`,
    payload: { message: "", stream: false },
    timeout_seconds: 3600,
    max_retries: 0,
    retry_delay_seconds: 60,
    enabled: true,
    next_run_at: null,
    target_kind: kind,
    target_id: target,
    disabled_reason: null,
    disabled_note: null,
    user_id: null,
    managed_by: null,
    created_at: CREATED,
    updated_at: CREATED,
    last_runs: [run(`${id}_1`, "2026-11-01T12:00:00Z", ["COMPLETED"])],
    consecutive_failures: 0,
    ...values,
  };
}

function samples(): Row[] {
  return [
    schedule("sch_daily_brief", "daily-brief", "workflow", "daily-brief", {
      description: "Morning brief for support leads: overnight volume, escalations, open approvals.",
      cron_expr: "0 3 * * *",
      timezone: "UTC",
      human: "Every day at 03:00",
      timeout_seconds: 900,
      max_retries: 1,
      retry_delay_seconds: 300,
      next_run_at: "2026-11-02T03:00:00Z",
      last_runs: DAILY_RUNS,
      consecutive_failures: 2,
    }),
    schedule("sch_kb_sync", "kb-sync", "agent", "kb-researcher", {
      description: "Re-reads the help center and refreshes the help_center knowledge base.",
      cron_expr: "0 */6 * * *",
      timezone: "UTC",
      human: "Every 6 hours, on the hour",
      next_run_at: "2026-11-01T18:00:00Z",
    }),
    schedule("sch_stale_tickets", "stale-ticket-sweep", "workflow", "ticket-router", {
      description: "Re-routes tickets with no reply in 24 hours during US support hours.",
      cron_expr: "*/30 8-18 * * 1-5",
      timezone: "America/New_York",
      human: "Every 30 minutes, 08:00–18:59, Monday to Friday",
      next_run_at: "2026-11-02T13:00:00Z",
    }),
    schedule("sch_weekly_usage", "weekly-usage-report", "agent", "billing-agent", {
      cron_expr: "30 7 * * 1",
      timezone: "Europe/Berlin",
      human: "Every Monday at 07:30",
      next_run_at: "2026-11-02T06:30:00Z",
    }),
    schedule("sch_churn_digest", "churn-digest", "team", "research-team", {
      cron_expr: "0 9 * * 5",
      timezone: "America/New_York",
      human: "Every Friday at 09:00",
      enabled: false,
      last_runs: [],
      disabled_note: {
        reason: "Waiting for research-team v3 to be published.",
        by: "usr_sam",
        by_name: "Sam Rivera",
        at: "2026-10-30T16:00:00Z",
      },
    }),
  ];
}

function preview(cron: string, timezone: string) {
  if (cron === "*/30 8-18 * * 1-5")
    return {
      cron_expr: cron,
      timezone,
      human: "Every 30 minutes, 08:00–18:59, Monday to Friday",
      runs: ["08:00", "08:30", "09:00", "09:30", "10:00"].map((time) => {
        const [hour = "08", minute = "00"] = time.split(":");
        return {
          local: `2026-11-02T${hour}:${minute}:00-05:00`,
          utc: `2026-11-02T${String(Number(hour) + 5).padStart(2, "0")}:${minute}:00Z`,
        };
      }),
      notes: ["Daylight saving ends Sun 1 Nov in America/New_York: these runs move from 12:00 to 13:00 UTC."],
    };
  return {
    cron_expr: cron,
    timezone,
    human: "Every day at 03:00",
    runs: [2, 3, 4, 5, 6].map((day) => ({
      local: `2026-11-0${String(day)}T03:00:00Z`,
      utc: `2026-11-0${String(day)}T03:00:00Z`,
    })),
    notes: [],
  };
}

type Scheduler = { disabled: { id: string; body: unknown }[] };

async function stubScheduler(page: Page): Promise<Scheduler> {
  const state: Scheduler = { disabled: [] };
  let rows = samples();
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(SCHEDULES, async (route) => {
    const request = route.request();
    const method = request.method();
    const path = new URL(request.url()).pathname.replace(/^.*\/schedules/, "");
    if (method === "GET" && path === "/status")
      return json(route, {
        instance_id: instances[0]?.id,
        running: true,
        poll_interval_seconds: 15,
        can_write: true,
        can_delete: true,
        can_custom_endpoint: true,
      });
    if (method === "GET" && path === "")
      return json(route, { data: rows, page: 1, limit: 100, total: rows.length });
    if (method === "POST" && path === "/preview") {
      const body = request.postDataJSON() as { cron_expr: string; timezone: string };
      return json(route, preview(body.cron_expr, body.timezone));
    }
    const runs = /^\/([^/]+)\/runs$/.exec(path);
    if (method === "GET" && runs) {
      const found = rows.find((row) => row.id === runs[1]);
      const items = found?.id === "sch_daily_brief" ? DAILY_RUNS : (found?.last_runs ?? []);
      return json(route, { data: items, page: 1, limit: 20, total: (items as unknown[]).length });
    }
    const toggle = /^\/([^/]+)\/(enable|disable)$/.exec(path);
    if (method === "POST" && toggle) {
      const [, id = "", action] = toggle;
      const body: unknown = action === "disable" ? request.postDataJSON() : null;
      if (action === "disable") state.disabled.push({ id, body });
      const reason = (body as { reason?: string | null } | null)?.reason;
      rows = rows.map((row) =>
        row.id === id
          ? {
              ...row,
              enabled: action === "enable",
              next_run_at: null,
              disabled_note: reason
                ? { reason, by: "usr_dana", by_name: "Daniel Okafor", at: "2026-11-01T09:00:00Z" }
                : null,
            }
          : row,
      );
      return json(
        route,
        rows.find((row) => row.id === id),
      );
    }
    return json(route, { type: "x", title: "Not found", status: 404, code: "not_found" }, 404);
  });
  return state;
}

async function shoot(target: Page, name: string) {
  await target.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("shows the failing schedule, every schedule's timing and the next runs with a DST note", async ({
  page,
}) => {
  await stubApi(page);
  await stubScheduler(page);
  await page.goto("/i/prod-agentos/scheduler");

  await expect(page.getByRole("heading", { name: "Scheduler", level: 1 })).toBeVisible();
  await expect(page.getByText("Scheduler running · polls every 15 s")).toBeVisible();
  const banner = page.getByRole("alert").filter({ hasText: "daily-brief failed twice" });
  await expect(banner).toContainText("Timed out in web_search after 30 s. The schedule is still enabled.");
  await expect(banner.getByRole("link", { name: "Open trace" })).toHaveAttribute(
    "href",
    "/i/prod-agentos/traces?run_id=run_db5",
  );

  const table = page.getByRole("table", { name: "Schedules" });
  await expect(table.getByRole("row")).toHaveCount(6);
  await expect(table.getByText("ERROR ×2")).toBeVisible();
  await expect(table.getByText("*/30 8-18 * * 1-5 · America/New_York")).toBeVisible();
  await expect(table.getByRole("switch", { name: "Enable churn-digest" })).toHaveAttribute(
    "aria-checked",
    "false",
  );

  await table.getByRole("button", { name: "stale-ticket-sweep" }).click();
  await expect(page).toHaveURL(/schedule=sch_stale_tickets/);
  const aside = page.getByRole("complementary", { name: "Schedule details" });
  await expect(aside.getByRole("heading", { name: "stale-ticket-sweep" })).toBeVisible();
  const next = aside.getByRole("group", { name: "Next runs" });
  await expect(next.getByRole("listitem").first()).toContainText("Mon 2 Nov 2026 · 08:00");
  await expect(next.getByRole("listitem").first()).toContainText("13:00 UTC");
  await expect(
    aside.getByText(
      "Daylight saving ends Sun 1 Nov in America/New_York: these runs move from 12:00 to 13:00 UTC.",
    ),
  ).toBeVisible();
  await shoot(page, "scheduler");
});

test("turns a schedule off with a reason", async ({ page }) => {
  await stubApi(page);
  const scheduler = await stubScheduler(page);
  await page.goto("/i/prod-agentos/scheduler");

  const toggle = page.getByRole("switch", { name: "Enable kb-sync" });
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await toggle.click();
  const dialog = page.getByRole("dialog", { name: "Disable kb-sync?" });
  await dialog.getByRole("textbox", { name: "Reason" }).fill("Help center migration this week");
  await dialog.getByRole("button", { name: "Disable" }).click();

  await expect(toggle).toHaveAttribute("aria-checked", "false");
  expect(scheduler.disabled).toEqual([
    { id: "sch_kb_sync", body: { reason: "Help center migration this week" } },
  ]);
  await expect(page.getByText("Disabled kb-sync")).toBeVisible();

  await page.getByRole("button", { name: "kb-sync", exact: true }).click();
  const aside = page.getByRole("complementary", { name: "Schedule details" });
  await expect(aside.getByText(/Paused by Daniel Okafor: Help center migration this week/)).toBeVisible();
  await shoot(page, "scheduler-disabled");
});
