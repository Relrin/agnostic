// Coding tool calls: a shell command with its output tail and exit code, a written file's first lines, an edit as a
// line diff (Pi's and OpenCode's argument names), compact reads, and the chip for any other tool.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  BASH_TAIL_LINES,
  CodingToolCall,
  WRITE_PREVIEW_LINES,
  editPairs,
  lineDiff,
  splitExitCode,
} from "./coding-tools";

function numbered(count: number): string {
  return Array.from({ length: count }, (_, index) => `line ${String(index + 1)}`).join("\n");
}

describe("lineDiff", () => {
  it("keeps common lines and marks the rest", () => {
    expect(lineDiff("a\nb\nc\n", "a\nB\nc\nd\n")).toEqual([
      { kind: "context", text: "a" },
      { kind: "remove", text: "b" },
      { kind: "add", text: "B" },
      { kind: "context", text: "c" },
      { kind: "add", text: "d" },
    ]);
  });

  it("handles empty sides", () => {
    expect(lineDiff("", "new")).toEqual([{ kind: "add", text: "new" }]);
    expect(lineDiff("old", "")).toEqual([{ kind: "remove", text: "old" }]);
  });
});

describe("editPairs", () => {
  it("reads Pi's and OpenCode's argument names", () => {
    expect(editPairs({ path: "a", oldText: "x", newText: "y" })).toEqual([{ before: "x", after: "y" }]);
    expect(editPairs({ filePath: "a", oldString: "x", newString: "y" })).toEqual([
      { before: "x", after: "y" },
    ]);
    expect(
      editPairs({
        path: "a",
        edits: [
          { oldText: "1", newText: "2" },
          { oldText: "3", newText: "4" },
        ],
      }),
    ).toHaveLength(2);
  });
});

describe("splitExitCode", () => {
  it("strips the trailing marker", () => {
    expect(splitExitCode("boom\n[exit code 2]")).toEqual({ output: "boom", exitCode: 2 });
    expect(splitExitCode("fine\n")).toEqual({ output: "fine\n", exitCode: undefined });
  });
});

describe("CodingToolCall", () => {
  it("shows a shell command, the tail of its output and a failing exit code", () => {
    render(
      <CodingToolCall
        name="bash"
        status="done"
        duration="0.3s"
        args={{ command: "make test" }}
        result={`${numbered(BASH_TAIL_LINES + 5)}\n[exit code 2]`}
      />,
    );
    const card = screen.getByRole("group", { name: "bash: make test" });
    expect(within(card).getByLabelText("Command")).toHaveTextContent("$ make test");
    const output = within(card).getByLabelText("Output");
    expect(output).toHaveTextContent("… 5 earlier lines");
    expect(output.textContent).not.toMatch(/line 5\b/);
    expect(output).toHaveTextContent(`line ${String(BASH_TAIL_LINES + 5)}`);
    expect(output).not.toHaveTextContent("[exit code");
    expect(within(card).getByText("exit 2")).toBeInTheDocument();
  });

  it("reports exit 0 for a command that passed", () => {
    render(<CodingToolCall name="bash" status="done" args={{ command: "true" }} result="" />);
    expect(screen.getByText("exit 0")).toBeInTheDocument();
    expect(screen.queryByLabelText("Output")).not.toBeInTheDocument();
  });

  it("previews the first lines of a written file", () => {
    render(
      <CodingToolCall
        name="write"
        status="done"
        args={{ path: "outputs/report.md", content: numbered(WRITE_PREVIEW_LINES + 3) }}
      />,
    );
    const card = screen.getByRole("group", { name: "write: outputs/report.md" });
    const contents = within(card).getByLabelText("Contents of outputs/report.md");
    expect(contents).toHaveTextContent(`line ${String(WRITE_PREVIEW_LINES)}`);
    expect(contents).not.toHaveTextContent(`line ${String(WRITE_PREVIEW_LINES + 1)}`);
    expect(contents).toHaveTextContent("… 3 more lines");
    expect(within(card).getByText(`${String(WRITE_PREVIEW_LINES + 3)} lines`)).toBeInTheDocument();
  });

  it("draws an OpenCode edit as a unified diff", () => {
    render(
      <CodingToolCall
        name="edit"
        status="done"
        args={{
          filePath: "src/volume.py",
          oldString: "def total(rows):\n    return sum(rows)",
          newString: "def total(rows: list[int]) -> int:\n    return sum(rows)",
        }}
      />,
    );
    const diff = screen.getByLabelText("Diff of src/volume.py");
    const removed = diff.querySelectorAll('[data-diff="remove"]');
    const added = diff.querySelectorAll('[data-diff="add"]');
    expect([...removed].map((line) => line.textContent)).toEqual(["-def total(rows):"]);
    expect([...added].map((line) => line.textContent)).toEqual(["+def total(rows: list[int]) -> int:"]);
    expect(diff.querySelectorAll('[data-diff="context"]')).toHaveLength(1);
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("−1")).toBeInTheDocument();
  });

  it("shows reads and searches on one line", () => {
    render(
      <CodingToolCall name="grep" status="done" args={{ pattern: "TODO", path: "src" }} result={"a\nb"} />,
    );
    const card = screen.getByRole("group", { name: "grep: TODO in src" });
    expect(within(card).getByText("2 lines")).toBeInTheDocument();
  });

  it("falls back to the chip for other tools, without the MCP prefix", () => {
    render(<CodingToolCall name="mcp__agnostic__kb_lookup" status="done" duration="0.6s" args={{}} />);
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(screen.getByText("kb_lookup")).toBeInTheDocument();
  });
});
