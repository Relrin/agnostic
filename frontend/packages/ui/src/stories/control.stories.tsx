// Control patterns with the prototype's samples: an approval timeline, worker slots, an argument diff, the cron
// fields of stale-ticket-sweep and an expiry countdown.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { ArgsDiff, Countdown, CronFields, SlotBar, Timeline } from "../patterns/control";
import { Button } from "../primitives/button";
import { Popover, PopoverContent, PopoverTrigger } from "../primitives/popover";

const meta = {
  title: "Control/Patterns",
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

export const ApprovalTimeline: Story = {
  render: () => (
    <Timeline
      label="Approval timeline"
      items={[
        { text: "Run paused at refund_customer · run_status PAUSED", meta: "Today 14:52 UTC", state: "done" },
        { text: "Routed to Support AI and Billing ops", meta: "Slack + control plane", state: "done" },
        { text: "Viewed by Maya Chen", meta: "Today 15:16 UTC", state: "done" },
        { text: "Waiting for a decision", meta: "Expires tomorrow 14:52 UTC", state: "now" },
      ]}
    />
  ),
};

export const WorkerSlots: Story = {
  render: () => (
    <div className="flex w-56 flex-col gap-2">
      <span className="font-mono text-[12.5px]">prod-agentos-0</span>
      <SlotBar busy={3} total={4} label="3 of 4 slots busy" />
      <span className="text-[12px] text-fg-muted">3 of 4 running · deployment 2026-10-31.2</span>
    </div>
  ),
};

export const EditedArguments: Story = {
  render: () => (
    <ArgsDiff
      before={{ order_id: "4471", amount: 49.0, currency: "USD" }}
      after={{ order_id: "4471", amount: 45.0, currency: "USD" }}
    />
  ),
};

function CronDemo() {
  const [value, setValue] = useState("*/30 8-18 * * 1-5");
  return (
    <div className="flex flex-col gap-2">
      <CronFields value={value} onChange={setValue} />
      <code className="font-mono text-[12px] text-fg-muted">{value}</code>
    </div>
  );
}

export const CronEditor: Story = { render: () => <CronDemo /> };

export const ExpiryCountdown: Story = {
  render: () => <Countdown target={new Date(Date.now() + (21 * 60 + 46) * 60_000)} />,
};

export const BellPopover: Story = {
  render: () => (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline">Notifications</Button>
      </PopoverTrigger>
      <PopoverContent className="p-3 text-[13px]">refund_customer needs approval</PopoverContent>
    </Popover>
  ),
};
