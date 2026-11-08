// Operate flows against a stubbed gateway (the mock model's support-triage on prod): chat, a tool that pauses for
// approval, an approval with an edited amount, the run completing, the Sessions timeline, user isolation, ⌘K.
import { expect, test, type Page } from "@playwright/test";

import { session, stubGateway } from "./fixtures/chat";
import { access, instances, stubApi } from "./stubs";

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

test("chat: below 1280px session details open in a sheet, below 1024px so does the session list", async ({
  page,
}) => {
  await stubApi(page);
  await stubGateway(page);
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.goto("/i/prod-agentos/chat/agents/support-triage");
  await page.getByRole("textbox", { name: "Message Support triage" }).fill("Please refund order 4471");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/chat\/agents\/support-triage\/ses_7f3a91c2/);

  // The conversation keeps its width: no details column beside it, and Send stays inside the composer.
  const run = page.getByRole("article", { name: "Run run_9f2c41" });
  await expect(run).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Session" })).toHaveCount(0);
  expect((await run.boundingBox())?.width).toBeGreaterThan(480);
  await expectSendInsideComposer(page);

  await page.getByRole("button", { name: "Session details" }).click();
  const details = page.getByRole("dialog", { name: "Session" });
  await expect(details.getByText("ses_7f3a91c2")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(details).toBeHidden();

  // Narrower still, the session list moves into a sheet too; picking a session closes it.
  await page.setViewportSize({ width: 800, height: 900 });
  await expect(page.getByRole("navigation", { name: "Sessions for support-triage" })).toHaveCount(0);
  await page.getByRole("button", { name: "Sessions", exact: true }).click();
  const sessions = page.getByRole("dialog", { name: "Sessions" });
  await expect(sessions.getByRole("navigation", { name: "Sessions for support-triage" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(sessions).toBeHidden();
  await expectSendInsideComposer(page);
});

async function expectSendInsideComposer(page: Page) {
  const send = page.getByRole("button", { name: "Send" });
  const composer = page.locator("[class*='@container/composer']");
  const [sendBox, composerBox] = await Promise.all([send.boundingBox(), composer.boundingBox()]);
  expect(sendBox && composerBox && sendBox.x + sendBox.width <= composerBox.x + composerBox.width).toBe(true);
}

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
