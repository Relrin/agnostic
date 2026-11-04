// The approvals inbox stub: one pending refund on prod that can be rejected with a note.
import type { Page, Route } from "@playwright/test";

import { instances } from "../stubs";

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const REFUND = {
  id: "apv_7Kq2",
  tool_name: "refund_customer",
  type: "blocking",
  status: "pending",
  agentos_status: "pending",
  args_changed: [],
  component_id: "billing-agent",
  component_kind: "agent",
  source_id: "billing-agent",
  source_kind: "agent",
  source_name: "billing-agent",
  created_at: minutesAgo(134),
  expires_at: minutesAgo(134 - 24 * 60),
  expiry_enforced: false,
  expiry_source: "ttl",
  note: null,
  resolved_at: null,
  resolved_by: null,
  resolved_by_name: null,
  run_id: "run_4471a",
  schedule_id: null,
  session_id: "ses_4471a",
  user_id: "zd:48121",
  user_name: null,
  via: "sa:zendesk-bridge",
};

const DETAIL = {
  ...REFUND,
  tool_args: {
    order_id: "4471",
    charge_id: "ch_3PqL9w",
    amount: 49,
    currency: "USD",
    reason: "duplicate_charge",
  },
  resolution_data: {},
  requirements: [],
  context: {
    user_message: "My card was charged twice for order #4471. Can you refund one of them?",
    agent_message: "Found two identical $49.00 charges on order #4471. Refunding the duplicate charge.",
  },
  timeline: [
    {
      text: "Run paused at refund_customer · run_status PAUSED",
      at: REFUND.created_at,
      detail: null,
      state: "done",
    },
    {
      text: "Routed to Support AI and Billing ops",
      at: REFUND.created_at,
      detail: "Slack + control plane",
      state: "done",
    },
    { text: "Waiting for a decision", at: REFUND.expires_at, detail: "Expires", state: "now" },
  ],
  routed_to: ["Support AI", "Billing ops"],
  channels: ["slack", "in_app"],
  views: [],
  can_resolve: true,
  cannot_resolve_reason: null,
  run_status: "PAUSED",
  user_isolation: false,
  elevation_enabled: true,
  policy: {
    instance_id: instances[0]?.id,
    enforce_expiry: true,
    ttl_hours: 24,
    updated_at: null,
    updated_by: null,
  },
};

export type Inbox = { decided: Record<string, unknown>[] };

export async function stubApprovals(page: Page): Promise<Inbox> {
  const state: Inbox = { decided: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(/\/api\/v1\/instances\/[^/]+\/approvals(\/[^?]*)?(\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const rest = url.pathname.replace(/^.*\/approvals\/?/, "");
    const method = route.request().method();
    if (rest === "count") return route.fallback();
    if (method === "GET" && rest === "") {
      const pending = url.searchParams.get("status") ?? "pending";
      const rows = pending === "pending" && state.decided.length === 0 ? [REFUND] : [];
      return json(route, {
        data: rows,
        page: 1,
        limit: 50,
        total: rows.length,
        truncated: false,
        oldest_pending_at: rows[0]?.created_at ?? null,
      });
    }
    if (method === "GET" && rest === "counts")
      return json(route, {
        pending: state.decided.length ? 0 : 1,
        approved: 41,
        rejected: state.decided.length ? 7 : 6,
        expired: 2,
        cancelled: 0,
        truncated: false,
      });
    if (method === "GET" && rest === REFUND.id) {
      const decided = state.decided[0];
      return json(
        route,
        decided
          ? {
              ...DETAIL,
              status: "rejected",
              can_resolve: false,
              note: decided.note,
              resolved_by: "usr_dana",
              resolved_by_name: "Daniel Okafor",
              resolved_at: new Date().toISOString(),
            }
          : DETAIL,
      );
    }
    if (method === "POST" && rest === `${REFUND.id}/decide`) {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      state.decided.push(body);
      return json(route, {
        approval_id: REFUND.id,
        instance_id: instances[0]?.id,
        decision: "reject",
        status: "rejected",
        run_id: REFUND.run_id,
        session_id: REFUND.session_id,
        continue_state: "continued",
        continue_detail: null,
        already_resolved: false,
        args_changed: [],
      });
    }
    return json(route, { type: "x", title: "Not stubbed", status: 404, detail: `${method} ${rest}` }, 404);
  });
  return state;
}
