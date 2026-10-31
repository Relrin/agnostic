import { ChevronsUpDown, Globe } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Badge } from "../primitives/badge";

export type Environment = "production" | "staging" | "development";

const ENV_TONE = { production: "warning", staging: "info", development: "muted" } as const;

export function EnvBadge({ env }: { env: Environment }) {
  return <Badge tone={ENV_TONE[env]}>{env}</Badge>;
}

/** Instance switcher button (36px, radius 9) */
export function InstanceSwitcher({
  name,
  env,
  onClick,
  className,
}: {
  name: string;
  env: Environment;
  onClick?: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex h-9 cursor-pointer items-center gap-2 rounded-segment border border-border bg-surface px-2.5 text-[13.5px] hover:border-border-strong",
        className,
      )}
    >
      <Globe className="size-4 text-fg-muted" aria-hidden />
      {/* Visible text stays part of the accessible name (WCAG 2.5.3 label in name). */}
      <span className="sr-only">Switch AgentOS instance:</span>
      <span className="font-medium">{name}</span>
      <EnvBadge env={env} />
      <ChevronsUpDown className="size-4 text-fg-muted" aria-hidden />
    </button>
  );
}

export type Health = {
  state: "healthy" | "degraded" | "down" | "unknown";
  latencyMs?: number;
  version?: string;
};

/** `● Healthy · 38 ms · agno 3.1.12` */
export function HealthIndicator({ health }: { health: Health }) {
  const label = { healthy: "Healthy", degraded: "Degraded", down: "Unreachable", unknown: "Unknown" }[
    health.state
  ];
  const parts = [label];
  if (health.latencyMs !== undefined) parts.push(`${health.latencyMs} ms`);
  if (health.version) parts.push(`agno ${health.version}`);
  return (
    <span
      className="inline-flex items-center gap-2 text-[12.5px] whitespace-nowrap text-fg-secondary"
      role="status"
    >
      <span
        aria-hidden
        className={cn(
          "size-[7px] rounded-full",
          health.state === "healthy" && "bg-accent",
          health.state === "degraded" && "bg-warning",
          health.state === "down" && "bg-danger",
          health.state === "unknown" && "bg-neutral-mark",
        )}
      />
      {parts.join(" · ")}
    </span>
  );
}

/** Top header bar: min-height 56, padding 8/24, border-bottom; left cluster wraps on narrow screens. */
export function PageHeader({
  start,
  end,
  className,
}: {
  start: ReactNode;
  end?: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex min-h-14 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border-subtle px-6 py-2",
        className,
      )}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-3">{start}</div>
      {end && <div className="flex flex-wrap items-center gap-2">{end}</div>}
    </header>
  );
}

/** H1 + one-paragraph explainer at the top of a page. */
export function PageIntro({
  title,
  children,
  actions,
}: {
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex max-w-3xl flex-col gap-1.5">
        <h1 className="text-[22px] font-semibold tracking-[-0.01em]">{title}</h1>
        {children && <p className="text-[13.5px] text-fg-secondary">{children}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
