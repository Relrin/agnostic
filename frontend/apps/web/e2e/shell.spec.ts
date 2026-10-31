import { expect, test, type Page } from "@playwright/test";

const greetings = {
  data: [
    {
      id: "hel_01M6A0EEZEQ373S26F20142FZ5",
      message: "Hi from Dana",
      status: "replied",
      reply: "Hello! You said: “Hi from Dana” (3 words).",
      created_at: "2026-10-31T09:12:00Z",
      updated_at: "2026-10-31T09:12:01Z",
    },
  ],
  next_cursor: null,
};

async function stubApi(page: Page) {
  await page.route("**/readyz", (route) => route.fulfill({ json: { status: "ready", checks: [] } }));
  await page.route(/\/api\/v1\/hello\/greetings/, (route) => route.fulfill({ json: greetings }));
}

test("redirects to the instance home and renders the shell", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/i\/dev-prod\/home$/);
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
  await expect(page.getByRole("button", { name: "Switch AgentOS instance" })).toContainText("dev-prod");
  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
});

test("hello page reads from the API", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/dev-prod/hello");
  await expect(page.getByText("Hi from Dana", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Hello" })).toHaveAttribute("aria-current", "page");
});

test("command palette jumps to a page", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/dev-prod/home");
  await page.getByRole("button", { name: /Search or jump to/ }).click();
  await page.getByPlaceholder("Search or jump to…").fill("hello");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/i\/dev-prod\/hello$/);
});

test("sidebar matches the visual baseline @visual", async ({ page }) => {
  await stubApi(page);
  await page.goto("/i/dev-prod/approvals");
  await expect(page.getByRole("heading", { name: "Approvals" })).toBeVisible();
  await expect(page.locator("aside")).toHaveScreenshot("sidebar.png");
});
