// Keyboard-only journeys (Tab, Shift+Tab, Enter, Space, typing; no clicks): chat with an approval that pauses the
// run, deciding an approval in the inbox, publishing an agent draft from Studio, and editing a role's permissions.
import { expect, test, type Locator, type Page } from "@playwright/test";

import { stubApprovals } from "./fixtures/approvals";
import { stubGateway } from "./fixtures/chat";
import { stubRoles } from "./fixtures/roles";
import { stubStudio } from "./fixtures/studio";
import { stubApi } from "./stubs";

/** Press Tab (or Shift+Tab) until `target` has focus, then check it shows a keyboard focus indicator. */
async function tabTo(page: Page, target: Locator, { backwards = false, max = 80 } = {}) {
  await expect(target).toBeVisible();
  for (let step = 0; step < max; step += 1) {
    if (await target.evaluate((element) => element === document.activeElement)) break;
    await page.keyboard.press(backwards ? "Shift+Tab" : "Tab");
  }
  await expect(target).toBeFocused();
  expect(await target.evaluate((element) => element.matches(":focus-visible"))).toBe(true);
}

/** Whether the focused element sits inside `container`. */
const holdsFocus = (container: Locator) =>
  container.evaluate((element) => element.contains(document.activeElement));

test("chat: send a message with Enter and approve the paused refund with edited args", async ({ page }) => {
  await stubApi(page);
  const gateway = await stubGateway(page);
  await page.goto("/i/prod-agentos/chat/agents/support-triage");

  const composer = page.getByRole("textbox", { name: "Message Support triage" });
  await tabTo(page, composer);
  await page.keyboard.type("Please refund order 4471");
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/chat\/agents\/support-triage\/ses_7f3a91c2/);
  const run = page.getByRole("article", { name: "Run run_9f2c41" });
  await expect(run.getByText("PAUSED")).toBeVisible();

  const approval = page.getByRole("region", { name: "Approval required for refund_customer" });
  await tabTo(page, approval.getByRole("button", { name: "Edit args" }));
  await page.keyboard.press("Enter");
  const args = approval.getByLabel("tool_args (JSON)");
  await tabTo(page, args);
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type('{"customer_id": "cus_8812", "amount": 45, "reason": "requested in chat"}');
  await tabTo(page, approval.getByRole("button", { name: "Approve with edits" }));
  await page.keyboard.press("Enter");

  await expect(page.getByText("Done. Refunded 45.00 to cus_8812 (requested in chat).")).toBeVisible();
  await expect(page.getByRole("article", { name: "Run run_9f2c41" }).getByText("COMPLETED")).toBeVisible();
  expect(gateway.decided).toEqual([
    {
      decision: "approve",
      edited_args: { customer_id: "cus_8812", amount: 45, reason: "requested in chat" },
    },
  ]);
});

test("approvals: open the pending refund, write a note and reject it from the keyboard", async ({ page }) => {
  await stubApi(page);
  const inbox = await stubApprovals(page);
  await page.goto("/i/prod-agentos/approvals");

  const table = page.getByRole("table", { name: "Approvals" });
  await tabTo(page, table.getByRole("button", { name: "refund_customer" }));
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/approval=apv_7Kq2/);
  const aside = page.getByRole("complementary", { name: "Approval details" });
  await expect(aside.getByText("RUN PAUSED", { exact: true })).toBeVisible();

  await tabTo(page, aside.getByLabel("Note · required to reject"));
  await page.keyboard.type("Outside the 30-day refund window.");
  const reject = aside.getByRole("button", { name: "Reject" });
  await tabTo(page, reject);
  await page.keyboard.press("Enter");

  await expect(aside.getByText("Rejected · the run is continuing.")).toBeVisible();
  expect(inbox.decided).toEqual([{ decision: "reject", note: "Outside the 30-day refund window." }]);
  await expect(aside.getByRole("group", { name: "Resolution" })).toContainText("Rejected by Daniel Okafor");
});

test("studio: publish the agent draft past a failed gate with a reason", async ({ page }) => {
  await stubApi(page);
  const studio = await stubStudio(page);
  await page.goto("/i/staging-agentos/studio/agents/support-triage");
  await expect(page.getByText(/Draft v4 · based on v3/)).toBeVisible();

  const open = page.getByRole("button", { name: "Publish v4" });
  await tabTo(page, open);
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog", { name: "Publish v4" });
  await expect(dialog.getByText("v4 draft (8.40) would be blocked from publishing.")).toBeVisible();
  expect(await holdsFocus(dialog)).toBe(true);
  const publish = dialog.getByRole("button", { name: "Override and publish v4" });
  await expect(publish).toBeDisabled();

  await tabTo(page, dialog.getByRole("textbox", { name: "Override reason" }));
  await page.keyboard.type("Judge is wrong on two cases");
  await tabTo(page, dialog.getByRole("textbox", { name: "Release notes" }));
  await page.keyboard.type("Switches to the precise model.");
  await tabTo(page, publish);
  // Focus stays inside the dialog while it is open.
  await page.keyboard.press("Tab");
  expect(await holdsFocus(dialog)).toBe(true);
  await tabTo(page, publish, { backwards: true });
  await page.keyboard.press("Enter");

  await expect(page.getByText(/v4 becomes current on staging-agentos, replacing v3/)).toBeVisible();
  await expect(dialog).toBeHidden();
  expect(studio.publishes).toEqual([
    { notes: "Switches to the precise model.", override_reason: "Judge is wrong on two cases" },
  ]);
  // Closing the dialog returns focus to the button that opened it.
  await expect(open).toBeFocused();
});

test("roles: toggle Operator permissions with Space and save from the keyboard", async ({ page }) => {
  await stubApi(page);
  const roles = await stubRoles(page);
  await page.goto("/access/roles?role=rol_operator");

  const matrix = page.getByRole("table", { name: "Operator permissions" });
  const knowledgeWrite = matrix.getByRole("checkbox", { name: "Operator: knowledge write" });
  const approvalsDelete = matrix.getByRole("checkbox", { name: "Operator: approvals delete" });
  await tabTo(page, knowledgeWrite, { max: 120 });
  await page.keyboard.press("Space");
  await expect(knowledgeWrite).toBeChecked();
  await tabTo(page, approvalsDelete, { max: 120 });
  await page.keyboard.press("Space");
  await expect(approvalsDelete).not.toBeChecked();

  const bar = page.getByRole("region", { name: "Save changes" });
  await expect(bar).toContainText("2 unsaved changes");
  await tabTo(page, bar.getByRole("button", { name: "Save role" }), { max: 120 });
  await page.keyboard.press("Enter");

  await expect(bar).toContainText("All changes saved");
  expect(roles.saved).toHaveLength(1);
  expect(roles.saved[0]?.version).toBe(4);
  expect(roles.saved[0]?.permissions.knowledge).toEqual(["read", "write"]);
  expect(roles.saved[0]?.permissions.approvals).toEqual(["read", "write"]);
  await expect(page.getByRole("button", { name: "Version 5" })).toBeVisible();
});
