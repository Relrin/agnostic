// A Jupyter notebook, read-only, rendered by jupyter-kit: Markdown cells, code cells with their saved outputs (text,
// HTML, images, SVG, tracebacks), Python highlighting and KaTeX math. Nothing in the notebook runs: no kernel or
// executor is attached and no editor is loaded.
//
// jupyter-kit writes its HTML as strings. Each one goes through `filterHtml` first: DOMPurify strips anything that
// runs or loads, and `sanitizedHtml` lets the app's Trusted Types policy accept exactly that result.
import "katex/dist/katex.min.css";
import "@jupyter-kit/theme-onedork/syntax/one-dark.css";
import "./notebook.css";

import type { HtmlFilter, Ipynb, Plugin, SaveHandler } from "@jupyter-kit/core";
import { Notebook } from "@jupyter-kit/react";
import createDOMPurify, { type Config } from "dompurify";

import { sanitizedHtml } from "../trusted-html";
import { katexMath } from "./notebook-math";
import { pythonHighlighting } from "./notebook-highlight";

const purify = createDOMPurify(window);

const CONFIG: Config = {
  // Nothing that restyles the app, takes input, embeds another document or changes how URLs resolve.
  FORBID_TAGS: [
    "style",
    "link",
    "meta",
    "base",
    "form",
    "input",
    "button",
    "textarea",
    "select",
    "option",
    "iframe",
    "frame",
    "object",
    "embed",
    "dialog",
    "template",
    "slot",
  ],
  FORBID_ATTR: ["autofocus", "formaction", "srcset", "ping"],
  ADD_ATTR: ["target"],
  // No policy of DOMPurify's own (the content security policy allows only the app's): the parse of the input
  // goes through the app's policy, which accepts it while `sanitizedHtml` runs.
  TRUSTED_TYPES_POLICY: null,
};

/** Attributes that load something; on anything but a link only embedded data and in-document references stay. */
const LOADING_ATTRIBUTES = ["src", "href", "xlink:href", "poster", "background", "data"];

function embedded(value: string): boolean {
  const url = value.trim().toLowerCase();
  return url.startsWith("data:image/") || url.startsWith("#");
}

purify.addHook("afterSanitizeAttributes", (node) => {
  if (!(node instanceof Element)) return;
  if (node.tagName === "A" && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  } else {
    // Remote images and fonts would be refused by the content security policy anyway; dropping them here keeps
    // the console free of violations and the notebook from calling out.
    for (const name of LOADING_ATTRIBUTES) {
      const value = node.getAttribute(name);
      if (value !== null && !embedded(value)) node.removeAttribute(name);
    }
  }
  const style = node.getAttribute("style");
  if (style && /url\s*\(|@import|expression\s*\(/i.test(style)) node.removeAttribute("style");
});

/** Sanitize HTML jupyter-kit is about to write, and let the policy accept it. */
export const filterHtml: HtmlFilter = (html) =>
  sanitizedHtml(html, (dirty) => purify.sanitize(dirty, CONFIG));

// Module-scoped: the renderer is rebuilt whenever one of these changes identity.
const PLUGINS: Plugin[] = [pythonHighlighting, katexMath];

/** Ctrl/Cmd+S in a notebook would download it; Download is in the toolbar already. */
const ignoreSave: SaveHandler = () => undefined;

/** The kernel language the notebook was saved with, for highlighting. */
export function notebookLanguage(notebook: Ipynb): string {
  const metadata = notebook.metadata as
    { language_info?: { name?: unknown }; kernelspec?: { language?: unknown } } | undefined;
  const name = metadata?.language_info?.name ?? metadata?.kernelspec?.language;
  return typeof name === "string" && name ? name.toLowerCase() : "python";
}

export function NotebookView({ notebook, filename }: { notebook: Ipynb; filename: string }) {
  return (
    <section className="notebook-view" aria-label={`Notebook ${filename}`}>
      <Notebook
        ipynb={notebook}
        language={notebookLanguage(notebook)}
        plugins={PLUGINS}
        htmlFilter={filterHtml}
        onSave={ignoreSave}
        filename={filename}
      />
    </section>
  );
}
