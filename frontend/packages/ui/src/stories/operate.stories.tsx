// Operate widgets with a sample run: support-triage paused on refund_customer, the Home
// tiles and attention cards, a workflow paused on a HumanReview step.
import type { Meta, StoryObj } from "@storybook/react-vite";

import { Composer, SessionList } from "../domain/chat";
import {
  ApprovalCard,
  RunBlock,
  RunCard,
  RunTimelineSeparator,
  RunToolbar,
  StepHitlForm,
  StepTimeline,
  ToolCallChip,
  UserBubble,
} from "../domain/run";
import { ShareList, StackedBarChart } from "../patterns/chart";
import { JsonView, MarkdownView } from "../patterns/content";
import { AttentionCard, KpiTile } from "../patterns/data";
import { Button } from "../primitives/button";
import { TooltipProvider } from "../primitives/tooltip";

const meta = {
  title: "Operate/Overview",
  decorators: [
    (Story) => (
      <TooltipProvider>
        <div className="flex max-w-3xl flex-col gap-4 p-6">
          <Story />
        </div>
      </TooltipProvider>
    ),
  ],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

const noop = () => undefined;

export const PausedRun: Story = {
  render: () => (
    <>
      <UserBubble>Please refund order 4471, the customer was charged twice.</UserBubble>
      <RunBlock
        label="Run run_9f2c41"
        kind="agent"
        name="support-triage"
        version="v3"
        worked="worked 3.1 s"
        status="PAUSED"
        tools={
          <>
            <ToolCallChip name="kb_lookup" status="done" duration="0.4s" />
            <ToolCallChip name="zendesk_search" status="done" duration="0.6s" />
            <ToolCallChip name="refund_customer" status="awaiting" />
          </>
        }
      >
        <MarkdownView>{"Order **4471** was charged twice. I've asked to refund `$49.00`."}</MarkdownView>
        <ApprovalCard
          toolName="refund_customer"
          args={{ order_id: "4471", amount: 49.0 }}
          requested="requested 2 min ago"
          canDecide
          onApprove={noop}
          onReject={noop}
          footer="Shown because you hold approvals:write on prod-agentos"
        />
      </RunBlock>
      <RunToolbar meta="run_9f2c41 · 2,106 tokens">
        <Button variant="ghost" size="28">
          Copy response
        </Button>
        <Button variant="ghost" size="28">
          Retry run
        </Button>
      </RunToolbar>
    </>
  ),
};

export const WorkflowHitl: Story = {
  render: () => (
    <>
      <StepTimeline
        steps={[
          { id: "1", name: "triage", kind: "step", status: "COMPLETED", children: [] },
          {
            id: "2",
            name: "research loop",
            kind: "loop",
            status: "COMPLETED",
            detail: "iteration 2 of 2",
            children: [{ id: "3", name: "kb", kind: "step", status: "COMPLETED", children: [] }],
          },
          { id: "4", name: "approve", kind: "step", status: "PAUSED", children: [] },
        ]}
      />
      <StepHitlForm
        request={{
          stepName: "approve",
          confirmation: "Issue the refund?",
          userInput: {
            message: "Confirm the amount",
            fields: [
              { name: "amount", type: "float", required: true },
              { name: "reason", type: "str", required: false, description: "Shown on the receipt" },
            ],
          },
        }}
        onSubmit={noop}
      />
    </>
  ),
};

export const ChatParts: Story = {
  render: () => (
    <>
      <SessionList
        label="Sessions for support-triage"
        search=""
        onSearch={noop}
        onSelect={noop}
        selectedId="ses_1"
        groups={[
          {
            label: "Today",
            items: [
              {
                id: "ses_1",
                name: "Refund for order 4471",
                status: "PAUSED",
                meta: "dana@northwind.dev · 2 min ago",
              },
              { id: "ses_2", name: "Where is my order?", meta: "cust_8812 · 1 hour ago" },
            ],
          },
        ]}
      />
      <Composer
        label="Message support-triage"
        placeholder="Message support-triage v3…"
        onSend={noop}
        attachments={{ maxBytes: 20 * 1024 * 1024, maxFiles: 5, accept: ["application/pdf"] }}
      />
      <RunTimelineSeparator>Run 2 · 10:44 · error</RunTimelineSeparator>
      <RunCard
        status="PAUSED"
        title="Please refund order 4471"
        meta="run_9f2c41 · Today 10:42 · 1.2 s so far · 2,106 tokens"
        note="Paused on refund_customer for approval. Continues when Billing ops resolves it."
      />
      <JsonView label="session_state" value={{ order_id: "4471", refund_requested: true }} />
    </>
  ),
};

export const HomeWidgets: Story = {
  render: () => (
    <>
      <div className="grid grid-cols-2 gap-3">
        <AttentionCard
          severity="warning"
          title="3 approvals waiting"
          detail="refund_customer on billing-agent · oldest 2h 14m"
          action={<Button size="28">Review</Button>}
        />
        <AttentionCard
          severity="danger"
          title="daily-brief failed twice"
          detail="Timeout in web_search after 30 s · 03:00 UTC"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <KpiTile
          label="Runs"
          value="4,912"
          delta={{ label: "12%", direction: "up", sentiment: "good", context: " vs previous 7 days" }}
        />
        <KpiTile
          label="Error rate"
          value="1.8%"
          delta={{ label: "0.4 pt", direction: "up", sentiment: "bad" }}
          estimate
        />
      </div>
      <StackedBarChart
        label="Runs per day, Oct 30 to Oct 31"
        categoryKey="date"
        data={[
          { date: "Oct 30", completed: 588, failed: 12 },
          { date: "Oct 31", completed: 610, failed: 9 },
        ]}
        series={[
          { key: "completed", label: "Completed", color: "var(--accent)" },
          { key: "failed", label: "Failed", color: "var(--danger)" },
        ]}
      />
      <ShareList items={[{ key: "m", label: "gpt-5.2-mini", value: "3,920 · 80%", share: 0.8 }]} />
    </>
  ),
};
