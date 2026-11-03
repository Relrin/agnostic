// CodeView in jsdom: lines render after the lazy chunk loads; marks, focus and notes land on the right lines, and
// prop changes update them in place.
import { EditorView } from "@codemirror/view";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { CodeView, CodeViewSkeleton } from "./index";

const SOURCE = [
  "from agno.agent import Agent",
  "",
  "agent = Agent(",
  '    name="support-triage",',
  '    model="gpt-5",',
  ")",
].join("\n");

beforeAll(() => {
  // jsdom has no layout: CodeMirror measures with these and copes with empty answers.
  Object.defineProperty(Range.prototype, "getClientRects", {
    configurable: true,
    value: () => Object.assign([], { item: () => null }),
  });
  Object.defineProperty(Range.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => new DOMRect(),
  });
});

async function mounted(): Promise<HTMLElement> {
  const content = await screen.findByRole("textbox", { name: "Generated code" });
  await waitFor(() => {
    expect(content.querySelectorAll(".cm-line")).toHaveLength(6);
  });
  return content;
}

function line(content: HTMLElement, number: number): Element {
  const element = content.querySelectorAll(".cm-line")[number - 1];
  if (!element) throw new Error(`no line ${String(number)}`);
  return element;
}

describe("CodeView", () => {
  it("renders read-only code with line numbers", async () => {
    render(<CodeView value={SOURCE} language="python" ariaLabel="Generated code" />);
    const content = await mounted();
    expect(content).toHaveAttribute("aria-readonly", "true");
    expect(content).toHaveAttribute("contenteditable", "true");
    expect(line(content, 4)).toHaveTextContent('name="support-triage",');
    const numbers = [...document.querySelectorAll(".cm-lineNumbers .cm-gutterElement")].map(
      (element) => element.textContent,
    );
    expect(numbers).toContain("6");
  });

  it("marks changed lines and the focused line, and updates them when props change", async () => {
    const { rerender } = render(
      <CodeView
        value={SOURCE}
        language="python"
        marks={{ 4: "modified", 5: "added" }}
        focusLine={4}
        ariaLabel="Generated code"
      />,
    );
    const content = await mounted();
    expect(document.querySelectorAll(".cm-change-modified")).toHaveLength(1);
    expect(document.querySelectorAll(".cm-change-added")).toHaveLength(1);
    expect(line(content, 4)).toHaveClass("cm-focus-line");

    rerender(
      <CodeView
        value={SOURCE}
        language="python"
        marks={{ 3: "added" }}
        focusLine={5}
        ariaLabel="Generated code"
      />,
    );
    await waitFor(() => {
      expect(line(content, 5)).toHaveClass("cm-focus-line");
    });
    expect(line(content, 4)).not.toHaveClass("cm-focus-line");
    expect(document.querySelectorAll(".cm-change-modified")).toHaveLength(0);
    expect(document.querySelectorAll(".cm-change-added")).toHaveLength(1);
  });

  it("shows notes under their line with an underlined range and an action link", async () => {
    render(
      <CodeView
        value={SOURCE}
        language="python"
        notes={[
          {
            line: 5,
            from: 10,
            to: 17,
            text: "gpt-5 isn't in this instance's model registry.",
            action: { label: "Open models", href: "/i/prod/models" },
          },
        ]}
        ariaLabel="Generated code"
      />,
    );
    const content = await mounted();
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("gpt-5 isn't in this instance's model registry.");
    expect(screen.getByRole("link", { name: "Open models" })).toHaveAttribute("href", "/i/prod/models");
    expect(line(content, 5).querySelector(".cm-note-mark")).toHaveTextContent('"gpt-5"');
  });

  it("replaces the document when the value changes", async () => {
    const { rerender } = render(<CodeView value={SOURCE} language="python" ariaLabel="Generated code" />);
    const content = await mounted();
    rerender(<CodeView value={'{\n  "a": 1\n}'} language="json" ariaLabel="Generated code" />);
    await waitFor(() => {
      expect(content.querySelectorAll(".cm-line")).toHaveLength(3);
    });
    expect(line(content, 2)).toHaveTextContent('"a": 1');
  });

  it("reports the cursor position", async () => {
    const onCursor = vi.fn();
    render(<CodeView value={SOURCE} language="python" onCursor={onCursor} ariaLabel="Generated code" />);
    const content = await mounted();
    const editor = content.closest<HTMLElement>(".cm-editor");
    const view = editor ? EditorView.findFromDOM(editor) : null;
    if (!view) throw new Error("no editor view");
    view.dispatch({ selection: { anchor: view.state.doc.line(3).from + 2 } });
    await waitFor(() => {
      expect(onCursor).toHaveBeenCalledWith(3, 3);
    });
  });
});

describe("CodeViewSkeleton", () => {
  it("is a status placeholder", () => {
    render(<CodeViewSkeleton lines={3} />);
    expect(screen.getByRole("status", { name: "Loading code" })).toBeInTheDocument();
  });
});
