// The chat gateway stub: support-triage on prod, a refund that pauses for approval and completes once approved.
import type { Page, Route } from "@playwright/test";

import { instances } from "../stubs";

const GATEWAY = /\/api\/v1\/instances\/[^/]+\/os\//;
const RUN = {
  run_id: "run_9f2c41",
  session_id: "ses_7f3a91c2",
  agent_id: "support-triage",
  agent_name: "Support triage",
};
const REFUND = {
  tool_call_id: "call_refund",
  tool_name: "refund_customer",
  tool_args: { customer_id: "cus_8812", amount: 49, reason: "requested in chat" },
  requires_confirmation: true,
};

function sse(events: Record<string, unknown>[]): string {
  return events.map((event) => `event: ${String(event.event)}\ndata: ${JSON.stringify(event)}\n\n`).join("");
}

const paused = [
  { event: "RunStarted", event_index: 0, created_at: 1, ...RUN, model: "mock-1" },
  {
    event: "ToolCallStarted",
    event_index: 1,
    created_at: 1,
    ...RUN,
    tool: { tool_call_id: "call_lookup", tool_name: "lookup_order", tool_args: { order_id: "ord_4471" } },
  },
  {
    event: "ToolCallCompleted",
    event_index: 2,
    created_at: 1.4,
    ...RUN,
    tool: { tool_call_id: "call_lookup", tool_name: "lookup_order", result: "shipped" },
  },
  { event: "RunPaused", event_index: 3, created_at: 2, ...RUN, tools: [REFUND] },
];
const continued = [
  ...paused,
  { event: "RunContinued", event_index: 4, created_at: 60, ...RUN },
  {
    event: "ToolCallStarted",
    event_index: 5,
    created_at: 60,
    ...RUN,
    tool: { ...REFUND, tool_args: { ...REFUND.tool_args, amount: 45 } },
  },
  {
    event: "ToolCallCompleted",
    event_index: 6,
    created_at: 61,
    ...RUN,
    tool: {
      tool_call_id: "call_refund",
      tool_name: "refund_customer",
      result: "Refunded 45.00 to cus_8812 (requested in chat).",
    },
  },
  {
    event: "RunContent",
    event_index: 7,
    created_at: 61,
    ...RUN,
    content: "Done. Refunded 45.00 to cus_8812 (requested in chat).",
  },
  { event: "RunCompleted", event_index: 8, created_at: 62, ...RUN, metrics: { total_tokens: 2106 } },
];

export const session = {
  session_id: RUN.session_id,
  session_name: "Refund for order 4471",
  session_state: {},
  user_id: "usr_dana",
  agent_id: "support-triage",
  total_tokens: 2106,
  created_at: "2026-11-01T10:41:00Z",
  updated_at: "2026-11-01T10:44:00Z",
};

export type Gateway = { decided: Record<string, unknown>[]; runs: { status: string }[] };

export async function stubGateway(
  page: Page,
  options: { sessions?: Record<string, unknown>[] } = {},
): Promise<Gateway> {
  const state: Gateway = { decided: [], runs: [] };
  const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body });
  await page.route(GATEWAY, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^.*\/os\//, "");
    const method = route.request().method();
    if (method === "GET" && path === "agents")
      return json(route, [{ id: "support-triage", name: "Support triage", current_version: 3 }]);
    if (method === "GET" && (path === "teams" || path === "workflows")) return json(route, []);
    if (method === "GET" && path === "sessions") {
      const items = options.sessions ?? (state.runs.length ? [session] : []);
      return json(route, {
        data: items,
        meta: { page: 1, limit: 20, total_pages: 1, total_count: items.length },
      });
    }
    if (method === "GET" && path === `sessions/${RUN.session_id}`)
      return json(route, { ...session, session_summary: null });
    if (method === "GET" && path === `sessions/${RUN.session_id}/runs`) {
      return json(
        route,
        state.runs.map((run) => ({
          run_id: RUN.run_id,
          agent_id: "support-triage",
          status: run.status,
          run_input: "Please refund order 4471",
          events: run.status === "COMPLETED" ? continued : paused,
          created_at: "2026-11-01T10:42:00Z",
        })),
      );
    }
    if (method === "POST" && path === "agents/support-triage/runs") {
      state.runs.push({ status: "PAUSED" });
      return route.fulfill({ contentType: "text/event-stream", body: sse(paused) });
    }
    if (method === "POST" && path === `agents/support-triage/runs/${RUN.run_id}/resume`) {
      return route.fulfill({
        contentType: "text/event-stream",
        body: `event: replay\ndata: {}\n\n${sse(continued)}`,
      });
    }
    if (method === "GET" && path === "approvals") {
      const pending = state.decided.length === 0 && state.runs.length > 0;
      const items = pending
        ? [
            {
              id: "apr_1",
              run_id: RUN.run_id,
              session_id: RUN.session_id,
              status: "pending",
              source_type: "agent",
              agent_id: "support-triage",
              tool_name: "refund_customer",
              tool_args: REFUND.tool_args,
              created_at: Math.floor(Date.now() / 1000) - 120,
            },
          ]
        : [];
      return json(route, {
        data: items,
        meta: { page: 1, limit: 20, total_pages: 1, total_count: items.length },
      });
    }
    return json(route, { detail: `not stubbed: ${method} ${path}` }, 404);
  });
  await page.route(/\/api\/v1\/instances\/[^/]+\/approvals\/apr_1\/decide$/, async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    state.decided.push(body);
    state.runs = [{ status: "COMPLETED" }];
    await route.fulfill({
      json: {
        approval_id: "apr_1",
        instance_id: instances[0]?.id,
        decision: "approve",
        status: "approved",
        run_id: RUN.run_id,
        session_id: RUN.session_id,
        continue_state: "continued",
        continue_detail: null,
        already_resolved: false,
        args_changed: ["amount"],
      },
    });
  });
  return state;
}
