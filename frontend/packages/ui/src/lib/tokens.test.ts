// Automated contrast test: every text/background pair the design relies on meets its ratio, and
// the TypeScript mirror of the tokens matches tokens.css.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { allColors, contrastPairs, contrastRatio } from "./tokens";

// Vitest runs from the frontend root (or packages/ui when run there).
const cssPath = ["packages/ui/src/styles/tokens.css", "src/styles/tokens.css"]
  .map((relative) => join(process.cwd(), relative))
  .find((candidate) => existsSync(candidate));
const css = cssPath ? readFileSync(cssPath, "utf8") : "";

describe("design tokens", () => {
  it.each(contrastPairs)("$fg on $bg meets $min:1", ({ fg, bg, min }) => {
    const foreground = allColors[fg];
    const background = allColors[bg];
    expect(foreground).toBeDefined();
    expect(background).toBeDefined();
    expect(contrastRatio(foreground ?? "", background ?? "")).toBeGreaterThanOrEqual(min);
  });

  it.each(Object.entries(allColors))("%s matches tokens.css", (name, hex) => {
    expect(css).toContain(`${name}: ${hex.toLowerCase()};`);
  });

  it("computes WCAG ratios", () => {
    expect(contrastRatio("#000000", "#FFFFFF")).toBeCloseTo(21, 1);
    expect(contrastRatio("#777777", "#777777")).toBe(1);
  });
});
