// Operate fixtures: a Home overview, AgentOS sessions/runs/approvals behind the gateway, search hits, and MSW handlers.
import type { AgentOS, DecideOut, OverviewOut, SearchOut } from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { PROD } from "./sample-org";

export const GATEWAY = `${API}/instances/:instance/os`;

export const sampleOverview: OverviewOut = {
  instance_id: PROD,
  range: "7d",
  start: "2026-10-25T12:00:00Z",
  end: "2026-11-01T12:00:00Z",
  generated_at: "2026-11-01T12:00:00Z",
  cached: false,
  sampled: false,
  counts: { agents: 6, teams: 3, workflows: 5 },
  kpis: {
    runs: { value: 4912, previous: 4386, delta: 526, delta_pct: 12 },
    sessions: { value: 1284, previous: 1211, delta: 73, delta_pct: 6 },
    error_rate: { value: 0.018, previous: 0.014, delta: 0.004, delta_pct: 28.6 },
    failed_runs: { value: 88, previous: 61, delta: 27, delta_pct: 44 },
    p95_latency_ms: { value: 6400, previous: 7200, delta: -800, delta_pct: -11 },
  },
  runs_per_day: [
    { date: "2026-10-31", completed: 601, failed: 9 },
    { date: "2026-11-01", completed: 410, failed: 4 },
  ],
  model_usage: [{ model_id: "gpt-5.2-mini", runs: 3920, share: 0.8 }],
  primitives: [
    {
      id: "support-triage",
      type: "agent",
      name: "Support triage",
      live_version: 3,
      draft_version: 4,
      runs: 1200,
      errors: 70,
      error_rate: 0.058,
      last_run_at: "2026-11-01T11:58:00Z",
    },
  ],
  pending_approvals: 3,
  attention: [
    {
      key: "approval_backlog",
      kind: "approval_backlog",
      severity: "warning",
      title: "3 approvals waiting",
      detail: "`refund_customer` on billing-agent · oldest 2h 14m",
      action: { label: "Review", target: "approvals?tool=refund_customer" },
    },
    {
      key: "schedule_failing:sch_1",
      kind: "schedule_failing",
      severity: "danger",
      title: "daily-brief failed twice",
      detail: "Timeout in `web_search` after 30 s · 03:00 UTC",
      action: { label: "Open trace", target: "traces?run_id=run_b" },
    },
  ],
  activity: [
    {
      id: "evt_1",
      occurred_at: "2026-11-01T10:00:00Z",
      actor: { kind: "user", id: "usr_maya", display: "Maya Chen" },
      action: "approvals.decided",
      summary: "Maya Chen approved refund_customer on billing-agent",
      resource_display: "refund_customer",
      links: null,
    },
  ],
  unavailable: {},
};

export const sampleAgents: AgentOS.AgentResponse[] = [
  { id: "support-triage", name: "Support triage", current_version: 3, is_component: false },
  { id: "billing-agent", name: "Billing agent", is_component: false },
];

export const sampleSessions: AgentOS.SessionSchema[] = [
  {
    session_id: "ses_7f3a91c2",
    session_name: "Refund for order 4471",
    session_state: { status: "paused" },
    user_id: "cust_8812",
    agent_id: "support-triage",
    total_tokens: 2106,
    created_at: "2026-11-01T10:41:00Z",
    updated_at: "2026-11-01T10:44:00Z",
  },
  {
    session_id: "ses_1b2c3d4e",
    session_name: "Where is my order?",
    session_state: {},
    user_id: "dana@northwind.dev",
    agent_id: "support-triage",
    total_tokens: 980,
    created_at: "2026-10-30T09:00:00Z",
    updated_at: "2026-10-30T09:05:00Z",
  },
];

export const samplePausedRun: AgentOS.RunSchema = {
  run_id: "run_9f2c41",
  agent_id: "support-triage",
  status: "PAUSED",
  run_input: "Please refund 49 for cus_8812",
  content: "",
  tools: [
    {
      tool_call_id: "call_refund",
      tool_name: "refund_customer",
      tool_args: { customer_id: "cus_8812", amount: 49, reason: "requested in chat" },
      requires_confirmation: true,
    },
  ],
  created_at: "2026-11-01T10:42:00Z",
};

export const samplePendingApproval: AgentOS.ApprovalResponse = {
  id: "apr_1",
  run_id: "run_9f2c41",
  session_id: "ses_7f3a91c2",
  status: "pending",
  source_type: "agent",
  agent_id: "support-triage",
  user_id: "cust_8812",
  tool_name: "refund_customer",
  tool_args: { customer_id: "cus_8812", amount: 49, reason: "requested in chat" },
  created_at: 1_793_529_720,
};

export const sampleSearch: SearchOut = {
  data: [
    {
      kind: "agent",
      ref: "support-triage",
      instance_id: PROD,
      title: "Support triage",
      subtitle: "support-triage prod-agentos",
      url_path: "/i/prod-agentos/chat/agents/support-triage",
      score: 1,
    },
  ],
};

function page<T>(items: readonly T[]) {
  return { data: items, meta: { page: 1, limit: 20, total_pages: 1, total_count: items.length } };
}

export function operateHandlers() {
  return [
    http.get(`${API}/instances/:instance/overview`, () => HttpResponse.json(sampleOverview)),
    http.get(`${API}/instances/:instance/approvals/count`, () =>
      HttpResponse.json({ instance_id: PROD, count: 3, available: true }),
    ),
    http.post(`${API}/instances/:instance/approvals/:approval/decide`, async ({ request, params }) => {
      const body = (await request.json()) as {
        decision: "approve" | "reject";
        edited_args?: Record<string, unknown>;
      };
      const result: DecideOut = {
        approval_id: String(params.approval),
        instance_id: PROD,
        decision: body.decision,
        status: body.decision === "approve" ? "approved" : "rejected",
        run_id: "run_9f2c41",
        session_id: "ses_7f3a91c2",
        continue_state: "continued",
        continue_detail: null,
        already_resolved: false,
        args_changed: body.edited_args ? ["amount"] : [],
      };
      return HttpResponse.json(result);
    }),
    http.get(`${API}/search`, () => HttpResponse.json(sampleSearch)),
    http.get(`${GATEWAY}/agents`, () => HttpResponse.json(sampleAgents)),
    http.get(`${GATEWAY}/teams`, () => HttpResponse.json([])),
    http.get(`${GATEWAY}/workflows`, () => HttpResponse.json([])),
    http.get(`${GATEWAY}/sessions`, () => HttpResponse.json(page(sampleSessions))),
    http.get(`${GATEWAY}/sessions/:session`, ({ params }) => {
      const found = sampleSessions.find((item) => item.session_id === params.session);
      return found
        ? HttpResponse.json({
            ...found,
            session_summary: { summary: "Customer asked for a refund.", topics: ["refund"] },
          })
        : HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }),
    http.get(`${GATEWAY}/sessions/:session/runs`, () => HttpResponse.json([samplePausedRun])),
    http.get(`${GATEWAY}/approvals`, () => HttpResponse.json(page([samplePendingApproval]))),
  ];
}
