// The bell in the header: an unread approval request, opening it marks it read and goes to the approval.
import { expect, test } from "@playwright/test";

import { stubApi, T } from "./stubs";

const notification = {
  id: "ntf_1",
  kind: "approval.created",
  title: "refund_customer needs approval",
  body: "agent billing-agent · amount=49.0",
  link: "/i/prod-agentos/approvals?approval=apv_7Kq2",
  instance_id: "ins_01M6A0EEZEQ373S26F2014PRD",
  data: {},
  created_at: T,
  read_at: null,
};

test("the bell shows unread notifications and opens them", async ({ page }) => {
  await stubApi(page);
  let unread = 1;
  let marked: unknown;
  await page.route(/\/api\/v1\/notifications\/unread-count$/, (route) => route.fulfill({ json: { unread } }));
  await page.route(/\/api\/v1\/notifications(\?.*)?$/, (route) =>
    route.fulfill({ json: { data: [notification], next_cursor: null, total_estimate: null } }),
  );
  await page.route(/\/api\/v1\/notifications\/read$/, async (route) => {
    marked = route.request().postDataJSON();
    unread = 0;
    await route.fulfill({ json: { changed: 1, unread: 0 } });
  });

  await page.goto("/i/prod-agentos/home");
  const bell = page.getByRole("button", { name: "Notifications, 1 unread" });
  await expect(bell).toBeVisible();
  await bell.click();
  const panel = page.getByRole("dialog", { name: "Notifications" });
  await panel.getByRole("button", { name: /refund_customer needs approval/ }).click();

  expect(marked).toEqual({ ids: ["ntf_1"] });
  await expect(page).toHaveURL(/\/i\/prod-agentos\/approvals\?approval=apv_7Kq2/);
  await expect(page.getByRole("button", { name: "Notifications", exact: true })).toBeVisible();
});
