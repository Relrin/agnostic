// Storybook stories as browser tests (Playwright/Chromium): renders every story and runs the a11y checks.
import { storybookTest } from "@storybook/addon-vitest/vitest-plugin";
import tailwindcss from "@tailwindcss/vite";
import { playwright } from "@vitest/browser-playwright";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tailwindcss(), storybookTest({ configDir: ".storybook" })],
  test: {
    name: "storybook",
    browser: { enabled: true, headless: true, provider: playwright(), instances: [{ browser: "chromium" }] },
    setupFiles: [".storybook/vitest.setup.ts"],
  },
});
