// Scheduler fixtures from the prototype's sample org: five schedules on prod (daily-brief failing twice, churn-digest
// paused by a person), their run history, cron previews with a daylight-saving note, and MSW handlers for them.
import type {
  AgentOS,
  EndpointCheckOut,
  PreviewOut,
  ScheduleIn,
  ScheduleOut,
  SchedulePatch,
  SchedulerStatusOut,
  ScheduleRunOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { MARCUS, PROD } from "./sample-org";
import { GATEWAY } from "./operate";

const SCHEDULES = `${API}/instances/:instance/schedules`;
const CREATED = "2026-10-18T10:00:00Z";

function run(
  scheduleId: string,
  id: string,
  triggeredAt: string,
  states: string[],
  extra: Partial<ScheduleRunOut> = {},
): ScheduleRunOut {
  const status = states[states.length - 1] ?? "COMPLETED";
  return {
    id,
    schedule_id: scheduleId,
    attempt: 1,
    attempt_label: "first attempt",
    status,
    states,
    status_code: status === "COMPLETED" ? 200 : null,
    run_id: `run_${id}`,
    session_id: `ses_${id}`,
    error: null,
    triggered_at: triggeredAt,
    completed_at: triggeredAt,
    duration_seconds: 40,
    ...extra,
  };
}

const TIMEOUT = "Timed out in web_search after 30 s";

export const sampleScheduleRuns: Record<string, ScheduleRunOut[]> = {
  sch_daily_brief: [
    run("sch_daily_brief", "db5", "2026-11-01T03:05:00Z", ["ERROR"], {
      attempt: 2,
      attempt_label: "retry 1 of 1",
      error: TIMEOUT,
      status_code: 504,
      duration_seconds: 31.2,
    }),
    run("sch_daily_brief", "db4", "2026-11-01T03:00:00Z", ["ERROR"], {
      error: TIMEOUT,
      status_code: 504,
      duration_seconds: 30.8,
    }),
    run("sch_daily_brief", "db3", "2026-10-30T03:00:00Z", ["COMPLETED"], { duration_seconds: 41 }),
    run("sch_daily_brief", "db2", "2026-10-29T03:00:00Z", ["COMPLETED"], { duration_seconds: 38 }),
    run("sch_daily_brief", "db1", "2026-10-28T03:00:00Z", ["COMPLETED"], { duration_seconds: 44 }),
  ],
  sch_kb_sync: [run("sch_kb_sync", "kb1", "2026-11-01T12:00:00Z", ["COMPLETED"], { duration_seconds: 212 })],
  sch_stale_tickets: [
    run("sch_stale_tickets", "st1", "2026-10-30T22:30:00Z", ["COMPLETED"], { duration_seconds: 18.4 }),
  ],
  sch_weekly_usage: [
    run("sch_weekly_usage", "wu3", "2026-10-26T06:30:00Z", ["PAUSED", "COMPLETED"], {
      attempt_label: "paused 32 min for confirmation",
      duration_seconds: 33 * 60,
    }),
    run("sch_weekly_usage", "wu2", "2026-10-19T05:30:00Z", ["PAUSED", "COMPLETED"], {
      attempt_label: "paused 11 min for confirmation",
      duration_seconds: 12 * 60,
    }),
    run("sch_weekly_usage", "wu1", "2026-10-12T05:30:00Z", ["PAUSED", "CANCELLED"], {
      attempt_label: "confirmation not given",
      duration_seconds: null,
    }),
  ],
  sch_churn_digest: [],
};

function schedule(
  id: string,
  name: string,
  values: Partial<ScheduleOut> & Pick<ScheduleOut, "endpoint" | "cron_expr" | "timezone" | "human">,
): ScheduleOut {
  const match = /^\/(agents|teams|workflows)\/([^/]+)\/runs$/.exec(values.endpoint);
  const kinds = { agents: "agent", teams: "team", workflows: "workflow" } as const;
  return {
    id,
    name,
    description: null,
    method: "POST",
    payload: { message: "", stream: false },
    timeout_seconds: 3600,
    max_retries: 0,
    retry_delay_seconds: 60,
    enabled: true,
    next_run_at: null,
    target_kind: match ? kinds[match[1] as keyof typeof kinds] : "custom",
    target_id: match ? (match[2] ?? null) : null,
    disabled_reason: null,
    disabled_note: null,
    user_id: null,
    managed_by: null,
    created_at: CREATED,
    updated_at: CREATED,
    last_runs: (sampleScheduleRuns[id] ?? []).slice(0, 3),
    consecutive_failures: 0,
    ...values,
  };
}

export const sampleSchedules: ScheduleOut[] = [
  schedule("sch_daily_brief", "daily-brief", {
    description: "Morning brief for support leads: overnight volume, escalations, open approvals.",
    endpoint: "/workflows/daily-brief/runs",
    cron_expr: "0 3 * * *",
    timezone: "UTC",
    human: "Every day at 03:00",
    payload: { message: "Write today's brief for the support leads", stream: false },
    timeout_seconds: 900,
    max_retries: 1,
    retry_delay_seconds: 300,
    next_run_at: "2026-11-02T03:00:00Z",
    consecutive_failures: 2,
  }),
  schedule("sch_kb_sync", "kb-sync", {
    description: "Re-reads the help center and refreshes the help_center knowledge base.",
    endpoint: "/agents/kb-researcher/runs",
    cron_expr: "0 */6 * * *",
    timezone: "UTC",
    human: "Every 6 hours, on the hour",
    payload: { message: "Sync help center articles changed since the last run", stream: false },
    timeout_seconds: 1800,
    max_retries: 2,
    retry_delay_seconds: 120,
    next_run_at: "2026-11-01T18:00:00Z",
  }),
  schedule("sch_stale_tickets", "stale-ticket-sweep", {
    description: "Re-routes tickets with no reply in 24 hours during US support hours.",
    endpoint: "/workflows/ticket-router/runs",
    cron_expr: "*/30 8-18 * * 1-5",
    timezone: "America/New_York",
    human: "Every 30 minutes, 08:00–18:59, Monday to Friday",
    payload: { message: "Sweep: tickets idle for more than 24 hours", stream: false },
    timeout_seconds: 600,
    max_retries: 0,
    retry_delay_seconds: 60,
    next_run_at: "2026-11-02T13:00:00Z",
  }),
  schedule("sch_weekly_usage", "weekly-usage-report", {
    description: "Usage by agent and model for finance. Export asks for confirmation.",
    endpoint: "/agents/billing-agent/runs",
    cron_expr: "30 7 * * 1",
    timezone: "Europe/Berlin",
    human: "Every Monday at 07:30",
    payload: { message: "Build last week's usage report and export it to finance", stream: false },
    timeout_seconds: 3600,
    max_retries: 0,
    retry_delay_seconds: 60,
    next_run_at: "2026-11-02T06:30:00Z",
  }),
  schedule("sch_churn_digest", "churn-digest", {
    description: "Friday digest of accounts at risk, from research-team.",
    endpoint: "/teams/research-team/runs",
    cron_expr: "0 9 * * 5",
    timezone: "America/New_York",
    human: "Every Friday at 09:00",
    payload: { message: "Compile this week's churn-risk digest", stream: false },
    timeout_seconds: 1800,
    max_retries: 1,
    retry_delay_seconds: 300,
    enabled: false,
    disabled_note: {
      reason: "Waiting for research-team v3 to be published.",
      by: MARCUS,
      by_name: "Sam Rivera",
      at: "2026-10-30T16:00:00Z",
    },
  }),
];

export const sampleSchedulerStatus: SchedulerStatusOut = {
  instance_id: PROD,
  running: true,
  poll_interval_seconds: 15,
  can_write: true,
  can_delete: true,
  can_custom_endpoint: true,
};

/** Agents, teams and workflows on prod that schedules can target. */
export const sampleScheduleTargets: Record<"agents" | "teams" | "workflows", AgentOS.AgentResponse[]> = {
  agents: [
    { id: "kb-researcher", name: "KB researcher" },
    { id: "billing-agent", name: "Billing agent" },
    { id: "support-triage", name: "Support triage" },
  ],
  teams: [{ id: "research-team", name: "Research team" }],
  workflows: [
    { id: "daily-brief", name: "Daily brief" },
    { id: "ticket-router", name: "Ticket router" },
  ],
};

const DST_NOTE =
  "Daylight saving ends Sun 1 Nov in America/New_York: these runs move from 12:00 to 13:00 UTC.";

const PREVIEWS: Record<string, Omit<PreviewOut, "cron_expr" | "timezone">> = {
  "0 3 * * *|UTC": {
    human: "Every day at 03:00",
    runs: [2, 3, 4, 5, 6].map((day) => ({
      local: `2026-11-0${String(day)}T03:00:00Z`,
      utc: `2026-11-0${String(day)}T03:00:00Z`,
    })),
    notes: [],
  },
  "*/30 8-18 * * 1-5|America/New_York": {
    human: "Every 30 minutes, 08:00–18:59, Monday to Friday",
    runs: ["08:00", "08:30", "09:00", "09:30", "10:00"].map((time) => {
      const [hour = "08", minute = "00"] = time.split(":");
      return {
        local: `2026-11-02T${hour}:${minute}:00-05:00`,
        utc: `2026-11-02T${String(Number(hour) + 5).padStart(2, "0")}:${minute}:00Z`,
      };
    }),
    notes: [DST_NOTE],
  },
};

/** A canned preview for the sample expressions; other expressions get "Every day at HH:MM"-style runs. */
export function sampleSchedulePreview(cron: string, timezone: string): PreviewOut | { fields: string[] } {
  const known = PREVIEWS[`${cron}|${timezone}`];
  if (known) return { cron_expr: cron, timezone, ...known };
  const [minute = "*", hour = "*"] = cron.trim().split(/\s+/);
  const fields: string[] = [];
  if (/^\d+$/.test(minute) && Number(minute) > 59) fields.push("minute");
  if (/^\d+$/.test(hour) && Number(hour) > 23) fields.push("hour");
  if (fields.length > 0) return { fields };
  const sample = sampleSchedules.find((item) => item.cron_expr === cron);
  const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  return {
    cron_expr: cron,
    timezone,
    human: sample?.human ?? (/^\d+$/.test(hour) && /^\d+$/.test(minute) ? `Every day at ${time}` : cron),
    runs: [2, 3, 4, 5, 6].map((day) => ({
      local: `2026-11-0${String(day)}T${/^\d+$/.test(hour) ? time : "00:00"}:00Z`,
      utc: `2026-11-0${String(day)}T${/^\d+$/.test(hour) ? time : "00:00"}:00Z`,
    })),
    notes: [],
  };
}

function problem(status: number, detail: string, extra: Record<string, unknown> = {}) {
  return HttpResponse.json(
    {
      type: "about:blank",
      title: "The request is not valid",
      status,
      code: "validation_failed",
      detail,
      ...extra,
    },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

function notFound() {
  return HttpResponse.json(
    { type: "about:blank", title: "Not found", status: 404, code: "not_found" },
    { status: 404 },
  );
}

/**
 * MSW handlers for `/instances/:instance/schedules…` plus the gateway's component lists. Each call keeps its own
 * copy of the samples, so enabling, disabling, creating, editing and deleting show up in the next list.
 */
export function schedulerHandlers() {
  let rows: ScheduleOut[] = structuredClone(sampleSchedules);
  const find = (id: unknown) => rows.find((item) => item.id === id);
  const save = (next: ScheduleOut) => {
    rows = rows.some((item) => item.id === next.id)
      ? rows.map((item) => (item.id === next.id ? next : item))
      : [...rows, next];
    return HttpResponse.json(next);
  };
  return [
    http.get(`${SCHEDULES}/status`, () => HttpResponse.json(sampleSchedulerStatus)),
    http.post(`${SCHEDULES}/preview`, async ({ request }) => {
      const body = (await request.json()) as { cron_expr: string; timezone?: string };
      const preview = sampleSchedulePreview(body.cron_expr, body.timezone ?? "UTC");
      if ("fields" in preview)
        return problem(422, `Not a valid cron expression: ${preview.fields.join(", ")}.`, preview);
      return HttpResponse.json(preview);
    }),
    http.get(`${SCHEDULES}/endpoint-check`, ({ request }) => {
      const url = new URL(request.url);
      const path = url.searchParams.get("path") ?? "";
      const method = url.searchParams.get("method") ?? "POST";
      const match = /^\/(agents|teams|workflows)\/([^/]+)\/runs$/.exec(path);
      const kinds = { agents: "agent", teams: "team", workflows: "workflow" } as const;
      const result: EndpointCheckOut =
        match && method === "POST"
          ? {
              target_kind: kinds[match[1] as keyof typeof kinds],
              target_id: match[2] ?? null,
              documented: true,
              needs_admin: false,
            }
          : {
              target_kind: "custom",
              target_id: null,
              documented: /^\/(agents|teams|workflows|memories|knowledge)\b/.test(path),
              needs_admin: true,
            };
      return HttpResponse.json(result);
    }),
    http.get(SCHEDULES, () => HttpResponse.json({ data: rows, page: 1, limit: 100, total: rows.length })),
    http.post(SCHEDULES, async ({ request }) => {
      const body = (await request.json()) as ScheduleIn;
      if (!/^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$/.test(body.name))
        return problem(422, "name: String should match pattern", {
          errors: [
            { loc: ["body", "name"], msg: "String should match pattern", type: "string_pattern_mismatch" },
          ],
        });
      const created = schedule(`sch_${body.name.replace(/\W+/g, "_")}`, body.name, {
        description: body.description ?? null,
        method: body.method ?? "POST",
        endpoint: body.endpoint,
        payload: body.payload ?? null,
        cron_expr: body.cron_expr ?? null,
        timezone: body.timezone ?? "UTC",
        human: body.cron_expr
          ? (sampleSchedules.find((item) => item.cron_expr === body.cron_expr)?.human ?? null)
          : null,
        timeout_seconds: body.timeout_seconds ?? 3600,
        max_retries: body.max_retries ?? 0,
        retry_delay_seconds: body.retry_delay_seconds ?? 60,
        last_runs: [],
      });
      rows = [...rows, created];
      return HttpResponse.json(created, { status: 201 });
    }),
    http.get(`${SCHEDULES}/:id/runs`, ({ params }) => {
      const runs = sampleScheduleRuns[String(params.id)];
      if (!runs) return notFound();
      return HttpResponse.json({ data: runs, page: 1, limit: 20, total: runs.length });
    }),
    http.post(`${SCHEDULES}/:id/enable`, ({ params }) => {
      const found = find(params.id);
      return found
        ? save({ ...found, enabled: true, disabled_note: null, next_run_at: "2026-11-06T14:00:00Z" })
        : notFound();
    }),
    http.post(`${SCHEDULES}/:id/disable`, async ({ params, request }) => {
      const found = find(params.id);
      if (!found) return notFound();
      const body = (await request.json()) as { reason?: string | null };
      return save({
        ...found,
        enabled: false,
        next_run_at: null,
        disabled_note: body.reason
          ? { reason: body.reason, by: "usr_daniel", by_name: "Daniel Okafor", at: "2026-11-01T09:00:00Z" }
          : null,
      });
    }),
    http.post(`${SCHEDULES}/:id/trigger`, ({ params }) => {
      const found = find(params.id);
      return found
        ? HttpResponse.json(
            run(found.id, "manual", "2026-11-01T09:00:00Z", ["RUNNING"], {
              completed_at: null,
              duration_seconds: null,
              attempt_label: "triggered by hand",
            }),
          )
        : notFound();
    }),
    http.get(`${SCHEDULES}/:id`, ({ params }) => {
      const found = find(params.id);
      return found ? HttpResponse.json(found) : notFound();
    }),
    http.patch(`${SCHEDULES}/:id`, async ({ params, request }) => {
      const found = find(params.id);
      if (!found) return notFound();
      const body = (await request.json()) as SchedulePatch;
      const patch = Object.fromEntries(Object.entries(body).filter(([, value]) => value !== null));
      return save({ ...found, ...patch });
    }),
    http.delete(`${SCHEDULES}/:id`, ({ params }) => {
      if (!find(params.id)) return notFound();
      rows = rows.filter((item) => item.id !== params.id);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${GATEWAY}/agents`, () => HttpResponse.json(sampleScheduleTargets.agents)),
    http.get(`${GATEWAY}/teams`, () => HttpResponse.json(sampleScheduleTargets.teams)),
    http.get(`${GATEWAY}/workflows`, () => HttpResponse.json(sampleScheduleTargets.workflows)),
  ];
}
