import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "../lib/cn";

export const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-badge px-1.5 py-0.5 font-mono text-[10.5px] leading-none font-semibold tracking-[0.06em] uppercase",
  {
    variants: {
      tone: {
        success: "bg-accent/12 text-accent",
        warning: "bg-warning/13 text-warning",
        danger: "bg-danger/12 text-danger",
        info: "bg-[var(--info-tint)] text-info",
        muted: "bg-surface-hover text-fg-secondary",
        outline: "border border-border-strong bg-transparent text-fg-secondary",
      },
    },
    defaultVariants: { tone: "muted" },
  },
);

export type BadgeProps = ComponentProps<"span"> & VariantProps<typeof badgeVariants>;

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span data-slot="badge" className={cn(badgeVariants({ tone }), className)} {...props} />;
}

const STATUS_TONES = {
  COMPLETED: "success",
  APPROVED: "success",
  OK: "success",
  ALLOWED: "success",
  ACTIVE: "success",
  REGISTERED: "success",
  RUNNING: "info",
  STAGING: "info",
  PENDING: "warning",
  PAUSED: "warning",
  DRAFT: "warning",
  PRODUCTION: "warning",
  DISCOVERED: "warning",
  FAILED: "danger",
  ERROR: "danger",
  DENIED: "danger",
  REJECTED: "danger",
  TIMEOUT: "danger",
  EXPIRED: "muted",
  CANCELLED: "muted",
  QUEUED: "muted",
} as const satisfies Record<string, NonNullable<BadgeProps["tone"]>>;

export type StatusPillProps = Omit<BadgeProps, "tone" | "children"> & {
  /** Status word as AgentOS or the control plane reports it, e.g. "COMPLETED", "paused". */
  status: string;
  tone?: BadgeProps["tone"];
};

/** A status word in a tinted mono pill; the tone follows the status unless given. */
export function StatusPill({ status, tone, ...props }: StatusPillProps) {
  const key = status.toUpperCase();
  const resolved = tone ?? (key in STATUS_TONES ? STATUS_TONES[key as keyof typeof STATUS_TONES] : "muted");
  return (
    <Badge tone={resolved} {...props}>
      {key}
    </Badge>
  );
}
