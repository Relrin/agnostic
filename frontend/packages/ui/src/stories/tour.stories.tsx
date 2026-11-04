import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import { Tour, type TourStep } from "../patterns/tour";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";

const meta = { title: "Patterns/Tour" } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const STEPS: TourStep[] = [
  {
    target: "demo-endpoint",
    title: "Where AgentOS listens",
    body: "The URL the control plane calls, e.g. http://agentos:7777.",
  },
  {
    target: "demo-test",
    title: "Test before you save",
    body: "Agnostic checks the instance answers and reports its version and capabilities.",
  },
  { target: "missing-target", title: "That's it", body: "A step without a target shows near the top." },
];

function TourDemo() {
  const [open, setOpen] = useState(false);
  const [ended, setEnded] = useState<string>();
  return (
    <div className="flex max-w-lg flex-col gap-4">
      <div className="flex flex-col gap-1.5 text-[13px]" data-tour="demo-endpoint">
        <label htmlFor="demo-endpoint">Endpoint URL</label>
        <Input id="demo-endpoint" defaultValue="http://agentos:7777" />
      </div>
      <div className="flex gap-2">
        <Button data-tour="demo-test">Test connection</Button>
        <Button
          variant="primary"
          onClick={() => {
            setOpen(true);
          }}
        >
          Start tour
        </Button>
      </div>
      {ended && <p className="text-[12.5px] text-fg-muted">Tour {ended}.</p>}
      <Tour
        label="Connect an instance"
        steps={STEPS}
        open={open}
        onEnd={(how) => {
          setOpen(false);
          setEnded(how);
        }}
      />
    </div>
  );
}

export const Steps: Story = {
  render: () => <TourDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const start = canvas.getByRole("button", { name: "Start tour" });
    await userEvent.click(start);
    const step = await screen.findByRole("dialog", { name: "Where AgentOS listens" });
    await waitFor(() => expect(step).toHaveFocus());
    await expect(canvasElement.querySelector("[data-tour-active]")).toHaveAttribute(
      "data-tour",
      "demo-endpoint",
    );
    await userEvent.click(within(step).getByRole("button", { name: "Next" }));
    await screen.findByRole("dialog", { name: "Test before you save" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await expect(canvas.getByText("Tour dismissed.")).toBeInTheDocument();
    await expect(start).toHaveFocus();
  },
};
