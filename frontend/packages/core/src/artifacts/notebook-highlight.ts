// Python highlighting for notebook code cells, built as DOM nodes.
//
// jupyter-kit can highlight cells itself, but it writes the result as an HTML string, which the app's Trusted Types
// policy refuses. So no language is registered with it: cells arrive as plain text, and this plugin tokenizes them
// with the same Lezer grammar and class names (`tok-*`, styled by the syntax theme), creating elements and text
// nodes instead of HTML.
import type { Plugin } from "@jupyter-kit/core";
import { classHighlighter, highlightCode } from "@lezer/highlight";
import { parser } from "@lezer/python";

/** Kernel language names that mean Python. */
const PYTHON = new Set(["python", "python3", "py", "ipython", "ipython3"]);

export function isPython(language: string | null | undefined): boolean {
  return PYTHON.has((language ?? "").toLowerCase());
}

/** Replace `code`'s text with highlighted spans of the same text. */
export function highlightPython(code: HTMLElement): void {
  const source = code.textContent;
  if (!source) return;
  const fragment = document.createDocumentFragment();
  highlightCode(
    source,
    parser.parse(source),
    classHighlighter,
    (text, classes) => {
      if (!classes) {
        fragment.append(document.createTextNode(text));
        return;
      }
      const span = document.createElement("span");
      span.className = classes;
      span.textContent = text;
      fragment.append(span);
    },
    () => {
      fragment.append(document.createTextNode("\n"));
    },
  );
  code.replaceChildren(fragment);
}

export const pythonHighlighting: Plugin = {
  name: "agnostic-python-highlighting",
  onCodeBlock(code, language) {
    if (isPython(language)) highlightPython(code);
  },
};
