// TeX in notebook markdown and LaTeX outputs, typeset by KaTeX (bundled, nothing loaded from a CDN).
//
// remark-math marks `$…$` and `$$…$$` so Markdown leaves them alone; they reach the page as `code.language-math`
// elements holding the TeX as text. After a cell renders, each is replaced by KaTeX's own DOM rendering:
// `katex.render` builds elements rather than writing HTML, so the Trusted Types policy is not involved.
import { remarkLatexEnvironment, remarkPromoteDisplayMath, type Plugin } from "@jupyter-kit/core";
import katex from "katex";
import remarkMath from "remark-math";

/** `eqnarray` is not in KaTeX; `aligned` lays it out the same way. */
function eqnarrayAsAligned() {
  const visit = (node: { value?: unknown; children?: unknown[] }) => {
    if (typeof node.value === "string")
      node.value = node.value
        .replace(/\\begin\{eqnarray\*?\}/g, "\\begin{aligned}")
        .replace(/\\end\{eqnarray\*?\}/g, "\\end{aligned}");
    for (const child of node.children ?? []) visit(child as typeof node);
  };
  return visit;
}

/** Typeset every math element under `root`. A formula KaTeX cannot parse is shown as its source, in red. */
export function typesetMath(root: HTMLElement): void {
  for (const code of root.querySelectorAll<HTMLElement>("code.language-math")) {
    const display = code.classList.contains("math-display");
    const block = display && code.parentElement?.tagName === "PRE" ? code.parentElement : code;
    const target = document.createElement(display ? "div" : "span");
    target.className = display ? "math math-display" : "math math-inline";
    katex.render(code.textContent, target, {
      displayMode: display,
      throwOnError: false,
      trust: false,
      strict: "ignore",
      output: "htmlAndMathml",
    });
    block.replaceWith(target);
  }
}

export const katexMath: Plugin = {
  name: "agnostic-katex",
  remarkPlugins: [eqnarrayAsAligned, remarkLatexEnvironment, remarkMath, remarkPromoteDisplayMath],
  onMarkdownRendered(element) {
    typesetMath(element);
  },
};
