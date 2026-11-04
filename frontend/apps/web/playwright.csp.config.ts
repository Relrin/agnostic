import { defineConfig, devices } from "@playwright/test";

// The production build under the production security headers (`vite preview`), so a page that trips the content
// security policy or Trusted Types fails here rather than in a customer's browser. `yarn e2e:csp`.
export default defineConfig({
  testDir: "./e2e-csp",
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never", outputFolder: "playwright-report-csp" }]]
    : "list",
  use: {
    baseURL: "http://localhost:4173",
    trace: "on-first-retry",
    launchOptions: { chromiumSandbox: true },
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
  ],
  webServer: {
    command: "yarn vite build && yarn vite preview --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
});
