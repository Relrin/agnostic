// Approvals inbox against a stubbed control plane: a refund waits on prod, Dana opens it, writes a note and rejects.
import { expect, test } from "@playwright/test";

import { stubApprovals } from "./fixtures/approvals";
import { stubApi } from "./stubs";

test("approvals: open a pending refund, write a note and reject it", async ({ page }) => {
  await stubApi(page);
  const inbox = await stubApprovals(page);
  await page.goto("/i/prod-agentos/approvals");

  await expect(page.getByRole("heading", { name: "Approvals", level: 1 })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Pending/ })).toContainText("1");
  const table = page.getByRole("table", { name: "Approvals" });
  await expect(table.getByText("blocking · apv_7Kq2")).toBeVisible();
  await table.getByRole("button", { name: "refund_customer" }).click();

  await expect(page).toHaveURL(/approval=apv_7Kq2/);
  const aside = page.getByRole("complementary", { name: "Approval details" });
  await expect(aside.getByText("RUN PAUSED", { exact: true })).toBeVisible();
  await expect(aside.getByText(/My card was charged twice/)).toBeVisible();
  await expect(aside.getByRole("list", { name: "Approval timeline" })).toContainText(
    "Waiting for a decision",
  );

  const reject = aside.getByRole("button", { name: "Reject" });
  await expect(reject).toBeDisabled();
  await aside.getByLabel("Note · required to reject").fill("Outside the 30-day refund window.");
  await reject.click();

  await expect(aside.getByText("Rejected · the run is continuing.")).toBeVisible();
  expect(inbox.decided).toEqual([{ decision: "reject", note: "Outside the 30-day refund window." }]);
  await expect(aside.getByRole("group", { name: "Resolution" })).toContainText("Rejected by Daniel Okafor");
  await expect(page.getByRole("tab", { name: /Rejected/ })).toContainText("7");
});
