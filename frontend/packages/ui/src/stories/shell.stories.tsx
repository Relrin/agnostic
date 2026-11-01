// The shell with the prototype's sample data: Localhost Company, Daniel Okafor, a conflict dot on
// Code sources and 3 pending approvals.
import type { Meta, StoryObj } from "@storybook/react-vite";
import {
  BadgeCheck,
  BookOpen,
  Bot,
  Boxes,
  Brain,
  CalendarClock,
  ChartColumn,
  ChartGantt,
  FolderTree,
  GitBranch,
  House,
  KeyRound,
  KeySquare,
  Library,
  Lightbulb,
  ListOrdered,
  MessageSquare,
  MessagesSquare,
  ScrollText,
  Settings,
  SquareTerminal,
  Target,
  Users,
  Workflow,
} from "lucide-react";

import { AppShell } from "../patterns/app-shell";
import { AppSidebar, type AppSidebarGroup, type AppSidebarItem } from "../patterns/app-sidebar";
import { HealthIndicator, InstanceSwitcher, PageHeader, PageIntro } from "../patterns/page-header";
import { Breadcrumb } from "../primitives/small";
import { Button } from "../primitives/button";

const item = (id: string, label: string, icon: AppSidebarItem["icon"], extra?: Partial<AppSidebarItem>) => ({
  id,
  label,
  icon,
  to: `#${id}`,
  ...extra,
});

const groups: AppSidebarGroup[] = [
  { id: "main", items: [item("home", "Home", House), item("chat", "Chat", MessageSquare)] },
  {
    id: "build",
    label: "Build",
    items: [
      item("agents", "Agents", Bot),
      item("teams", "Agent teams", Boxes),
      item("workflows", "Workflows", Workflow),
      item("registry", "Registry", Library),
      item("sources", "Code sources", GitBranch, {
        badge: { kind: "dot", tone: "danger", label: "1 conflict" },
      }),
    ],
  },
  {
    id: "observe",
    label: "Observe",
    items: [
      item("sessions", "Sessions", MessagesSquare),
      item("traces", "Traces", ChartGantt),
      item("metrics", "Metrics", ChartColumn),
      item("evals", "Evaluations", Target),
    ],
  },
  {
    id: "context",
    label: "Context",
    items: [
      item("memory", "Memory", Brain),
      item("knowledge", "Knowledge", BookOpen),
      item("learnings", "Learnings", Lightbulb),
      item("files", "File system", FolderTree),
    ],
  },
  {
    id: "control",
    label: "Control",
    items: [
      item("approvals", "Approvals", BadgeCheck, {
        badge: { kind: "count", value: 3, tone: "warning", label: "3 pending" },
      }),
      item("scheduler", "Scheduler", CalendarClock),
      item("queue", "Queue", ListOrdered),
    ],
  },
  {
    id: "access",
    label: "Access",
    items: [
      item("people", "People & groups", Users),
      item("roles", "Roles & permissions", KeyRound),
      item("tokens", "Service accounts", KeySquare),
      item("audit", "Audit log", ScrollText),
    ],
  },
];

const footer = [item("settings", "Settings", Settings), item("ask", "Ask your OS", SquareTerminal)];

function PrototypeSidebar({ activeId }: { activeId: string }) {
  return (
    <AppSidebar
      org={{ name: "Localhost Company", detail: "24 members · 24 seats", logoLetter: "L" }}
      user={{ id: "usr_dana", name: "Daniel Okafor", role: "Owner", email: "daniel@localhost.company" }}
      groups={groups}
      footer={footer}
      activeId={activeId}
      onSearch={() => undefined}
      renderLink={({ item: entry, className, active, children }) => (
        <a href={entry.to} className={className} {...(active ? { "aria-current": "page" as const } : {})}>
          {children}
        </a>
      )}
    />
  );
}

const meta = {
  title: "Patterns/Shell",
  component: PrototypeSidebar,
  parameters: { layout: "fullscreen" },
  args: { activeId: "approvals" },
} satisfies Meta<typeof PrototypeSidebar>;
export default meta;
type Story = StoryObj<typeof meta>;

/** 248px sidebar, as in the prototype's Sidebar component artboard. */
export const Sidebar: Story = {
  decorators: [
    (Story) => (
      <div className="h-[1060px] w-[248px] border-r border-border-subtle">
        <Story />
      </div>
    ),
  ],
};

export const ShellWithHeader: Story = {
  render: (args) => (
    <AppShell sidebar={<PrototypeSidebar {...args} />}>
      <PageHeader
        start={
          <>
            <InstanceSwitcher name="prod-agentos" env="production" />
            <Breadcrumb items={[{ label: "Control" }, { label: "Approvals" }]} />
          </>
        }
        end={<HealthIndicator health={{ state: "healthy", latencyMs: 38, version: "3.1.12" }} />}
      />
      <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
        <PageIntro title="Approvals" actions={<Button variant="primary">Routing rules</Button>}>
          Runs pause here when they call a tool marked @approval. Resolving needs approvals:write.
        </PageIntro>
      </div>
    </AppShell>
  ),
};
