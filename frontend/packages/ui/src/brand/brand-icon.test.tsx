// Logos draw in their brand's colors by default: a single brand color, or their own paths and gradients with ids
// unique to each instance; a brand too dark for the theme, and the monochrome tone, draw in the text color.
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrandIcon } from "./brand-icon";

describe("BrandIcon", () => {
  it("fills a simple logo with its brand color", () => {
    const { container } = render(<BrandIcon brand="discord" />);
    expect(container.querySelector("svg")).toHaveAttribute("data-tone", "color");
    expect(container.querySelector("path")).toHaveAttribute("fill", "#5865F2");
  });

  it("keeps a brand too dark for the theme in the text color", () => {
    const { container } = render(<BrandIcon brand="github" />);
    expect(container.querySelector("path")).toHaveAttribute("fill", "currentColor");
  });

  it("gives each instance its own gradient ids", () => {
    const { container } = render(
      <>
        <BrandIcon brand="gemini" />
        <BrandIcon brand="gemini" />
      </>,
    );
    const ids = [...container.querySelectorAll("linearGradient")].map((gradient) => gradient.id);
    expect(ids.length).toBeGreaterThan(1);
    expect(new Set(ids).size).toBe(ids.length);
    const [first] = container.querySelectorAll("svg");
    const references = [...(first?.querySelectorAll("path") ?? [])]
      .map((path) => /^url\(#(.+)\)$/.exec(path.getAttribute("fill") ?? "")?.[1])
      .filter(Boolean);
    for (const reference of references)
      expect(first?.querySelector(`[id="${String(reference)}"]`)).not.toBeNull();
  });

  it("draws in the text color when asked", () => {
    const { container } = render(<BrandIcon brand="discord" tone="mono" />);
    expect(container.querySelector("svg")).toHaveAttribute("data-tone", "mono");
    expect(container.querySelector("path")).not.toHaveAttribute("fill");
  });
});
