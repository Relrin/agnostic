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

/** A notebook with every kind of cell output jupyter-kit writes as HTML. */
const NOTEBOOK = {
  nbformat: 4,
  nbformat_minor: 5,
  metadata: { language_info: { name: "python" } },
  cells: [
    {
      cell_type: "markdown",
      metadata: {},
      source: [
        "# Volume review\n",
        "\n",
        "Growth is $g = \\frac{b}{a} - 1$ and <b>bold</b>.\n",
        "\n",
        "$$\\sum_i x_i$$",
      ],
    },
    {
      cell_type: "code",
      execution_count: 1,
      metadata: {},
      source: ["def growth(a, b):\n", "    return b / a - 1"],
      outputs: [
        { output_type: "stream", name: "stdout", text: ["done\n"] },
        {
          output_type: "execute_result",
          execution_count: 1,
          metadata: {},
          data: {
            "text/html": ["<table><tr><td>0.12</td></tr></table><script>window.ran = 1</script>"],
            "text/plain": ["0.12"],
          },
        },
        {
          output_type: "display_data",
          metadata: {},
          data: {
            "image/png":
              "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
          },
        },
        {
          output_type: "error",
          ename: "ZeroDivisionError",
          evalue: "division by zero",
          traceback: ["\u001b[0;31mZeroDivisionError\u001b[0m: division by zero"],
        },
      ],
    },
  ],
};

test("a notebook renders under the production policy", async ({ page }) => {
  const violations = await collectViolations(page);
  await stubApi(page);
  await page.route(/\/api\/v1\/shares\/notebook-token$/, (route) =>
    route.fulfill({
      json: {
        filename: "review.ipynb",
        content_type: "application/x-ipynb+json",
        size: 2048,
        audience: "anyone",
        shared_by: "Daniel Okafor",
        created_at: "2026-11-08T09:35:00Z",
        expires_at: null,
      },
    }),
  );
  await page.route(/\/api\/v1\/shares\/notebook-token\/content/, (route) =>
    route.fulfill({ json: NOTEBOOK, contentType: "application/x-ipynb+json" }),
  );
  await page.goto("/s/notebook-token");
  const notebook = page.getByRole("region", { name: "Notebook review.ipynb" });
  await expect(notebook.getByRole("heading", { name: "Volume review" }), violations.join("\n")).toBeVisible();
  await expect(notebook.locator(".katex").first()).toBeVisible();
  await expect(notebook.locator(".tok-keyword").first()).toHaveText("def");
  await expect(notebook.locator(".output_html td")).toHaveText("0.12");
  await expect(notebook.locator(".output_png img")).toBeVisible();
  await expect(notebook).toContainText("ZeroDivisionError");
  expect(await page.evaluate(() => (window as { ran?: number }).ran)).toBeUndefined();
  expect(violations).toEqual([]);
});
