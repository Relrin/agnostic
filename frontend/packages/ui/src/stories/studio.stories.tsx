// Studio building blocks with sample data from the support-triage agent: sortable instructions and members, form
// sections, line links, a model picker, checkboxes and the eval gates of a draft version.
import type { Meta, StoryObj } from "@storybook/react-vite";
import { X } from "lucide-react";
import { useState } from "react";

import { GateResultList, LineLinkBadge } from "../domain/studio";
import { Accordion, AccordionSection } from "../patterns/accordion";
import { SortableList } from "../patterns/sortable-list";
import { Button } from "../primitives/button";
import { Checkbox } from "../primitives/checkbox";
import { Combobox } from "../primitives/combobox";
import { Input } from "../primitives/input";

const meta = {
  title: "Studio/Building blocks",
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

type Instruction = { id: string; text: string };

export const SortableInstructions: Story = {
  render: function Render() {
    const [items, setItems] = useState<Instruction[]>([
      { id: "i1", text: "Classify the ticket as billing, shipping, account or other." },
      { id: "i2", text: "Look the order up before answering anything about shipping." },
      { id: "i3", text: "Never promise a refund; route refunds to Billing ops." },
      { id: "i4", text: "Answer in the customer's language." },
    ]);
    return (
      <SortableList
        aria-label="Instructions"
        items={items}
        getId={(item) => item.id}
        getLabel={(item) => `instruction ${String(items.indexOf(item) + 1)}`}
        onReorder={setItems}
        itemClassName="rounded-tile border border-border bg-surface"
        renderItem={(item, { handle, index }) => (
          <div className="flex items-center gap-2 px-2 py-1.5">
            {handle}
            <span className="w-4 shrink-0 font-mono text-[11.5px] text-fg-muted">{index + 1}</span>
            <Input
              aria-label={`Instruction ${String(index + 1)}`}
              defaultValue={item.text}
              className="h-[30px] border-transparent bg-transparent"
            />
            <Button
              variant="icon"
              size="28"
              aria-label={`Remove instruction ${String(index + 1)}`}
              onClick={() => {
                setItems(items.filter((other) => other.id !== item.id));
              }}
            >
              <X aria-hidden />
            </Button>
          </div>
        )}
      />
    );
  },
};

export const FormSections: Story = {
  render: function Render() {
    const [focused, setFocused] = useState<number | undefined>(8);
    return (
      <Accordion>
        <AccordionSection
          title="Model"
          summary="openai:gpt-5 · temperature 0.2"
          adornment={
            <LineLinkBadge
              line={8}
              active={focused === 8}
              onClick={() => {
                setFocused(8);
              }}
            />
          }
          defaultOpen
        >
          <p className="text-[13px] text-fg-secondary">The model and its parameters.</p>
        </AccordionSection>
        <AccordionSection
          title="Instructions"
          summary="4 instructions · Classify the ticket as billing, shipping, account or other."
          adornment={
            <LineLinkBadge
              line={12}
              active={focused === 12}
              onClick={() => {
                setFocused(12);
              }}
            />
          }
        >
          <p className="text-[13px] text-fg-secondary">Sortable instructions go here.</p>
        </AccordionSection>
        <AccordionSection title="Tools" summary="lookup_order, refund_customer">
          <p className="text-[13px] text-fg-secondary">Tools from the registry.</p>
        </AccordionSection>
      </Accordion>
    );
  },
};

export const LineLinks: Story = {
  render: () => (
    <div className="flex items-center gap-2">
      <LineLinkBadge line={8} />
      <LineLinkBadge line={12} onClick={() => undefined} />
      <LineLinkBadge line={23} onClick={() => undefined} active />
    </div>
  ),
};

export const ModelCombobox: Story = {
  render: function Render() {
    const [model, setModel] = useState<string | undefined>("openai:gpt-5");
    return (
      <div className="flex flex-col gap-1.5">
        <label htmlFor="story-model" className="text-[13px] font-medium text-fg-secondary">
          Model
        </label>
        <Combobox
          id="story-model"
          value={model}
          onValueChange={setModel}
          mono
          group="Registered models"
          searchPlaceholder="Search models"
          options={[
            { value: "openai:gpt-5", label: "openai:gpt-5", hint: "OpenAI" },
            { value: "openai:gpt-5-mini", label: "openai:gpt-5-mini", hint: "OpenAI" },
            { value: "anthropic:claude-sonnet-5-5", label: "anthropic:claude-sonnet-5-5", hint: "Anthropic" },
            { value: "ollama:llama4", label: "ollama:llama4", hint: "not reachable", disabled: true },
          ]}
        />
      </div>
    );
  },
};

export const Checkboxes: Story = {
  render: function Render() {
    const [history, setHistory] = useState(true);
    const [markdown, setMarkdown] = useState(false);
    return (
      <div className="flex flex-col gap-3">
        <Checkbox
          label="Add history to context"
          description="The last 3 runs of the session go into the prompt."
          checked={history}
          onCheckedChange={(checked) => {
            setHistory(checked === true);
          }}
        />
        <Checkbox
          label="Format replies as Markdown"
          checked={markdown}
          onCheckedChange={(checked) => {
            setMarkdown(checked === true);
          }}
        />
        <Checkbox label="Stream intermediate steps" checked="indeterminate" disabled />
      </div>
    );
  },
};

export const EvalGates: Story = {
  render: () => (
    <GateResultList
      rows={[
        {
          id: "g1",
          dataset: "support-golden-v3",
          evalType: "accuracy",
          minAverage: 0.8,
          value: 0.86,
          state: "passes",
          consequence: "Publishing goes ahead.",
        },
        {
          id: "g2",
          dataset: "refund-policy",
          evalType: "agent_as_judge",
          minAverage: 0.9,
          value: 0.74,
          state: "would_block",
          consequence: "Publishing would be blocked until this version averages at least 0.90.",
        },
        {
          id: "g3",
          dataset: "latency-smoke",
          evalType: "performance",
          minAverage: 0.7,
          state: "no_result",
          consequence: "No run of this eval for the draft yet; publishing would be blocked.",
        },
        {
          id: "g4",
          dataset: "tone-check",
          evalType: "reliability",
          minAverage: 0.6,
          state: "off",
          consequence: "Reported only; it never blocks publishing.",
        },
      ]}
    />
  ),
};
