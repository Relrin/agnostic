// Sidebar building blocks: 28px nav items with 16px icons, mono eyebrow group labels,
// trailing count pills / dots. Data-free: the app passes items, badges and the link component.
import type { ComponentProps, ComponentType, ReactNode } from "react";

import { cn } from "../lib/cn";

export type NavBadge =
  | { kind: "count"; value: number; tone?: "warning" | "danger" | "muted"; label: string }
  | { kind: "dot"; tone?: "danger" | "warning" | "accent"; label: string };

export type NavIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

export function Sidebar({ className, ...props }: ComponentProps<"nav">) {
  return (
    <nav
      aria-label="Primary"
      data-slot="sidebar"
      className={cn("flex h-full flex-col gap-0.5 bg-bg px-2.5 pt-3 pb-3.5 text-[13.5px] text-fg", className)}
      {...props}
    />
  );
}

export function SidebarGroupLabel({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("eyebrow px-2.5 pt-3 pb-1", className)} {...props} />;
}

export function SidebarSeparator({ className }: { className?: string }) {
  return <div role="separator" className={cn("mx-1 mt-3.5 mb-2 h-px bg-border-subtle", className)} />;
}

export function SidebarBadge({ badge }: { badge: NavBadge }) {
  if (badge.kind === "dot") {
    return (
      <span
        role="img"
        aria-label={badge.label}
        className={cn(
          "size-[7px] shrink-0 rounded-full",
          (badge.tone ?? "danger") === "danger" && "bg-danger",
          badge.tone === "warning" && "bg-warning",
          badge.tone === "accent" && "bg-accent",
        )}
      />
    );
  }
  return (
    <span
      aria-label={badge.label}
      className={cn(
        "tabular rounded-full px-1.5 font-mono text-[11px] leading-[18px] font-semibold",
        (badge.tone ?? "warning") === "warning" && "bg-warning/14 text-warning",
        badge.tone === "danger" && "bg-danger/12 text-danger",
        badge.tone === "muted" && "bg-surface-hover text-fg-muted",
      )}
    >
      {badge.value}
    </span>
  );
}

export type SidebarItemContentProps = {
  icon: NavIcon;
  label: ReactNode;
  active?: boolean;
  badge?: NavBadge | undefined;
};

/** Visual content of a nav item; wrap it in the router's link (see `navItemClassName`). */
export function SidebarItemContent({ icon: Icon, label, active = false, badge }: SidebarItemContentProps) {
  return (
    <>
      <Icon className={cn("size-4 shrink-0", active ? "text-accent" : "text-fg-faint")} aria-hidden />
      <span className="flex-1 truncate">{label}</span>
      {badge && <SidebarBadge badge={badge} />}
    </>
  );
}

export function navItemClassName(active: boolean): string {
  return cn(
    "flex h-7 items-center gap-2.5 rounded-control px-2.5 no-underline transition-colors duration-[var(--motion-fast)]",
    active ? "bg-surface-hover text-fg-active" : "text-fg-secondary hover:bg-surface-hover/60 hover:text-fg",
  );
}
