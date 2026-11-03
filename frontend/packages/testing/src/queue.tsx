// Queue fixtures from the prototype's sample org: prod-agentos with three replicas, a failed support-triage run with
// two checkpoints, paused billing runs waiting on approvals; plus MSW handlers for /queue/*.
import type {
  QueueJobDetailOut,
  QueueJobOut,
  QueueOverviewOut,
  QueueSummaryOut,
  QueueWorkerOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { PROD } from "./p01";

const NOW = Date.now();
const secondsAgo = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();
const minutesAgo = (minutes: number) => secondsAgo(minutes * 60);

export const sampleQueueConfig = {
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
};

export const sampleQueueSummary: QueueSummaryOut = {
  instance_id: PROD,
  counts: { queued: 5, running: 7, paused: 3, failed: 3, completed: 1186, cancelled: 4 },
  oldest_queued_age_seconds: 3,
  access: "elevated",
  explanation: null,
};

export const sampleQueueSummaryCountsOnly: QueueSummaryOut = {
  ...sampleQueueSummary,
  access: null,
  explanation:
    "The queue is admin-only in AgentOS. Operators (queue:operate) reach it through the control plane; ask an " +
    "Owner for Operator or Instance admin on this instance.",
};

function worker(index: number, busy: number, heartbeat: number): QueueWorkerOut {
  return {
    name: `prod-agentos-${String(index)}`,
    worker_id: `wrk_prod_${String(index)}`,
    heartbeat_at: secondsAgo(heartbeat),
    slots_busy: busy,
    slots_total: 4,
    deployment: "2026-10-31.2",
    source: "bridge",
  };
}

export const sampleQueueWorkers: QueueWorkerOut[] = [worker(0, 3, 1), worker(1, 4, 2), worker(2, 0, 1)];

export const sampleQueueOverview: QueueOverviewOut = {
  summary: sampleQueueSummary,
  config: sampleQueueConfig,
  workers: sampleQueueWorkers,
  slots_total: 12,
  paused_approvals: 3,
};

function job(
  id: string,
  kind: "agent" | "team" | "workflow",
  component: string,
  status: string,
  detail: string | null,
  attempt: number,
  ageSeconds: number,
  key: string,
  extra: Partial<QueueJobOut> = {},
): QueueJobOut {
  return {
    id,
    run_id: id,
    component_type: kind,
    component_id: component,
    session_id: `ses_${id.slice(4)}`,
    user_id: "zd:50112",
    status,
    detail,
    attempt,
    max_attempts: 2,
    idempotency_key: key,
    locked_by: status === "running" ? detail : null,
    deployment: "2026-10-31.2",
    error: null,
    created_at: secondsAgo(ageSeconds),
    updated_at: secondsAgo(Math.max(ageSeconds - 60, 0)),
    completed_at: null,
    ...extra,
  };
}

const FAILED = job(
  "run_5c81e0",
  "agent",
  "support-triage",
  "failed",
  "run ERROR",
  2,
  41 * 60,
  "zd-50112-msg-3",
  {
    error:
      "ModelProviderError: claude-opus-5-5 returned 529 (overloaded).\n" +
      "Model retries exhausted (retries=2) on attempt 2 of 2.",
    completed_at: minutesAgo(40),
  },
);

export const sampleQueueJobs: QueueJobOut[] = [
  job("run_7d23b4", "agent", "support-triage", "queued", "not claimed", 0, 2, "zd-50294-msg-1"),
  job("run_7d23a9", "workflow", "ticket-router", "queued", "not claimed", 0, 3, "zd-50293-msg-1"),
  job("run_7d22f8", "workflow", "ticket-router", "running", "prod-agentos-0", 1, 4, "zd-50288-msg-2"),
  job("run_7d22c1", "agent", "support-triage", "running", "prod-agentos-1", 1, 6, "zd-50291-msg-1"),
  job("run_7d1f55", "agent", "support-triage", "completed", "2.6 s", 1, 60, "zd-50279-msg-2"),
  job("run_4b19d0", "agent", "billing-agent", "paused", "approval apv_7Kr9", 1, 38 * 60, "zd-50277-msg-1"),
  FAILED,
  job("run_e5a3b7", "team", "escalation-team", "paused", "approval apv_7Kp4", 1, 65 * 60, "zd-47703-msg-5"),
  job("run_9f2c41", "agent", "billing-agent", "paused", "approval apv_7Kq2", 1, 134 * 60, "zd-48121-msg-2"),
  job("run_6f0a12", "agent", "billing-agent", "cancelled", "by Omar Haddad", 1, 180 * 60, "zd-49870-msg-4", {
    deployment: "2026-10-31.1",
  }),
  job(
    "run_d81f2a",
    "workflow",
    "daily-brief",
    "failed",
    "run ERROR",
    2,
    14 * 3600,
    "sched:daily-brief:03:05Z",
  ),
  job(
    "run_c47e90",
    "workflow",
    "daily-brief",
    "failed",
    "run ERROR",
    2,
    14 * 3600 + 300,
    "sched:daily-brief:03:00Z",
  ),
];

export const sampleQueueJobDetail: QueueJobDetailOut = {
  ...FAILED,
  run_status: "ERROR",
  run_content: null,
  attempts: [
    {
      text: "Accepted · 202 with run_id",
      at: FAILED.created_at,
      detail: "Idempotency-Key zd-50112-msg-3",
      state: "done",
    },
    {
      text: "Attempt 1 was retried",
      at: null,
      detail: "restarted from the beginning · retry_delay_seconds 30",
      state: "error",
    },
    { text: "Attempt 2 claimed by prod-agentos-0", at: minutesAgo(40.5), detail: null, state: "done" },
    {
      text: "Attempt 2 ended in ERROR · job marked failed",
      at: minutesAgo(40),
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
      reason: "tool_result",
      created_at: minutesAgo(41),
      is_latest: false,
    },
    {
      number: 2,
      message_index: 5,
      title: "After zendesk_search",
      preview: "zendesk_search: ticket #50112 and 2 related tickets",
      role: "tool",
      reason: "tool_result",
      created_at: minutesAgo(41),
      is_latest: true,
    },
  ],
  checkpoints_unavailable: null,
  access: "elevated",
};

/** The detail of any sample job: the failed support-triage run in full, the others with a short narrative. */
export function sampleQueueDetail(id: string): QueueJobDetailOut | undefined {
  if (id === sampleQueueJobDetail.id) return sampleQueueJobDetail;
  const found = sampleQueueJobs.find((item) => item.id === id);
  if (!found) return undefined;
  const workflow = found.component_type === "workflow";
  return {
    ...found,
    run_status: found.status === "failed" ? "ERROR" : found.status.toUpperCase(),
    run_content: null,
    attempts: [{ text: "Accepted · 202 with run_id", at: found.created_at, detail: null, state: "done" }],
    checkpoints: [],
    checkpoints_unavailable: workflow
      ? "Workflows don't keep message checkpoints: requeue the job or continue its paused step."
      : null,
    access: "elevated",
  };
}

const notFound = (id: string) =>
  HttpResponse.json(
    {
      type: "x",
      title: "Not found",
      status: 404,
      code: "not_found",
      detail: `There is no queued job ${id}.`,
    },
    { status: 404 },
  );

export const queueRequiresAdmin = {
  type: "x",
  title: "The queue needs queue:operate or Instance admin",
  status: 403,
  code: "queue_requires_admin",
  detail: sampleQueueSummaryCountsOnly.explanation,
};

/** Handlers over the sample jobs; recovery actions change the job for the rest of the test. */
export function queueHandlers() {
  const base = `${API}/instances/:instance/queue`;
  const changed = new Map<string, QueueJobDetailOut>();
  const current = (id: string) => changed.get(id) ?? sampleQueueDetail(id);
  const act = (id: string, patch: (detail: QueueJobDetailOut) => Partial<QueueJobDetailOut>) => {
    const detail = current(id);
    if (!detail) return notFound(id);
    const next = { ...detail, ...patch(detail) };
    changed.set(id, next);
    return HttpResponse.json(next);
  };
  return [
    http.get(`${base}/summary`, () => HttpResponse.json(sampleQueueSummary)),
    http.get(`${base}/overview`, () => HttpResponse.json(sampleQueueOverview)),
    http.get(`${base}/workers`, () => HttpResponse.json(sampleQueueWorkers)),
    http.get(`${base}/jobs`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      const status = params.get("status");
      const rows = status ? sampleQueueJobs.filter((item) => item.status === status) : sampleQueueJobs;
      const counts = sampleQueueSummary.counts;
      const total = status
        ? (counts[status] ?? rows.length)
        : Object.values(counts).reduce((sum, value) => sum + value, 0);
      return HttpResponse.json({
        data: rows,
        page: Number(params.get("page") ?? 1),
        limit: Number(params.get("limit") ?? 50),
        total,
        access: "elevated",
      });
    }),
    http.get(`${base}/jobs/:job`, ({ params }) => {
      const detail = current(String(params.job));
      return detail ? HttpResponse.json(detail) : notFound(String(params.job));
    }),
    http.post(`${base}/jobs/:job/resume`, ({ params }) =>
      act(String(params.job), () => ({ status: "running", detail: "prod-agentos-2", run_status: "RUNNING" })),
    ),
    http.post(`${base}/jobs/:job/requeue`, ({ params }) =>
      act(String(params.job), (detail) => ({
        status: "queued",
        detail: "not claimed",
        max_attempts: detail.max_attempts + 1,
      })),
    ),
    http.post(`${base}/jobs/:job/cancel`, ({ params }) =>
      act(String(params.job), () => ({ status: "cancelled", detail: null, run_status: "CANCELLED" })),
    ),
  ];
}

/** Someone who may see the instance but not operate its queue: counts and the reason, 403 for the rest. */
export function queueCountsOnlyHandlers() {
  const base = `${API}/instances/:instance/queue`;
  const refused = () => HttpResponse.json(queueRequiresAdmin, { status: 403 });
  return [
    http.get(`${base}/summary`, () => HttpResponse.json(sampleQueueSummaryCountsOnly)),
    http.get(`${base}/overview`, refused),
    http.get(`${base}/workers`, refused),
    http.get(`${base}/jobs`, refused),
    http.get(`${base}/jobs/:job`, refused),
  ];
}
