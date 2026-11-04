import type { Meta, StoryObj } from "@storybook/react-vite";

import { EmptyState, ErrorState, LoadingRows } from "../patterns/states";
import { Button } from "../primitives/button";

const meta = { title: "Patterns/States" } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {
  render: () => (
    <div className="flex max-w-2xl flex-col gap-4">
      <EmptyState
        title="No schedules yet"
        action={<Button variant="primary">New schedule</Button>}
        docs={{ href: "https://docs.example.com/scheduler", label: "How schedules work" }}
      >
        Run an agent, team or workflow on a cron, in its own time zone.
      </EmptyState>
      <EmptyState title="No agents, teams or workflows on this instance yet" />
    </div>
  ),
};

export const Errors: Story = {
  render: () => (
    <div className="flex max-w-2xl flex-col gap-4">
      <ErrorState
        reason="prod-agentos didn't answer within 10 seconds."
        requestId="req_01M6A0EEZEQ373S26F2014ERR"
        onRetry={() => undefined}
      />
      <ErrorState title="You can't see this page" reason="It needs sessions:read on prod-agentos." />
    </div>
  ),
};

export const Loading: Story = {
  render: () => (
    <div className="max-w-2xl">
      <LoadingRows rows={4} label="Loading sessions" />
    </div>
  ),
};
