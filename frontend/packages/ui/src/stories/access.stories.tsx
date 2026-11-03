// Access patterns with the prototype's samples: Maya's bindings, the Operator edit and the role editor's save bar.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { AccessChip, SaveBar, ScopeDiff } from "../patterns/access";

const meta = {
  title: "Access/Patterns",
  decorators: [
    (Story) => (
      <div className="flex max-w-xl flex-col gap-4 p-6">
        <Story />
      </div>
    ),
  ],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const Chips: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <AccessChip
        roleName="Operator"
        instance="prod-agentos"
        env="production"
        via="Support AI"
        color="#C5F25C"
      />
      <AccessChip
        roleName="Builder"
        instance="staging-agentos"
        env="staging"
        via="Support AI"
        color="#7DA6FF"
      />
      <AccessChip roleName="Auditor" color="#B79CFF" />
      <AccessChip
        roleName="Viewer"
        instance="staging-agentos"
        env="staging"
        color="#A9AFB8"
        expires="ends 30 Nov"
      />
    </div>
  ),
};

export const OperatorEdit: Story = {
  render: () => (
    <ScopeDiff
      label="Token scope changes"
      lines={[
        { op: "add", text: "knowledge:write" },
        { op: "remove", text: "approvals:delete" },
      ]}
    />
  ),
};

function SaveBarDemo() {
  const [dirty, setDirty] = useState(2);
  return (
    <div className="relative h-32 rounded-card border border-border">
      <SaveBar
        dirty={dirty}
        note="No redeploy"
        onDiscard={() => {
          setDirty(0);
        }}
        onSave={() => {
          setDirty(0);
        }}
      />
    </div>
  );
}

export const UnsavedChanges: Story = { render: () => <SaveBarDemo /> };
