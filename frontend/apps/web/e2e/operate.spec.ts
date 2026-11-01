// P02 operate flows against a stubbed gateway (the mock model's support-triage on prod): chat, a tool that pauses for
// approval, an approval with an edited amount, the run completing, the Sessions timeline, user isolation, ⌘K.
import { expect, test, type Page, type Route } from "@playwright/test";

import { access, instances, stubApi } from "./stubs";

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

const session = {
  session_id: RUN.session_id,
  session_name: "Refund for order 4471",
  session_state: {},
  user_id: "usr_dana",
  agent_id: "support-triage",
  total_tokens: 2106,
  created_at: "2026-11-01T10:41:00Z",
  updated_at: "2026-11-01T10:44:00Z",
};

type Gateway = { decided: Record<string, unknown>[]; runs: { status: string }[] };

async function stubGateway(
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

test("chat: a refund pauses for approval, Maya approves with an edited amount, the run completes", async ({
  page,
}) => {
  await stubApi(page);
  const gateway = await stubGateway(page);
  await page.goto("/i/prod-agentos/chat/agents/support-triage");

  await page.getByRole("textbox", { name: "Message Support triage" }).fill("Please refund order 4471");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/chat\/agents\/support-triage\/ses_7f3a91c2/);
  const run = page.getByRole("article", { name: "Run run_9f2c41" });
  await expect(run.getByText("PAUSED")).toBeVisible();
  await expect(run.getByText("lookup_order")).toBeVisible();

  const approval = page.getByRole("region", { name: "Approval required for refund_customer" });
  await expect(approval.getByText(/Shown because you hold/)).toContainText("approvals:write on prod-agentos");
  await approval.getByRole("button", { name: "Edit args" }).click();
  await approval
    .getByLabel("tool_args (JSON)")
    .fill('{"customer_id": "cus_8812", "amount": 45, "reason": "requested in chat"}');
  await approval.getByRole("button", { name: "Approve with edits" }).click();

  await expect(page.getByText("Done. Refunded 45.00 to cus_8812 (requested in chat).")).toBeVisible();
  await expect(page.getByRole("article", { name: "Run run_9f2c41" }).getByText("COMPLETED")).toBeVisible();
  expect(gateway.decided).toEqual([
    {
      decision: "approve",
      edited_args: { customer_id: "cus_8812", amount: 45, reason: "requested in chat" },
    },
  ]);

  // Sessions shows the run timeline.
  await page.goto("/i/prod-agentos/sessions/ses_7f3a91c2");
  const detail = page.getByRole("complementary", { name: "Session detail" });
  await expect(detail.getByRole("separator").filter({ hasText: "Run 1" })).toContainText("completed");
  await detail.getByRole("tab", { name: "Runs" }).click();
  await expect(detail.getByText("Completed after 2 tool calls.")).toBeVisible();
});

test("sessions: the Owner sees every user with the isolation callout", async ({ page }) => {
  await stubApi(page);
  await stubGateway(page, {
    sessions: [
      session,
      { ...session, session_id: "ses_other", session_name: "Someone else", user_id: "usr_maya" },
    ],
  });
  await page.goto("/i/prod-agentos/sessions");
  await expect(page.getByRole("table", { name: "Sessions" }).getByText("Someone else")).toBeVisible();
  await expect(page.getByText(/you're seeing all users as Owner/)).toBeVisible();
});

test("sessions: Maya (Operator) sees only her own sessions", async ({ page }) => {
  await stubApi(page);
  const operator = {
    ...access,
    org_role: "member",
    implicit_full_access: false,
    roles: ["Operator"],
    token_scopes: ["agents:run", "sessions:read", "approvals:write"],
    runtime_scopes: ["agents:read", "agents:run", "sessions:read", "approvals:read", "approvals:write"],
  };
  await page.route(/\/api\/v1\/me\/access/, (route) => route.fulfill({ json: operator }));
  // AgentOS filters by the token's sub under isolation: the gateway returns only Maya's sessions.
  await stubGateway(page, {
    sessions: [{ ...session, user_id: "usr_maya", session_name: "Maya's session" }],
  });
  await page.goto("/i/prod-agentos/sessions");
  const table = page.getByRole("table", { name: "Sessions" });
  await expect(table.getByText("Maya's session")).toBeVisible();
  await expect(table.getByText("Someone else")).toHaveCount(0);
  await expect(page.getByText(/you're seeing your own sessions/)).toBeVisible();
});

test("⌘K finds a session by pasting its id", async ({ page }) => {
  await stubApi(page);
  await stubGateway(page);
  await page.route(/\/api\/v1\/search/, (route) => route.fulfill({ json: { data: [] } }));
  await page.route(/\/os\/sessions\/0f8fad5b-d9cb-469f-a165-70867728950e$/, (route) =>
    route.fulfill({
      json: {
        ...session,
        session_id: "0f8fad5b-d9cb-469f-a165-70867728950e",
        session_name: "Pasted session",
      },
    }),
  );
  await page.goto("/i/prod-agentos/home");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.getByPlaceholder("Search or jump to…").fill("0f8fad5b-d9cb-469f-a165-70867728950e");
  await page.getByRole("option", { name: /Pasted session/ }).click();
  await expect(page).toHaveURL(/\/sessions\/0f8fad5b-d9cb-469f-a165-70867728950e$/);
});

test("the approvals badge shows the pending count", async ({ page }) => {
  await stubApi(page);
  await page.route(/\/api\/v1\/instances\/[^/]+\/approvals\/count$/, (route) =>
    route.fulfill({ json: { instance_id: instances[0]?.id, count: 3, available: true } }),
  );
  await page.goto("/i/prod-agentos/home");
  await expect(page.getByRole("navigation", { name: "Primary" }).getByLabel("3 pending")).toBeVisible();
});
