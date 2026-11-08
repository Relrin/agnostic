import type { Ipynb } from "@jupyter-kit/core";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { acceptsHtml, clearSanitizedHtml } from "../trusted-html";
import { highlightPython, isPython } from "./notebook-highlight";
import { typesetMath } from "./notebook-math";
import { filterHtml, notebookLanguage, NotebookView } from "./notebook-view";
import { parseNotebook } from "./viewer";

const NOTEBOOK: Ipynb = {
  metadata: { language_info: { name: "python" } },
  cells: [
    {
      cell_type: "markdown",
      source: ["# Revenue review\n", "\n", "Growth is $g = \\frac{r_1}{r_0} - 1$."],
      metadata: {},
    },
    {
      cell_type: "code",
      execution_count: 3,
      source: ["def growth(a, b):\n", "    return b / a - 1"],
      metadata: {},
      outputs: [
        { output_type: "stream", name: "stdout", text: ["computed\n"] },
        {
          output_type: "execute_result",
          execution_count: 3,
          metadata: {},
          data: {
            "text/html": [
              "<table><tr><td>0.12</td></tr></table>",
              "<script>window.ran = true</script>",
              '<img src="https://tracker.example/p.gif" onerror="window.ran = true">',
            ],
            "text/plain": ["0.12"],
          },
        },
      ],
    },
  ],
} as unknown as Ipynb;

afterEach(() => {
  clearSanitizedHtml();
});

describe("notebook highlighting", () => {
  it("knows the names Python kernels use", () => {
    expect(isPython("python3")).toBe(true);
    expect(isPython("IPython")).toBe(true);
    expect(isPython("r")).toBe(false);
    expect(isPython(undefined)).toBe(false);
  });

  it("splits code into token spans and keeps the text", () => {
    const code = document.createElement("code");
    code.textContent = "def f(x):\n    return 'a'  # note";
    highlightPython(code);
    expect(code.textContent).toBe("def f(x):\n    return 'a'  # note");
    expect(code.querySelector(".tok-keyword")?.textContent).toBe("def");
    expect(code.querySelector(".tok-string")?.textContent).toBe("'a'");
    expect(code.querySelector(".tok-comment")?.textContent).toBe("# note");
  });
});

describe("notebook math", () => {
  it("typesets inline and display formulas with KaTeX", () => {
    const root = document.createElement("div");
    const inline = document.createElement("code");
    inline.className = "language-math math-inline";
    inline.textContent = "x^2";
    const pre = document.createElement("pre");
    const display = document.createElement("code");
    display.className = "language-math math-display";
    display.textContent = "\\sum_i x_i";
    pre.append(display);
    root.append(inline, pre);
    typesetMath(root);
    expect(root.querySelector("span.math-inline .katex")).not.toBeNull();
    expect(root.querySelector("div.math-display .katex-display")).not.toBeNull();
    expect(root.querySelector("pre, code")).toBeNull();
  });
});

describe("notebook HTML filter", () => {
  it("strips what runs or loads, and lets the policy accept the result once", () => {
    const html = filterHtml(
      '<p onclick="x()">hi</p><script>x()</script><style>body{display:none}</style>' +
        '<img src="https://tracker.example/p.gif"><img src="data:image/png;base64,AAAA">' +
        '<a href="https://example.com">link</a><a href="javascript:x()">bad</a>',
    );
    expect(html).not.toMatch(/onclick|<script|<style|tracker\.example|javascript:/);
    expect(html).toContain('src="data:image/png;base64,AAAA"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(acceptsHtml(html, "Element innerHTML")).toBe(true);
    expect(acceptsHtml(html, "Element innerHTML")).toBe(false);
  });
});

describe("parseNotebook", () => {
  it("reads nbformat JSON and refuses anything else", () => {
    expect(parseNotebook(JSON.stringify(NOTEBOOK))?.cells).toHaveLength(2);
    expect(parseNotebook("{")).toBeUndefined();
    expect(parseNotebook('{"name": "not a notebook"}')).toBeUndefined();
  });

  it("picks the kernel language for highlighting", () => {
    expect(notebookLanguage(NOTEBOOK)).toBe("python");
    expect(notebookLanguage({ cells: [], metadata: { kernelspec: { language: "R" } } })).toBe("r");
    expect(notebookLanguage({ cells: [] })).toBe("python");
  });
});

describe("NotebookView", () => {
  it("renders cells read-only, highlighted, with math and sanitized outputs", async () => {
    render(<NotebookView notebook={NOTEBOOK} filename="review.ipynb" />);
    const view = screen.getByRole("region", { name: "Notebook review.ipynb" });
    expect(await screen.findByRole("heading", { name: "Revenue review" })).toBeInTheDocument();
    await waitFor(() => {
      expect(view.querySelector(".katex")).not.toBeNull();
    });
    expect(view.querySelector(".tok-keyword")?.textContent).toBe("def");
    expect(view).toHaveTextContent("In [3]:");
    expect(view).toHaveTextContent("computed");
    expect(view.querySelector(".output_html td")?.textContent).toBe("0.12");
    expect(view.querySelector("script, [onerror], textarea, [contenteditable]")).toBeNull();
    expect(view.querySelector('img[src^="https:"]')).toBeNull();
    expect((window as { ran?: boolean }).ran).toBeUndefined();
  });
});
