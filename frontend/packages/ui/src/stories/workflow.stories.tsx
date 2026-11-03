// Workflow builder building blocks with the ticket router's steps: node cards of every primitive and run status,
// branch labels, the insert button and palette items.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { BranchLabel, InsertButton, NodeCard, PaletteItem, type WorkflowNodeType } from "../domain/workflow";

const meta = {
  title: "Studio/Workflow builder",
  decorators: [
    (Story) => (
      <div className="flex max-w-md flex-col gap-4 p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const NodeCards: Story = {
  render: function Render() {
    const [selected, setSelected] = useState("Route by category");
    const cards: { type: WorkflowNodeType; title: string; meta?: string; chip?: string }[] = [
      { type: "Step", title: "Classify ticket", meta: "avg 1.1 s", chip: "agent · support-triage" },
      {
        type: "Router",
        title: "Route by category",
        meta: "3 choices",
        chip: 'cel · input.contains("refund") || …',
      },
      { type: "Parallel", title: "Investigate", meta: "2 branches" },
      { type: "Loop", title: "Draft & review", meta: "max 3" },
      { type: "Condition", title: "Needs a human?", chip: 'cel · previous_step_content.contains("ESC…' },
      { type: "Steps", title: "Prepare", meta: "2 steps" },
    ];
    return (
      <div className="flex flex-col gap-3">
        {cards.map((card) => (
          <NodeCard
            key={card.title}
            {...card}
            selected={selected === card.title}
            onSelect={() => {
              setSelected(card.title);
            }}
          />
        ))}
      </div>
    );
  },
};

export const RunStatus: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <NodeCard type="Step" title="Classify ticket" chip="agent · support-triage" status="done" />
      <NodeCard type="Step" title="Billing" chip="agent · billing-agent" status="running" />
      <NodeCard type="Step" title="Escalate" chip="team · escalation-team" status="paused" />
      <NodeCard type="Step" title="Send reply" chip="fn · send_reply" status="failed" problems={1} />
    </div>
  ),
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
        type="Step"
        name="Step"
        description="Run an agent, team or function"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
      <PaletteItem
        type="Router"
        name="Router"
        description="Pick one choice by selector"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
      <PaletteItem
        name="support-triage"
        kind="agent"
        color="var(--entity-agent)"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
      <PaletteItem
        name="check_status"
        kind="fn"
        color="var(--entity-fn)"
        onAdd={() => undefined}
        onDragStart={() => undefined}
      />
    </div>
  ),
};
