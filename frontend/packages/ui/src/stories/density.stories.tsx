import type { Meta, StoryObj } from "@storybook/react-vite";

import { SpanWaterfall, type SpanRowView } from "../domain/trace";
import { DensityContext, type Density } from "../lib/density";
import { DataTable } from "../patterns/data";
import { LoadingRows } from "../patterns/states";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";

const meta = { title: "Foundations/Density" } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const ROWS = [
  { id: "ses_7f3a91c2", agent: "support-triage", runs: 3, updated: "2 min ago" },
  { id: "ses_1b2c3d4e", agent: "billing-assistant", runs: 12, updated: "1 hour ago" },
  { id: "ses_9e8d7c6b", agent: "daily-brief", runs: 1, updated: "yesterday" },
];

const SPANS: SpanRowView[] = [
  { id: "1", name: "support-triage", kind: "agent", depth: 0, startMs: 0, durationMs: 3120, failed: false },
  { id: "2", name: "gpt-4.1-mini", kind: "model", depth: 1, startMs: 40, durationMs: 1210, failed: false },
  { id: "3", name: "lookup_order", kind: "tool", depth: 1, startMs: 1300, durationMs: 380, failed: false },
  { id: "4", name: "refund_customer", kind: "tool", depth: 1, startMs: 1720, durationMs: 1300, failed: true },
];

/** One density: the attribute drives the CSS tokens, the context the fixed JS row heights. */
function Sample({ density }: { density: Density }) {
  return (
    <DensityContext.Provider value={density}>
      <section data-density={density} aria-label={density} className="flex min-w-0 flex-1 flex-col gap-3">
        <h2 className="eyebrow">{density}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">Publish v9</Button>
          <Button size="30">Test draft</Button>
          <Button size="28" variant="outline">
            Compare
          </Button>
        </div>
        <Input aria-label={`Search sessions, ${density}`} placeholder="Search sessions" />
        <DataTable
          label={`Sessions, ${density}`}
          columns={[
            { id: "id", header: "Session", cell: (row) => <span className="font-mono">{row.id}</span> },
            { id: "agent", header: "Agent", cell: (row) => row.agent },
            { id: "runs", header: "Runs", align: "right", cell: (row) => row.runs },
            { id: "updated", header: "Updated", cell: (row) => row.updated },
          ]}
          rows={ROWS}
          rowKey={(row) => row.id}
        />
        <div className="overflow-x-auto">
          <SpanWaterfall label={`Span waterfall, ${density}`} spans={SPANS} totalMs={3120} />
        </div>
        <LoadingRows rows={2} label={`Loading, ${density}`} />
      </section>
    </DensityContext.Provider>
  );
}

export const Comfortable: Story = { render: () => <Sample density="comfortable" /> };

export const Compact: Story = { render: () => <Sample density="compact" /> };

export const SideBySide: Story = {
  render: () => (
    <div className="flex flex-col gap-8 2xl:flex-row">
      <Sample density="comfortable" />
      <Sample density="compact" />
    </div>
  ),
};
