// Automated WCAG 2.2 AA check of every page: each route renders against the shared stubs (calls they don't cover
// answer 404, so pages show their error states) and axe must find no violations. Manual screen-reader checks are
// in docs/guides/accessibility.md.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { me, stubApi } from "./stubs";

const INSTANCE = "/i/prod-agentos";
const INSTANCE_PAGES = [
  "home",
  "chat",
  "ask",
  "studio/agents",
  "studio/teams",
  "studio/workflows",
  "studio/registry",
  "studio/sources",
  "sessions",
  "traces",
  "metrics",
  "evals",
  "memory",
  "knowledge",
  "learnings",
  "files",
  "approvals",
  "scheduler",
  "queue",
  "settings",
];
const ORG_PAGES = [
  "/instances",
  "/instances/connect",
  "/access/people",
  "/access/roles",
  "/access/service-accounts",
  "/access/audit",
  "/org/settings",
  "/account",
];
const PUBLIC_PAGES = ["/login", "/reset-password"];

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function stubEverything(page: Page, signedIn: boolean) {
  // Registered first, so every specific stub below wins over it.
  await page.route(/\/api\/v1\//, (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/problem+json",
      json: { type: "about:blank", title: "Not stubbed", status: 404, code: "not_found" },
    }),
  );
  await stubApi(page, { signedIn });
}

async function expectNoViolations(page: Page) {
  await expect(page.getByRole("main").first()).toBeVisible();
  // Failed requests retry with backoff before a page settles on its error state.
  await expect(page.getByRole("status", { name: /^Loading/ })).toHaveCount(0, { timeout: 20_000 });
  const results = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze();
  const summary = results.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact ?? "?"}): ${violation.help}\n` +
      violation.nodes.map((node) => `    ${node.target.join(" ")}`).join("\n"),
  );
  expect(summary, `axe violations on ${page.url()}`).toEqual([]);
}

for (const path of INSTANCE_PAGES) {
  test(`a11y: ${path}`, async ({ page }) => {
    await stubEverything(page, true);
    await page.goto(`${INSTANCE}/${path}`);
    await expectNoViolations(page);
  });
}

for (const path of ORG_PAGES) {
  test(`a11y: ${path}`, async ({ page }) => {
    await stubEverything(page, true);
    await page.goto(path);
    await expectNoViolations(page);
  });
}

for (const path of PUBLIC_PAGES) {
  test(`a11y: ${path}`, async ({ page }) => {
    await stubEverything(page, false);
    await page.goto(path);
    await expectNoViolations(page);
  });
}

test("a11y: compact density", async ({ page }) => {
  await stubEverything(page, true);
  await page.route(/\/api\/v1\/me$/, (route) =>
    route.fulfill({ json: { ...me, preferences: { density: "compact" } } }),
  );
  await page.goto(`${INSTANCE}/home`);
  await expect(page.locator("html")).toHaveAttribute("data-density", "compact");
  await expectNoViolations(page);
});

test("a11y: an open tour step", async ({ page }) => {
  await stubEverything(page, true);
  await page.goto("/instances/connect?tour=connect");
  const step = page.getByRole("dialog", { name: "Four short steps" });
  await expect(step).toBeFocused();
  await expectNoViolations(page);
  await page.keyboard.press("Escape");
  await expect(step).toBeHidden();
  await expect(page).toHaveURL(/\/instances\/connect$/);
});
