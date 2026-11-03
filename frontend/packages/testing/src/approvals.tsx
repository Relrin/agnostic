// Approvals fixtures from the prototype's sample org: three refunds and credits waiting on prod, resolved and expired
// history, routing rules, the expiry policy and the "Notify me in Slack" preference; plus MSW handlers for them.
import type {
  ApprovalCountsOut,
  ApprovalDetailOut,
  ApprovalOut,
  ApprovalsPageOut,
  ChannelOut,
  DecideOut,
  PolicyOut,
  PreferencesOut,
  RouteIn,
  RouteOut,
  TimelineEntryOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";
import { DANIEL, MARCUS, PROD, sampleMembers, sampleRoles } from "./p01";

const NOW = Date.now();
const MINUTE = 60_000;
const ago = (minutes: number) => new Date(NOW - minutes * MINUTE).toISOString();
const DAY = 24 * 60;

function approval(
  fields: Partial<ApprovalOut> & Pick<ApprovalOut, "id" | "tool_name" | "created_at">,
): ApprovalOut {
  return {
    agentos_status: "pending",
    args_changed: [],
    component_id: "billing-agent",
    component_kind: "agent",
    expires_at: null,
    expiry_enforced: false,
    expiry_source: null,
    note: null,
    resolved_at: null,
    resolved_by: null,
    resolved_by_name: null,
    run_id: null,
    schedule_id: null,
    session_id: null,
    source_id: "billing-agent",
    source_kind: "agent",
    source_name: "billing-agent",
    status: "pending",
    type: "blocking",
    user_id: null,
    user_name: null,
    via: "sa:zendesk-bridge",
    ...fields,
  };
}

/** Expiry 24 h after the request, as the instance's TTL sets it. */
const expiresAfter = (minutesAgo: number) => ago(minutesAgo - DAY);

export const sampleApprovals: ApprovalOut[] = [
  approval({
    id: "apv_7Kq2",
    tool_name: "refund_customer",
    created_at: ago(134),
    expires_at: expiresAfter(134),
    expiry_source: "ttl",
    user_id: "zd:48121",
    session_id: "ses_4471a",
    run_id: "run_4471a",
  }),
  approval({
    id: "apv_7Kp4",
    tool_name: "apply_account_credit",
    created_at: ago(65),
    expires_at: expiresAfter(65),
    expiry_source: "ttl",
    component_id: "escalation-team",
    component_kind: "team",
    source_id: "escalation-team",
    source_kind: "team",
    source_name: "escalation-team",
    user_id: "zd:47703",
    session_id: "ses_2210c",
    run_id: "run_2210c",
  }),
  approval({
    id: "apv_7Kr9",
    tool_name: "refund_customer",
    created_at: ago(38),
    expires_at: expiresAfter(38),
    expiry_source: "ttl",
    user_id: "zd:50277",
    session_id: "ses_4519f",
    run_id: "run_4519f",
  }),
  approval({
    id: "apv_7Jz1",
    tool_name: "refund_customer",
    status: "approved",
    agentos_status: "approved",
    created_at: ago(220),
    resolved_at: ago(120),
    resolved_by: MARCUS,
    resolved_by_name: "Maya Chen",
    user_id: "zd:46310",
    session_id: "ses_2291b",
    run_id: "run_2291b",
  }),
  approval({
    id: "apv_7Jt6",
    tool_name: "export_usage_report",
    type: "audit",
    status: "approved",
    agentos_status: "approved",
    created_at: ago(5 * DAY),
    resolved_at: ago(5 * DAY - 2),
    resolved_by: "usr_jonas",
    resolved_by_name: "Jonas Weber",
    component_id: "usage-reporter",
    source_id: "weekly-usage-report",
    source_kind: "schedule",
    source_name: "weekly-usage-report",
    schedule_id: "sch_weekly_usage",
    user_id: "jonas@northwind.dev",
    via: "scheduler",
    session_id: "ses_9c01e",
    run_id: "run_9c01e",
  }),
  approval({
    id: "apv_7Hk3",
    tool_name: "refund_customer",
    status: "rejected",
    agentos_status: "rejected",
    created_at: ago(DAY + 30),
    resolved_at: ago(DAY),
    resolved_by: "usr_omar",
    resolved_by_name: "Omar Haddad",
    note: "Outside the 30-day refund window.",
    user_id: "zd:44871",
    session_id: "ses_3870a",
    run_id: "run_3870a",
  }),
  approval({
    id: "apv_7Gd8",
    tool_name: "apply_account_credit",
    status: "expired",
    agentos_status: "rejected",
    created_at: ago(4 * DAY),
    expires_at: ago(3 * DAY),
    expiry_source: "ttl",
    expiry_enforced: true,
    component_id: "escalation-team",
    component_kind: "team",
    source_id: "escalation-team",
    source_kind: "team",
    source_name: "escalation-team",
    user_id: "zd:43020",
    session_id: "ses_1987d",
    run_id: "run_1987d",
  }),
];

export const sampleApprovalCounts: ApprovalCountsOut = {
  pending: 3,
  approved: 41,
  rejected: 6,
  expired: 2,
  cancelled: 0,
  truncated: false,
};

const TOOL_ARGS: Record<string, Record<string, unknown>> = {
  apv_7Kq2: {
    order_id: "4471",
    charge_id: "ch_3PqL9w",
    amount: 49,
    currency: "USD",
    reason: "duplicate_charge",
  },
  apv_7Kp4: { account_id: "acct_2210", amount: 25, currency: "USD", reason: "sla_breach" },
  apv_7Kr9: {
    order_id: "4519",
    charge_id: "ch_3PrA2k",
    amount: 129,
    currency: "USD",
    reason: "damaged_item",
  },
  apv_7Jz1: {
    order_id: "4402",
    charge_id: "ch_3PnX7d",
    amount: 49,
    currency: "USD",
    reason: "returned_item",
  },
  apv_7Jt6: { period: "2026-10-19/2026-10-25", format: "csv", destination: "finance-share" },
  apv_7Hk3: {
    order_id: "3870",
    charge_id: "ch_3NcK1p",
    amount: 96,
    currency: "USD",
    reason: "customer_request",
  },
  apv_7Gd8: { account_id: "acct_1987", amount: 40, currency: "USD", reason: "outage" },
};

const CONTEXT: Record<string, ApprovalDetailOut["context"]> = {
  apv_7Kq2: {
    user_message: "My card was charged twice for order #4471. Can you refund one of them?",
    agent_message: "Found two identical $49.00 charges on order #4471. Refunding the duplicate charge.",
  },
};

function entry(
  text: string,
  at: string | null,
  state: TimelineEntryOut["state"],
  detail: string | null = null,
) {
  return { text, at, state, detail };
}

function timelineOf(row: ApprovalOut): TimelineEntryOut[] {
  const paused = entry(
    `Run paused at ${row.tool_name ?? "a tool"} · run_status PAUSED`,
    row.created_at,
    "done",
  );
  const routed = entry(
    "Routed to Support AI and Billing ops",
    row.created_at,
    "done",
    "Slack + control plane",
  );
  switch (row.status) {
    case "pending":
      return [
        paused,
        routed,
        entry("Viewed by Maya Chen", ago(110), "done"),
        entry("Waiting for a decision", row.expires_at, "now", "Expires"),
      ];
    case "approved":
      return [
        paused,
        entry(`Approved by ${row.resolved_by_name ?? "someone"}`, row.resolved_at, "done"),
        entry("Run continued and completed in 1.9 s", row.resolved_at, "end"),
      ];
    case "rejected":
      return [
        paused,
        entry(`Rejected by ${row.resolved_by_name ?? "someone"}`, row.resolved_at, "done", row.note),
        entry("The agent told the customer and offered a credit instead", row.resolved_at, "end"),
      ];
    default:
      return [paused, entry("Expired without a decision", row.expires_at, "end")];
  }
}

export function sampleApprovalDetail(id: string): ApprovalDetailOut | undefined {
  const row = sampleApprovals.find((item) => item.id === id);
  if (!row) return undefined;
  const pending = row.status === "pending";
  return {
    ...row,
    tool_args: TOOL_ARGS[id] ?? {},
    resolution_data: {},
    requirements: [],
    context: CONTEXT[id] ?? { user_message: null, agent_message: null },
    timeline: timelineOf(row),
    routed_to: ["Support AI", "Billing ops"],
    channels: ["slack", "in_app"],
    views: [{ user_id: MARCUS, name: "Maya Chen", at: ago(110) }],
    can_resolve: pending && row.type === "blocking",
    cannot_resolve_reason: pending && row.type === "audit" ? "Audit approvals never block the run." : null,
    run_status: pending ? "PAUSED" : "COMPLETED",
    user_isolation: false,
    elevation_enabled: true,
    policy: sampleApprovalPolicy,
  };
}

export const sampleApprovalPolicy: PolicyOut = {
  instance_id: PROD,
  enforce_expiry: true,
  ttl_hours: 24,
  updated_at: null,
  updated_by: null,
};

const operator = sampleRoles.find((role) => role.slug === "operator");

export const sampleRoutes: RouteOut[] = [
  {
    id: "rte_billing",
    instance_id: PROD,
    name: "Billing ops",
    tool_name: "refund_customer",
    component_kind: "agent",
    component_ids: ["billing-agent"],
    members: [{ id: DANIEL, name: "Daniel Okafor" }],
    roles: operator ? [{ id: operator.id, name: operator.name }] : [],
    channels: ["in_app", "slack"],
    channel_ids: ["chn_ops"],
    created_by: DANIEL,
    updated_at: ago(3 * DAY),
  },
  {
    id: "rte_org_all",
    instance_id: null,
    name: "Support AI",
    tool_name: null,
    component_kind: null,
    component_ids: [],
    members: [{ id: MARCUS, name: "Marcus Chen" }],
    roles: [],
    channels: ["in_app"],
    channel_ids: [],
    created_by: DANIEL,
    updated_at: ago(10 * DAY),
  },
];

export const sampleApprovalChannels: ChannelOut[] = [
  {
    id: "chn_ops",
    kind: "slack",
    name: "#support-approvals",
    enabled: true,
    events: [],
    instance_ids: [],
    config: {},
    recent: [],
    sends_direct_messages: true,
    created_at: ago(30 * DAY),
    updated_at: ago(30 * DAY),
  },
];

export function sampleApprovalPreferences(slack: boolean, slackAvailable = true): PreferencesOut {
  return {
    slack_available: slackAvailable,
    quiet_hours: null,
    events: [
      {
        event: {
          name: "approval.created",
          label: "Approval requested",
          description: "A run paused for an approval routed to you.",
          defaults: ["in_app"],
        },
        channels: slack ? ["in_app", "slack"] : ["in_app"],
        custom: slack,
      },
    ],
  };
}

function problem(status: number, title: string, detail: string) {
  return HttpResponse.json(
    { type: "about:blank", title, status, detail, code: status === 404 ? "not_found" : "invalid" },
    { status, headers: { "content-type": "application/problem+json" } },
  );
}

function routeOut(body: RouteIn, id: string, instanceId: string | null): RouteOut {
  return {
    id,
    instance_id: instanceId,
    name: body.name,
    tool_name: body.tool_name ?? null,
    component_kind: body.component_kind ?? null,
    component_ids: body.component_ids ?? [],
    members: sampleMembers
      .filter((member) => body.member_ids?.includes(member.user_id))
      .map((member) => ({ id: member.user_id, name: member.display_name })),
    roles: sampleRoles
      .filter((role) => body.role_ids?.includes(role.id))
      .map((role) => ({ id: role.id, name: role.name })),
    channels: body.channels ?? [],
    channel_ids: body.channel_ids ?? [],
    created_by: DANIEL,
    updated_at: new Date().toISOString(),
  };
}

/** The approvals API on prod with the sample inbox; put these before `p02Handlers()` (it has a simpler decide). */
export function approvalsHandlers() {
  let preferences = sampleApprovalPreferences(false);
  let routes = [...sampleRoutes];
  let policy = sampleApprovalPolicy;
  return [
    http.get(`${API}/instances/:instance/approvals`, ({ request }) => {
      const query = new URL(request.url).searchParams;
      const status = query.get("status") ?? "pending";
      const q = query.get("q")?.toLowerCase();
      const rows = sampleApprovals.filter(
        (row) =>
          row.status === status &&
          (!query.get("tool") || row.tool_name === query.get("tool")) &&
          (!query.get("type") || row.type === query.get("type")) &&
          (!query.get("source_kind") || row.source_kind === query.get("source_kind")) &&
          (!query.get("source_id") || row.source_id === query.get("source_id")) &&
          (!query.get("user_id") || row.user_id === query.get("user_id")) &&
          (!query.get("schedule_id") || row.schedule_id === query.get("schedule_id")) &&
          (!q ||
            [row.tool_name, row.run_id, row.user_id, row.id].some((value) =>
              value?.toLowerCase().includes(q),
            )),
      );
      const page: ApprovalsPageOut = {
        data: rows,
        page: 1,
        limit: 50,
        total:
          status === "pending"
            ? rows.length
            : Math.max(rows.length, sampleApprovalCounts[status as "approved"]),
        truncated: false,
        oldest_pending_at:
          status === "pending" ? (rows.map((row) => row.created_at).sort()[0] ?? null) : null,
      };
      return HttpResponse.json(page);
    }),
    http.get(`${API}/instances/:instance/approvals/counts`, () => HttpResponse.json(sampleApprovalCounts)),
    http.get(`${API}/instances/:instance/approvals/routes`, () => HttpResponse.json(routes)),
    http.post(`${API}/instances/:instance/approvals/routes`, async ({ request }) => {
      const body = (await request.json()) as RouteIn;
      if (!body.member_ids?.length && !body.role_ids?.length)
        return problem(422, "Invalid route", "A route needs at least one member or role.");
      const created = routeOut(body, `rte_${String(routes.length + 1)}`, PROD);
      routes = [created, ...routes];
      return HttpResponse.json(created, { status: 201 });
    }),
    http.put(`${API}/approvals/routes/:route`, async ({ request, params }) => {
      const body = (await request.json()) as RouteIn;
      const current = routes.find((route) => route.id === params.route);
      if (!current) return problem(404, "Not found", "There is no such route.");
      const updated = routeOut(body, current.id, current.instance_id);
      routes = routes.map((route) => (route.id === current.id ? updated : route));
      return HttpResponse.json(updated);
    }),
    http.delete(`${API}/approvals/routes/:route`, ({ params }) => {
      routes = routes.filter((route) => route.id !== params.route);
      return new HttpResponse(null, { status: 204 });
    }),
    http.get(`${API}/instances/:instance/approvals/policy`, () => HttpResponse.json(policy)),
    http.put(`${API}/instances/:instance/approvals/policy`, async ({ request }) => {
      const body = (await request.json()) as { enforce_expiry: boolean; ttl_hours?: number | null };
      policy = { ...policy, enforce_expiry: body.enforce_expiry, ttl_hours: body.ttl_hours ?? null };
      return HttpResponse.json(policy);
    }),
    http.get(`${API}/instances/:instance/approvals/:approval`, ({ params }) => {
      const detail = sampleApprovalDetail(String(params.approval));
      return detail ? HttpResponse.json(detail) : problem(404, "Not found", "No such approval.");
    }),
    http.post(`${API}/instances/:instance/approvals/:approval/decide`, async ({ request, params }) => {
      const body = (await request.json()) as {
        decision: "approve" | "reject";
        note?: string | null;
        edited_args?: Record<string, unknown> | null;
      };
      if (body.decision === "reject" && !body.note?.trim())
        return problem(
          422,
          "Invalid decision",
          "Rejecting needs a note: the requester sees it, and so does the audit log.",
        );
      const before = TOOL_ARGS[String(params.approval)] ?? {};
      const result: DecideOut = {
        approval_id: String(params.approval),
        instance_id: PROD,
        decision: body.decision,
        status: body.decision === "approve" ? "approved" : "rejected",
        run_id: "run_4471a",
        session_id: "ses_4471a",
        continue_state: "continued",
        continue_detail: null,
        already_resolved: false,
        args_changed: Object.keys(body.edited_args ?? {}).filter(
          (key) => JSON.stringify(before[key]) !== JSON.stringify(body.edited_args?.[key]),
        ),
      };
      return HttpResponse.json(result);
    }),
    http.get(`${API}/me/notification-preferences`, () => HttpResponse.json(preferences)),
    http.put(`${API}/me/notification-preferences`, async ({ request }) => {
      const body = (await request.json()) as { events?: Record<string, string[] | null> };
      const channels = body.events?.["approval.created"];
      if (channels) preferences = sampleApprovalPreferences(channels.includes("slack"));
      return HttpResponse.json(preferences);
    }),
    http.get(`${API}/notifications/channels`, () => HttpResponse.json(sampleApprovalChannels)),
  ];
}
