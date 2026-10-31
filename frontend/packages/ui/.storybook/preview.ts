import "../src/styles/globals.css";

import type { Preview } from "@storybook/react-vite";

const preview: Preview = {
  parameters: {
    layout: "padded",
    backgrounds: { disable: true },
    // Every story is checked with axe; violations fail `yarn workspace @agnostic/ui storybook:test` (WCAG 2.2 AA).
    a11y: { test: "error" },
  },
};

export default preview;
