// Workflow builder building blocks with the ticket router's steps: component nodes of every primitive and run
// status, group frames, the input and output nodes, a sticky note, the port legend, branch labels, the insert
// button and palette items.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import {
  BranchLabel,
  FlowIoNode,
  FlowNodeFrame,
  GroupFrame,
  InsertButton,
  PaletteItem,
  PortLegend,
  StickyNote,
  portDotStyle,
  type FlowRow,
} from "../domain/workflow";

const meta = {
  title: "Studio/Workflow builder",
  decorators: [
    (Story) => (
      <div className="flex flex-col gap-4 bg-canvas p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const dot = (row: Extract<FlowRow, { kind: "in" | "out" }>) => (
  <span
    aria-hidden
    className="absolute top-1/2 -translate-y-1/2"
    style={{ ...portDotStyle(row.port, true), [row.kind === "in" ? "left" : "right"]: -7 }}
  />
);

const classify: FlowRow[] = [
  { kind: "desc", text: "Agent · support-triage" },
  { kind: "in", id: "in", label: "Input", port: "message" },
  { kind: "field", label: "Model", value: "claude-opus-5-5" },
  { kind: "field", label: "Tools", value: "kb_lookup, zendesk_search" },
  { kind: "sep" },
  { kind: "out", id: "out", label: "Response", port: "message" },
];
const router: FlowRow[] = [
  { kind: "desc", text: "Router · runs exactly one choice" },
  { kind: "in", id: "in", label: "Input", port: "message" },
  {
    kind: "area",
    label: "Selector · CEL",
    lines: ['input.contains("refund")', '|| input.contains("invoice")', '? "Billing"', ': "Draft & review"'],
  },
  { kind: "out", id: "choices[0]", label: "Billing", port: "route" },
  { kind: "out", id: "choices[1]", label: "Investigate", port: "route" },
  { kind: "out", id: "choices[2]", label: "Draft & review", port: "route" },
];

export const ComponentNodes: Story = {
  render: function Render() {
    const [selected, setSelected] = useState("Route by category");
    return (
      <div className="flex flex-wrap items-start gap-6 px-2">
        <FlowNodeFrame
          type="Step"
          executor="agent"
          title="Classify ticket"
          rows={classify}
          chip="agent · support-triage"
          meta="avg 1.1 s"
          selected={selected === "Classify ticket"}
          onSelect={() => {
            setSelected("Classify ticket");
          }}
          renderPort={dot}
        />
        <FlowNodeFrame
          type="Router"
          title="Route by category"
          rows={router}
          chip='cel · input.contains("refund") || …'
          meta="3 choices"
          selected={selected === "Route by category"}
          onSelect={() => {
            setSelected("Route by category");
          }}
          renderPort={dot}
        />
      </div>
    );
  },
};

export const RunStatus: Story = {
  render: () => {
    const rows: FlowRow[] = [
      { kind: "in", id: "in", label: "Input", port: "message" },
      { kind: "out", id: "out", label: "Response", port: "message" },
    ];
    return (
      <div className="flex flex-wrap items-start gap-6 px-2">
        <FlowNodeFrame
          type="Step"
          executor="agent"
          title="Classify ticket"
          rows={rows}
          status="done"
          time="1.1 s"
        />
        <FlowNodeFrame type="Step" executor="agent" title="Billing" rows={rows} status="running" />
        <FlowNodeFrame type="Step" executor="team" title="Escalate" rows={rows} status="paused" />
        <FlowNodeFrame
          type="Step"
          executor="function"
          title="Send reply"
          rows={rows}
          status="failed"
          problems={1}
        />
      </div>
    );
  },
};

export const GroupsAndEnds: Story = {
  render: () => (
    <div className="flex flex-wrap items-start gap-6 px-2">
      <FlowIoNode kind="input" title="Workflow input" description="Start · input" />
      <GroupFrame
        type="Parallel"
        title="Investigate"
        label="PARALLEL"
        meta="2 branches"
        width={300}
        height={140}
      />
      <GroupFrame
        type="Loop"
        title="Draft & review"
        label="LOOP · MAX 3"
        footer='until last_step_content.contains("APPROVED")'
        width={300}
        height={140}
      />
      <FlowIoNode kind="output" title="Workflow output" description="The last step's response" />
    </div>
  ),
};

export const NotesAndLegend: Story = {
  render: function Render() {
    const [text, setText] = useState(
      "The router reads the classifier's answer. Keep route names in sync with its categories.",
    );
    return (
      <div className="flex flex-wrap items-start gap-6">
        <StickyNote text={text} onChange={setText} onDelete={() => undefined} />
        <PortLegend types={["message", "data", "route"]} />
      </div>
    );
  },
};

export const BranchesAndInsert: Story = {
  render: function Render() {
    const [count, setCount] = useState(0);
    return (
      <div className="flex flex-wrap items-center gap-3">
        <BranchLabel tone="choice">Billing</BranchLabel>
        <BranchLabel tone="true">true</BranchLabel>
        <BranchLabel tone="else">else</BranchLabel>
        <InsertButton
          onInsert={() => {
            setCount((current) => current + 1);
          }}
        />
        <span className="text-[12px] text-fg-muted">{`${String(count)} inserted`}</span>
      </div>
    );
  },
};

export const Palette: Story = {
  render: () => (
    <div className="flex w-52 flex-col gap-0.5">
      <PaletteItem
        type="Router"
        name="Router"
        description="Pick one choice by selector"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
      <PaletteItem
        type="Loop"
        name="Loop"
        description="Repeat until an end condition"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
      <PaletteItem
        name="support-triage"
        kind="agent"
        executor="agent"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
      <PaletteItem
        name="check_status"
        kind="fn"
        executor="function"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
    </div>
  ),
};
