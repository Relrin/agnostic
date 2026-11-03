// CodeEditor and CelEditor in jsdom: typing reaches onChange, a new value from outside replaces the text without
// being reported as an edit, diagnostics and code-owned lines land where they belong, and CEL chips insert at the
// cursor.
import { EditorView } from "@codemirror/view";
import { render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { CelEditor, CodeEditor, type CelEditorHandle } from "./index";

beforeAll(() => {
  Object.defineProperty(Range.prototype, "getClientRects", {
    configurable: true,
    value: () => Object.assign([], { item: () => null }),
  });
  Object.defineProperty(Range.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => new DOMRect(),
  });
});

const SOURCE = [
  "from agno.agent import Agent",
  "",
  "agent = Agent(",
  '    name="triage",',
  "    pre_hooks=[check],",
  ")",
].join("\n");

function viewOf(element: HTMLElement): EditorView {
  const view = EditorView.findFromDOM(element);
  if (!view) throw new Error("no editor");
  return view;
}

describe("CodeEditor", () => {
  it("reports edits, not values set from outside, and shows diagnostics and code-owned lines", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <CodeEditor
        value={SOURCE}
        onChange={onChange}
        language="python"
        ariaLabel="agents/triage.py"
        diagnostics={[
          {
            line: 5,
            column: 4,
            endLine: 5,
            endColumn: 13,
            severity: "warning",
            message: "pre_hooks can't be stored",
          },
        ]}
        ownedLines={[{ from: 5, to: 5 }]}
        focusRange={{ from: 3, to: 6 }}
      />,
    );
    const content = await screen.findByRole("textbox", { name: "agents/triage.py" });
    expect(content).not.toHaveAttribute("aria-readonly", "true");
    await waitFor(() => {
      expect(content.querySelectorAll(".cm-line")).toHaveLength(6);
    });
    expect(content.querySelectorAll(".cm-line")[4]).toHaveClass("cm-owned-line");
    expect(content.querySelectorAll(".cm-focus-line")).toHaveLength(4);
    await waitFor(() => {
      expect(document.querySelector(".cm-lintRange-warning")).not.toBeNull();
    });

    const view = viewOf(content);
    view.dispatch({ changes: { from: view.state.doc.line(4).to, insert: "  # hand-tuned" } });
    expect(onChange).toHaveBeenLastCalledWith(
      SOURCE.replace('name="triage",', 'name="triage",  # hand-tuned'),
    );

    onChange.mockClear();
    rerender(
      <CodeEditor value={`${SOURCE}\n`} onChange={onChange} language="python" ariaLabel="agents/triage.py" />,
    );
    await waitFor(() => {
      expect(view.state.doc.toString()).toBe(`${SOURCE}\n`);
    });
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("CelEditor", () => {
  it("inserts a variable at the cursor and reports the expression", async () => {
    const onChange = vi.fn();
    const handle = createRef<CelEditorHandle>();
    render(
      <CelEditor
        ref={handle}
        value='.contains("refund")'
        onChange={onChange}
        ariaLabel="Selector expression"
        symbols={[
          { name: "input", detail: "string", doc: "The workflow's input as text.", kind: "variable" },
        ]}
        diagnostics={[{ from: 0, to: 1, severity: "error", message: "Expected a value" }]}
      />,
    );
    const content = await screen.findByRole("textbox", { name: "Selector expression" });
    const view = viewOf(content);
    view.dispatch({ selection: { anchor: 0 } });
    handle.current?.insert("input");
    expect(onChange).toHaveBeenLastCalledWith('input.contains("refund")');
    expect(content).toHaveTextContent('input.contains("refund")');
  });
});
