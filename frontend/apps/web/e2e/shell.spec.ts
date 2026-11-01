import { expect, test } from "@playwright/test";

import { stubApi } from "./stubs";

test("anonymous visitors are sent to sign in", async ({ page }) => {
  await stubApi(page, { signedIn: false });
  await page.goto("/access/people");
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("opens the last instance and renders the shell", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/i\/prod-agentos\/home$/);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("6 agents · 3 agent teams · 5 workflows on prod-agentos")).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Primary" });
  for (const label of [
    "Home",
    "Chat",
    "Agents",
    "Sessions",
    "Memory",
    "Approvals",
    "People & groups",
    "Settings",
  ]) {
    await expect(nav.getByRole("link", { name: label })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Switch AgentOS instance" })).toContainText("prod-agentos");
  await expect(page.getByRole("status").filter({ hasText: "Healthy" })).toContainText("38 ms · agno 3.1.12");
  await expect(page.getByText("Localhost Company")).toBeVisible();
});

test("the audit log reads from the API", async ({ page }) => {
  await stubApi(page);
  await page.goto("/access/audit");
  await expect(page.getByText("Daniel Okafor signed in (password)")).toBeVisible();
  await expect(page.getByRole("link", { name: "Audit log" })).toHaveAttribute("aria-current", "page");
});

test("command palette jumps to a page", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/prod-agentos/home");
  await page.getByRole("button", { name: /Search or jump to/ }).click();
  await page.getByPlaceholder("Search or jump to…").fill("audit log");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/access\/audit$/);
});

test("sidebar matches the visual baseline @visual", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/prod-agentos/approvals");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await expect(page.locator("aside")).toHaveScreenshot("sidebar.png");
});
