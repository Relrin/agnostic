import { defineConfig, devices } from "@playwright/test";

// E2E: runs against the Vite dev server with API calls stubbed per test. `yarn e2e` starts the server unless
// one is already running.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  // Chromium runs with its sandbox on (Playwright turns it off by default).
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    launchOptions: { chromiumSandbox: true },
  },
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.01 } },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
  ],
  webServer: {
    command: "yarn vite",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
