import { expect, test, type Page } from "@playwright/test";

import { stubApi } from "../e2e/stubs";

/** Every CSP or Trusted Types violation the page reports, as text. */
async function collectViolations(page: Page): Promise<string[]> {
  const violations: string[] = [];
  page.on("console", (message) => {
    const text = message.text();
    if (/Content Security Policy|Trusted Type|TrustedHTML|TrustedScript/i.test(text)) violations.push(text);
  });
  page.on("pageerror", (error) => {
    violations.push(`${page.url()}: ${error.message}`);
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      console.error(`Content Security Policy violation: ${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  return violations;
}

const ROUTES = [
  "/i/prod-agentos/home",
  "/i/prod-agentos/chat",
  "/i/prod-agentos/sessions",
  "/i/prod-agentos/traces",
  "/i/prod-agentos/metrics",
  "/i/prod-agentos/knowledge",
  "/i/prod-agentos/approvals",
  "/i/prod-agentos/studio/agents",
  "/i/prod-agentos/studio/workflows",
  "/i/prod-agentos/settings",
  "/access/people",
  "/access/roles",
  "/access/audit",
  "/org/settings",
];

test("the production policy holds on every main screen", async ({ page }) => {
  test.setTimeout(180_000);
  const violations = await collectViolations(page);
  await stubApi(page);
  const response = await page.goto("/");
  expect(response?.headers()["content-security-policy"]).toContain("require-trusted-types-for 'script'");
  for (const route of ROUTES) {
    await page.goto(route);
    // The realtime event stream keeps the network busy: wait for the page itself, then for lazy chunks.
    await expect(page.getByRole("main"), violations.join("\n")).toBeVisible();
    await page.waitForTimeout(750);
  }
  expect(violations).toEqual([]);
});

test("the Trusted Types policy refuses HTML strings", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  const refused = await page.evaluate(() => {
    try {
      document.body.insertAdjacentHTML("beforeend", "<img src=x>");
      return false;
    } catch {
      return true;
    }
  });
  expect(refused).toBe(true);
});
