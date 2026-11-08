// Streamed model output, side by side: as the chunks arrive (in uneven bursts, the way providers send them) and
// as the chat shows it, paced for reading. Replay runs the same stream again.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";

import { MarkdownView } from "../patterns/content";
import { Button } from "../primitives/button";

const meta = {
  title: "Operate/Streaming text",
  parameters: { layout: "fullscreen" },
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const ANSWER = `## Why the refund was held

The order **ord_1001** was refunded once already, on 2 November, so a second refund of the same amount needs a \
person to confirm it. Here is what I checked before pausing:

1. The order total is 49.00 and the first refund covered all of it.
2. The customer opened a new ticket asking for the money again.
3. The payment provider shows the first refund as settled.

\`\`\`python
order = lookup_order("ord_1001")
assert order.refunded == order.total
\`\`\`

> Approve the refund only if the customer was charged twice.

If you reject it, I will reply to the ticket with the settlement date of the first refund.`;

/** Deterministic pseudo-random numbers, so every replay streams the same way. */
function sequence(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1_103_515_245 + 12_345) % 2 ** 31;
    return state / 2 ** 31;
  };
}

/** Chunks with the pause before each: mostly a few tokens quickly, now and then a stall and a large chunk. */
function bursts(text: string): { chunk: string; pause: number }[] {
  const random = sequence(7);
  const result: { chunk: string; pause: number }[] = [];
  let index = 0;
  while (index < text.length) {
    const stall = random() < 0.12;
    const size = stall ? 40 + Math.floor(random() * 60) : 2 + Math.floor(random() * 14);
    result.push({
      chunk: text.slice(index, index + size),
      pause: stall ? 350 + random() * 250 : 25 + random() * 60,
    });
    index += size;
  }
  return result;
}

function useSimulatedStream(text: string, run: number): { received: string; streaming: boolean } {
  const [state, setState] = useState({ received: "", streaming: true });
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const chunks = bursts(text);
    let received = "";
    const next = (index: number) => {
      const item = chunks[index];
      if (cancelled) return;
      if (!item) {
        setState({ received, streaming: false });
        return;
      }
      timer = setTimeout(() => {
        received += item.chunk;
        setState({ received, streaming: true });
        next(index + 1);
      }, item.pause);
    };
    timer = setTimeout(() => {
      setState({ received, streaming: true });
      next(0);
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [text, run]);
  return state;
}

function Column({ title, detail, children }: { title: string; detail: string; children: React.ReactNode }) {
  return (
    <section
      aria-label={title}
      className="flex min-w-0 flex-1 flex-col gap-3 rounded-card border border-border p-4"
    >
      <header className="flex flex-col gap-0.5">
        <h2 className="text-[13px] font-semibold text-fg">{title}</h2>
        <p className="text-[12px] text-fg-muted">{detail}</p>
      </header>
      <div className="min-h-[26rem]">{children}</div>
    </section>
  );
}

function StreamingComparison() {
  const [run, setRun] = useState(0);
  const { received, streaming } = useSimulatedStream(ANSWER, run);
  return (
    <div className="flex flex-col gap-4 bg-bg p-6">
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          size="30"
          onClick={() => {
            setRun(run + 1);
          }}
        >
          Replay
        </Button>
        <span className="text-[12px] text-fg-muted tabular-nums" aria-live="polite">
          {streaming
            ? `streaming · ${String(received.length)} of ${String(ANSWER.length)} characters received`
            : "done"}
        </span>
      </div>
      <div className="flex gap-4">
        <Column title="As received" detail="Each chunk appears the moment it arrives.">
          <MarkdownView>{received}</MarkdownView>
        </Column>
        <Column title="Paced for reading" detail="The same stream, revealed at a steady pace.">
          <MarkdownView streaming={streaming}>{received}</MarkdownView>
        </Column>
      </div>
    </div>
  );
}

export const SideBySide: Story = {
  render: () => <StreamingComparison />,
};
