// A coding agent's tool calls: a passing and a failing shell command, a file written, an edit as a diff (Pi's
// oldText/newText and OpenCode's oldString/newString), the compact read and search rows, and an MCP tool that falls
// back to the plain chip.
import type { Meta, StoryObj } from "@storybook/react-vite";

import { CodingToolCall } from "../domain/coding-tools";

const meta = {
  title: "Operate/Coding tool calls",
  component: CodingToolCall,
  decorators: [
    (Story) => (
      <div className="flex max-w-3xl flex-col gap-2 p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof CodingToolCall>;
export default meta;
type Story = StoryObj<typeof meta>;

const report = [
  "# Support volume",
  "",
  "| Quarter | Tickets |",
  "|---|---|",
  "| Q1 | 61 |",
  "| Q2 | 82 |",
].join("\n");

export const Bash: Story = {
  args: {
    name: "bash",
    status: "done",
    duration: "1.2s",
    args: { command: "python -m pytest -q tests/test_volume.py" },
    result: "....                                                   [100%]\n4 passed in 0.31s\n",
  },
};

export const BashFailed: Story = {
  args: {
    name: "bash",
    status: "done",
    duration: "0.4s",
    args: { command: "ls outputs/missing" },
    result: "ls: cannot access 'outputs/missing': No such file or directory\n[exit code 2]",
  },
};

export const BashRunning: Story = {
  args: { name: "bash", status: "running", args: { command: "npm install" } },
};

export const Write: Story = {
  args: {
    name: "write",
    status: "done",
    duration: "0.1s",
    args: { path: "outputs/report.md", content: report },
  },
};

export const EditPi: Story = {
  args: {
    name: "edit",
    status: "done",
    duration: "0.1s",
    args: {
      path: "outputs/report.md",
      oldText: "| Q2 | 82 |",
      newText: "| Q2 | 82 |\n| Q3 | 97 |",
    },
  },
};

export const EditOpenCode: Story = {
  args: {
    name: "edit",
    status: "done",
    args: {
      filePath: "src/volume.py",
      oldString: "def total(rows):\n    return sum(rows)\n",
      newString: "def total(rows: list[int]) -> int:\n    return sum(rows)\n",
    },
  },
};

export const Compact: Story = {
  args: {
    name: "read",
    status: "done",
    duration: "0.0s",
    args: { path: "data/tickets.csv" },
    result: "a\nb\nc",
  },
  render: (args) => (
    <>
      <CodingToolCall {...args} />
      <CodingToolCall name="grep" status="done" args={{ pattern: "TODO", path: "src" }} result="src/a.py:3" />
      <CodingToolCall name="find" status="done" args={{ pattern: "*.csv" }} result="data/tickets.csv" />
      <CodingToolCall name="ls" status="running" args={{}} />
    </>
  ),
};

export const McpTool: Story = {
  args: { name: "mcp__agnostic__kb_lookup", status: "done", duration: "0.6s", args: { query: "refunds" } },
};
