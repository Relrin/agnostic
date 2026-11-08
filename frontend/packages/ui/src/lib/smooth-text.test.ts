import { describe, expect, it } from "vitest";

import { markdownBlocks } from "../patterns/content";
import { nextReveal } from "./smooth-text";

describe("nextReveal", () => {
  it("finishes the word in progress", () => {
    expect(nextReveal("Hello wonderful world", 0, 8)).toBe(15);
  });

  it("never runs past the end", () => {
    expect(nextReveal("Hi", 0, 10)).toBe(2);
  });

  it("always moves forward", () => {
    expect(nextReveal("abc def", 0, 0)).toBe(3);
  });
});

describe("markdownBlocks", () => {
  it("splits at blank lines", () => {
    expect(markdownBlocks("# Title\n\nFirst.\n\nSecond.")).toEqual(["# Title\n", "First.\n", "Second."]);
  });

  it("keeps fenced code together across blank lines", () => {
    const source = "Intro\n\n```ts\nconst a = 1;\n\nconst b = 2;\n```\n\nAfter";
    expect(markdownBlocks(source)).toEqual([
      "Intro\n",
      "```ts\nconst a = 1;\n\nconst b = 2;\n```\n",
      "After",
    ]);
  });

  it("keeps an indented continuation with its list item", () => {
    expect(markdownBlocks("- item\n\n  more about it\n\nNext")).toEqual([
      "- item\n\n  more about it\n",
      "Next",
    ]);
  });
});
