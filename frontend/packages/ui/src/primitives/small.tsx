// Small primitives: Kbd, Skeleton, Callout, Breadcrumb, Avatar.
import { CircleAlert, Info, Lightbulb, OctagonX, TriangleAlert } from "lucide-react";
import { Avatar as AvatarPrimitive } from "radix-ui";
import { Fragment, type ComponentProps, type ReactNode } from "react";

import { cn } from "../lib/cn";

export function Kbd({ className, ...props }: ComponentProps<"kbd">) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "rounded-badge border border-border-strong px-1.5 py-px font-mono text-[11px] leading-4 text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}

/** Loading placeholder shaped like the final layout. */
export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden
      className={cn("animate-pulse rounded-control bg-surface-hover", className)}
      {...props}
    />
  );
}

const CALLOUT = {
  info: { icon: Info, className: "border-border bg-surface text-fg-secondary", iconClass: "text-fg-muted" },
  warning: {
    icon: TriangleAlert,
    className: "border-warning/35 bg-warning/6 text-fg",
    iconClass: "text-warning",
  },
  danger: { icon: OctagonX, className: "border-danger/35 bg-danger/5 text-fg", iconClass: "text-danger" },
  insight: { icon: Lightbulb, className: "border-accent/35 bg-accent/6 text-fg", iconClass: "text-accent" },
  availability: {
    icon: CircleAlert,
    className: "border-info/35 bg-[var(--info-tint)] text-fg",
    iconClass: "text-info",
  },
} as const;

export type CalloutProps = Omit<ComponentProps<"div">, "title"> & {
  tone?: keyof typeof CALLOUT;
  title?: ReactNode;
  action?: ReactNode;
};

export function Callout({ tone = "info", title, action, className, children, ...props }: CalloutProps) {
  const style = CALLOUT[tone];
  const Icon = style.icon;
  return (
    <div
      role={tone === "danger" || tone === "warning" ? "alert" : "note"}
      data-slot="callout"
      className={cn("flex gap-2.5 rounded-tile border px-3.5 py-3 text-[13px]", style.className, className)}
      {...props}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", style.iconClass)} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {title && <div className="font-semibold text-fg">{title}</div>}
        {children && <div className="text-fg-secondary">{children}</div>}
        {action && <div className="pt-1">{action}</div>}
      </div>
    </div>
  );
}

export type Crumb = { label: ReactNode; href?: string; mono?: boolean };

/** `Studio / Agents / support-triage`: links in secondary text, current page in primary (mono for ids). */
export function Breadcrumb({
  items,
  renderLink,
  className,
}: {
  items: readonly Crumb[];
  renderLink?: (crumb: Crumb & { href: string }) => ReactNode;
  className?: string;
}) {
  return (
    <nav aria-label="Breadcrumb" className={cn("min-w-0", className)}>
      <ol className="flex min-w-0 items-center gap-1.5 text-[13.5px]">
        {items.map((crumb, index) => {
          const last = index === items.length - 1;
          return (
            <Fragment key={index}>
              {index > 0 && (
                <li aria-hidden className="text-fg-muted">
                  /
                </li>
              )}
              <li
                className={cn(
                  "truncate",
                  last ? "text-fg" : "text-fg-secondary",
                  crumb.mono && "font-mono text-[13px]",
                )}
                {...(last ? { "aria-current": "page" as const } : {})}
              >
                {!last && crumb.href
                  ? (renderLink?.({ ...crumb, href: crumb.href }) ?? crumb.label)
                  : crumb.label}
              </li>
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}

const AVATAR_COLORS = [
  "bg-[var(--avatar-1-bg)] text-[var(--avatar-1-fg)]",
  "bg-[var(--avatar-2-bg)] text-[var(--avatar-2-fg)]",
  "bg-[var(--avatar-3-bg)] text-[var(--avatar-3-fg)]",
  "bg-[var(--avatar-4-bg)] text-[var(--avatar-4-fg)]",
  "bg-[var(--avatar-5-bg)] text-[var(--avatar-5-fg)]",
  "bg-[var(--avatar-6-bg)] text-[var(--avatar-6-fg)]",
  "bg-[var(--avatar-7-bg)] text-[var(--avatar-7-fg)]",
] as const;

/** Stable palette index for an id (same user, same colours everywhere). */
export function avatarColorIndex(id: string): number {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % AVATAR_COLORS.length;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "?";
  const last = parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

export type AvatarProps = {
  id: string;
  name: string;
  /** Machine principals (service accounts, scheduler) are rounded squares; humans are circles. */
  kind?: "human" | "machine" | "system";
  src?: string;
  size?: number;
  className?: string;
};

export function Avatar({ id, name, kind = "human", src, size = 28, className }: AvatarProps) {
  const colors =
    kind === "system"
      ? "bg-[var(--avatar-system-bg)] text-[var(--avatar-system-fg)]"
      : AVATAR_COLORS[avatarColorIndex(id)];
  return (
    <AvatarPrimitive.Root
      data-slot="avatar"
      className={cn(
        "inline-grid shrink-0 place-items-center overflow-hidden font-semibold",
        kind === "human" ? "rounded-full" : "rounded-control",
        colors,
        className,
      )}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
    >
      {src && <AvatarPrimitive.Image src={src} alt={name} className="size-full object-cover" />}
      <AvatarPrimitive.Fallback aria-label={name}>{initials(name)}</AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  );
}
