import type { Meta, StoryObj } from "@storybook/react-vite";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge, StatusPill } from "../primitives/badge";
import { Button } from "../primitives/button";
import { Input } from "../primitives/input";
import { SegmentedControl } from "../primitives/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../primitives/select";
import { Avatar, Breadcrumb, Callout, Kbd, Skeleton } from "../primitives/small";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../primitives/tabs";

const meta = { title: "Primitives/Overview" } satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

export const Buttons: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary">Publish v9</Button>
        <Button variant="secondary">Test draft</Button>
        <Button variant="outline">Compare</Button>
        <Button variant="subtle">Filters</Button>
        <Button variant="ghost">Cancel</Button>
        <Button variant="dashed-add">
          <Plus aria-hidden /> Add tool
        </Button>
        <Button variant="destructive-text">Discard</Button>
        <Button variant="destructive-outline">
          <Trash2 aria-hidden /> Delete
        </Button>
        <Button variant="link">Open trace</Button>
        <Button variant="icon" aria-label="Add">
          <Plus aria-hidden />
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {(["36", "34", "32", "30", "28"] as const).map((size) => (
          <Button key={size} size={size} variant="secondary">
            {size}px
          </Button>
        ))}
        <Button variant="primary" disabled>
          Disabled
        </Button>
      </div>
    </div>
  ),
};

export const Badges: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      {["COMPLETED", "RUNNING", "PAUSED", "FAILED", "DRAFT", "unknown"].map((status) => (
        <StatusPill key={status} status={status} />
      ))}
      <Badge tone="outline">tool</Badge>
    </div>
  ),
};

export const Inputs: Story = {
  render: function Render() {
    const [kind, setKind] = useState<"agents" | "teams" | "workflows">("agents");
    return (
      <div className="flex max-w-md flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="story-name" className="text-[13px] text-fg-secondary">
            Name
          </label>
          <Input id="story-name" placeholder="support-triage" />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="story-session" className="text-[13px] text-fg-secondary">
            Session id
          </label>
          <Input id="story-session" mono defaultValue="sess_8f2c41" />
        </div>
        <Select defaultValue="v3">
          <SelectTrigger aria-label="Version">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="v3">v3 · current</SelectItem>
            <SelectItem value="v4">v4 · draft</SelectItem>
          </SelectContent>
        </Select>
        <SegmentedControl
          label="Component type"
          value={kind}
          onValueChange={setKind}
          options={[
            { value: "agents", label: "Agents" },
            { value: "teams", label: "Teams" },
            { value: "workflows", label: "Workflows" },
          ]}
        />
      </div>
    );
  },
};

export const TabsVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-6">
      <Tabs defaultValue="pending">
        <TabsList>
          <TabsTrigger value="pending" count={3} countTone="warning">
            Pending
          </TabsTrigger>
          <TabsTrigger value="resolved">Resolved</TabsTrigger>
        </TabsList>
        <TabsContent value="pending" className="text-[13px] text-fg-secondary">
          3 runs are waiting on a decision.
        </TabsContent>
        <TabsContent value="resolved" className="text-[13px] text-fg-secondary">
          Nothing resolved today.
        </TabsContent>
      </Tabs>
      <Tabs defaultValue="members">
        <TabsList variant="pill">
          <TabsTrigger value="members" count={24}>
            Members
          </TabsTrigger>
          <TabsTrigger value="groups" count={6}>
            Groups
          </TabsTrigger>
        </TabsList>
        <TabsContent value="members" className="text-[13px] text-fg-secondary">
          24 people in Northwind Labs.
        </TabsContent>
        <TabsContent value="groups" className="text-[13px] text-fg-secondary">
          6 groups, 4 synced from Okta.
        </TabsContent>
      </Tabs>
    </div>
  ),
};

export const Feedback: Story = {
  render: () => (
    <div className="flex max-w-xl flex-col gap-3">
      <Callout tone="info" title="Shown because you hold approvals:write on prod-agentos" />
      <Callout tone="warning" title="1 migration pending">
        main-pg needs a migration before Studio can save components.
      </Callout>
      <Callout tone="danger" title="prod-agentos isn't answering">
        Timeout after 5 s. Cached data from 2 min ago is shown.
      </Callout>
      <Callout tone="insight" title="3 agents share this tool" />
      <div className="flex items-center gap-2">
        <Avatar id="usr_dana" name="Dana Okafor" />
        <Avatar id="usr_sam" name="Sam Rivera" />
        <Avatar id="sa_ci" name="ci bot" kind="machine" />
        <Avatar id="system" name="Scheduler" kind="system" />
        <Kbd>⌘K</Kbd>
      </div>
      <Breadcrumb
        items={[{ label: "Studio" }, { label: "Agents" }, { label: "support-triage", mono: true }]}
      />
      <Skeleton className="h-9 w-full" />
    </div>
  ),
};
