import { EllipsisVertical, Search } from "lucide-react";
import type { ReactNode } from "react";

import { Avatar, Kbd } from "../primitives/small";
import {
  Sidebar,
  SidebarGroupLabel,
  SidebarItemContent,
  SidebarSeparator,
  navItemClassName,
  type NavBadge,
  type NavIcon,
} from "../primitives/sidebar";

export type AppSidebarItem = {
  id: string;
  label: string;
  icon: NavIcon;
  to: string;
  badge?: NavBadge | undefined;
};

export type AppSidebarGroup = {
  id: string;
  /** Eyebrow label; omit for the ungrouped top items (Home, Chat). */
  label?: string;
  items: readonly AppSidebarItem[];
};

export type SidebarOrg = { name: string; detail: string; logoLetter?: string };
export type SidebarUser = { id: string; name: string; role: string; email: string };

export type AppSidebarProps = {
  org: SidebarOrg;
  user: SidebarUser;
  groups: readonly AppSidebarGroup[];
  /** Items below the divider (Settings, Ask your OS). */
  footer: readonly AppSidebarItem[];
  activeId?: string | undefined;
  onSearch: () => void;
  onAccountMenu?: () => void;
  /** Renders a router link; receives the target, the class name and the item's visual content. */
  renderLink: (props: {
    item: AppSidebarItem;
    className: string;
    active: boolean;
    children: ReactNode;
  }) => ReactNode;
};

/** Org badge (one org per install, so no switcher menu). */
export function OrgBadge({ org }: { org: SidebarOrg }) {
  return (
    <div className="flex h-11 w-full items-center gap-2.5 rounded-segment px-2">
      <span
        aria-hidden
        className="grid size-7 shrink-0 place-items-center rounded-control bg-accent text-[14px] font-bold text-accent-fg"
      >
        {org.logoLetter ?? org.name.slice(0, 1)}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="truncate text-[13.5px] font-semibold">{org.name}</span>
        <span className="text-[11.5px] text-fg-muted">{org.detail}</span>
      </span>
    </div>
  );
}

export function AppSidebar({
  org,
  user,
  groups,
  footer,
  activeId,
  onSearch,
  onAccountMenu,
  renderLink,
}: AppSidebarProps) {
  const item = (entry: AppSidebarItem) => {
    const active = entry.id === activeId;
    return (
      <li key={entry.id}>
        {renderLink({
          item: entry,
          active,
          className: navItemClassName(active),
          children: (
            <SidebarItemContent icon={entry.icon} label={entry.label} active={active} badge={entry.badge} />
          ),
        })}
      </li>
    );
  };

  return (
    <Sidebar>
      <OrgBadge org={org} />
      <button
        type="button"
        onClick={onSearch}
        className="mt-1.5 mb-2 flex h-[34px] w-full cursor-pointer items-center gap-2 rounded-button border border-border bg-surface px-2.5 text-left text-[13px] text-fg-muted hover:border-border-strong"
      >
        <Search className="size-[15px]" aria-hidden />
        <span className="flex-1">Search or jump to…</span>
        <Kbd>⌘K</Kbd>
      </button>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {groups.map((group) => (
          <section key={group.id} aria-labelledby={group.label ? `nav-${group.id}` : undefined}>
            {group.label && <SidebarGroupLabel id={`nav-${group.id}`}>{group.label}</SidebarGroupLabel>}
            <ul className="flex flex-col gap-0.5">{group.items.map(item)}</ul>
          </section>
        ))}
        <SidebarSeparator />
        <ul className="flex flex-col gap-0.5">{footer.map(item)}</ul>
      </div>

      <div className="mt-3 flex items-center gap-2.5 rounded-segment border border-border-subtle bg-surface p-2">
        <Avatar id={user.id} name={user.name} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-[13px] font-medium">{user.name}</span>
          <span className="truncate text-[11.5px] text-fg-muted">
            {user.role} · {user.email}
          </span>
        </div>
        <button
          type="button"
          aria-label="Account menu"
          onClick={onAccountMenu}
          className="grid size-7 cursor-pointer place-items-center rounded-control text-fg-muted hover:bg-surface-hover hover:text-fg"
        >
          <EllipsisVertical className="size-4" aria-hidden />
        </button>
      </div>
    </Sidebar>
  );
}
