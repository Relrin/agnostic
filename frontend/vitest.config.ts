// Unit tests for every workspace (jsdom). Storybook a11y/interaction tests run as a separate browser project in
// packages/ui (yarn workspace @agnostic/ui storybook:test).
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    name: "unit",
    environment: "jsdom",
    include: ["{apps,packages,modules}/*/src/**/*.test.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
    // Page tests that click through whole flows take 2–3 s alone and about twice that with every file in parallel.
    testTimeout: 15_000,
    css: false,
    coverage: {
      provider: "v8",
      include: ["{apps,packages,modules}/*/src/**/*.{ts,tsx}"],
      exclude: [
        "**/*.stories.tsx",
        "**/*.test.{ts,tsx}",
        "packages/api/src/generated/**",
        "packages/api/src/agentos/**",
      ],
    },
  },
});
