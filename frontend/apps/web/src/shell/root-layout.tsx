import {
  activeNavId,
  buildNavigation,
  collectCommands,
  decide,
  findInstance,
  moduleAvailable,
  ORG_ROLE_LABELS,
  RealtimeProvider,
  ReauthProvider,
  scopedPath,
  useApprovalsCount,
  useSourceConflicts,
  useCan,
  useInstanceHealth,
  useInstances,
  useMe,
  useMyAccess,
  useOrg,
  type HealthOut,
  type InstanceOut,
  type ModuleManifest,
  type NavBadge,
  type ResolvedNavEntry,
} from "@agnostic/core";
import {
  AppShell,
  AppSidebar,
  Breadcrumb,
  Button,
  Callout,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EnvBadge,
  HealthIndicator,
  InstanceSwitcher,
  PageHeader,
  Toaster,
  TooltipProvider,
  type AppSidebarItem,
  type Health,
} from "@agnostic/ui";
import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { MODULES } from "../modules";
import { CommandPalette } from "./command-palette";
import { GROUP_LABELS, NAV_CATALOG } from "./nav-catalog";
import { NotificationBell } from "./notification-bell";
import { lastInstance, rememberInstance } from "./session";

/** `/i/<instance>/…` → that instance. */
function instanceFromPath(pathname: string): string | undefined {
  const match = /^\/i\/([^/]+)/.exec(pathname);
  return match?.[1] ? decodeURIComponent(match[1]) : undefined;
}

/** `● Healthy · 38 ms · agno 3.1.12` from the instance record and its health endpoint. */
function toHealth(instance: InstanceOut | undefined, health: HealthOut | undefined): Health {
  if (!instance) return { state: "unknown" };
  const status = health?.status ?? instance.status;
  const state =
    status === "connected"
      ? "healthy"
      : status === "unreachable"
        ? "down"
        : status === "pending"
          ? "degraded"
          : "unknown";
  const latency = health?.latency_ms ?? instance.latency_ms;
  const version = health?.agno_version ?? instance.agno_version;
  return {
    state,
    ...(latency !== null ? { latencyMs: latency } : {}),
    ...(version ? { version } : {}),
  };
}

function toSidebarItem(
  entry: ResolvedNavEntry,
  instance: string,
  badges: Readonly<Record<string, NavBadge>>,
): AppSidebarItem {
  return {
    id: entry.id,
    label: entry.label,
    icon: entry.icon,
    to: scopedPath(entry.scope, entry.path, instance),
    badge: badges[entry.id] ?? entry.badge,
  };
}

/** Live nav badges: the pending-approvals count, kept current by realtime `approvals.count` events. */
function useNavBadges(instance: InstanceOut | undefined): Record<string, NavBadge> {
  const canRead = useCan("approvals:read", instance?.slug).allowed === true;
  const canSeeSources = useCan("components:read", instance?.slug).allowed === true;
  const approvals = useApprovalsCount(instance?.id, canRead);
  const conflicts = useSourceConflicts(instance?.id, canSeeSources);
  const count = approvals.data?.count;
  const open = conflicts.data?.count;
  return useMemo(() => {
    const badges: Record<string, NavBadge> = {};
    if (count)
      badges.approvals = { kind: "count", value: count, tone: "warning", label: `${String(count)} pending` };
    if (open)
      badges.sources = {
        kind: "dot",
        tone: "danger",
        label: open === 1 ? "1 conflict" : `${String(open)} conflicts`,
      };
    return badges;
  }, [count, open]);
}

function InstanceMenu({
  instances,
  active,
}: {
  instances: readonly InstanceOut[];
  active: InstanceOut | undefined;
}) {
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  if (!active) {
    return (
      <Button asChild size="32" variant="outline">
        <Link to="/instances/connect">
          <Plus aria-hidden />
          Connect an instance
        </Link>
      </Button>
    );
  }
  // Switching keeps the current page when it's an instance page (03 §3).
  const switchTo = (slug: string) => {
    const rest = pathname.startsWith("/i/") ? pathname.split("/").slice(3).join("/") : "settings";
    void navigate({ to: `/i/${encodeURIComponent(slug)}/${rest}` });
  };
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <InstanceSwitcher name={active.display_name} env={active.env_tag} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-64">
        <DropdownMenuLabel>AgentOS instances</DropdownMenuLabel>
        {instances.map((instance) => (
          <DropdownMenuItem
            key={instance.id}
            onSelect={() => {
              switchTo(instance.slug);
            }}
          >
            <span className="flex-1">{instance.display_name}</span>
            <EnvBadge env={instance.env_tag} />
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => {
            void navigate({ to: "/instances" });
          }}
        >
          Manage instances
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UnreachableBanner({ instance, health }: { instance: InstanceOut | undefined; health: Health }) {
  if (!instance || (health.state !== "down" && instance.status !== "disabled")) return null;
  const disabled = instance.status === "disabled";
  return (
    <div className="px-6 pt-3">
      <Callout
        tone={disabled ? "warning" : "danger"}
        title={disabled ? `${instance.display_name} is disabled` : `${instance.display_name} is unreachable`}
        action={
          <Button asChild size="28" variant="outline">
            <Link
              to="/i/$instance/settings/$section"
              params={{ instance: instance.slug, section: "connection" }}
            >
              Open connection settings
            </Link>
          </Button>
        }
      >
        {disabled
          ? "The gateway won't call it until it's enabled again."
          : `Pages that read from it fail until it's back.${
              instance.last_seen_at ? ` Last seen ${new Date(instance.last_seen_at).toLocaleString()}.` : ""
            }`}
      </Callout>
    </div>
  );
}

/** Modules shown for the active instance: capability-driven (07 §3) and scope-driven (anyScope). */
function useVisibleModules(capabilities: ReadonlyMap<string, string> | undefined): ModuleManifest[] {
  const orgAccess = useMyAccess();
  return useMemo(
    () =>
      MODULES.filter((module) => {
        if (module.scope === "instance" && !moduleAvailable(module, capabilities)) return false;
        const anyScope = module.requires?.anyScope ?? [];
        if (anyScope.length === 0 || !orgAccess.data) return true;
        return anyScope.some((scope) => decide(orgAccess.data, scope).allowed === true);
      }),
    [capabilities, orgAccess.data],
  );
}

export function RootLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const me = useMe();
  const org = useOrg();
  const instances = useInstances();

  const fromPath = instanceFromPath(pathname);
  const active =
    findInstance(instances.data, fromPath) ??
    findInstance(instances.data, lastInstance()) ??
    instances.data?.[0];
  const instanceSlug = fromPath ?? active?.slug ?? "";
  useEffect(() => {
    if (fromPath && findInstance(instances.data, fromPath)) rememberInstance(fromPath);
  }, [fromPath, instances.data]);

  const healthQuery = useInstanceHealth(active?.id);
  const health = toHealth(active, healthQuery.data);
  const capabilities = useMemo(
    () =>
      healthQuery.data
        ? new Map(healthQuery.data.capabilities.map((item) => [item.name, item.status]))
        : undefined,
    [healthQuery.data],
  );
  const visibleModules = useVisibleModules(capabilities);
  const badges = useNavBadges(active);
  const navigation = useMemo(() => buildNavigation(NAV_CATALOG, visibleModules), [visibleModules]);
  const commands = useMemo(() => collectCommands(MODULES), []);
  const activeId = activeNavId(navigation, pathname, instanceSlug);
  const activeEntry = [...navigation.groups.flatMap((group) => group.items), ...navigation.footer].find(
    (entry) => entry.id === activeId,
  );

  const orgDetail = org.data
    ? `${String(org.data.member_count)} ${org.data.member_count === 1 ? "member" : "members"}` +
      (org.data.seat_limit ? ` · ${String(org.data.seat_limit)} seats` : "")
    : "";
  const sidebar = (
    <AppSidebar
      org={{
        name: org.data?.name ?? "Agnostic",
        detail: orgDetail,
        logoUrl: org.data?.logo_url ?? undefined,
      }}
      user={{
        id: me.data?.id ?? "me",
        name: me.data?.display_name ?? "…",
        role: me.data?.org_role ? ORG_ROLE_LABELS[me.data.org_role] : "",
        email: me.data?.email ?? "",
      }}
      groups={navigation.groups.map((group) => ({
        id: group.id,
        ...(group.label ? { label: group.label } : {}),
        items: group.items.map((entry) => toSidebarItem(entry, instanceSlug, badges)),
      }))}
      footer={navigation.footer.map((entry) => toSidebarItem(entry, instanceSlug, badges))}
      activeId={activeId}
      onSearch={() => {
        setPaletteOpen(true);
      }}
      onAccountMenu={() => {
        void navigate({ to: "/account" });
      }}
      renderLink={({ item, className, active: isActive, children }) => (
        <Link to={item.to} className={className} {...(isActive ? { "aria-current": "page" as const } : {})}>
          {children}
        </Link>
      )}
    />
  );

  const groupLabel = activeEntry ? GROUP_LABELS[activeEntry.group] : undefined;
  const unknownInstance =
    fromPath !== undefined && instances.data !== undefined && !findInstance(instances.data, fromPath);

  return (
    <RealtimeProvider>
      <TooltipProvider delayDuration={300}>
        <ReauthProvider>
          <AppShell sidebar={sidebar}>
            <PageHeader
              start={
                <>
                  <InstanceMenu instances={instances.data ?? []} active={active} />
                  <Breadcrumb
                    items={[
                      ...(groupLabel ? [{ label: groupLabel }] : []),
                      {
                        label:
                          activeEntry?.label ??
                          (pathname.startsWith("/account")
                            ? "Account"
                            : pathname.startsWith("/instances")
                              ? "Instances"
                              : ""),
                      },
                    ]}
                  />
                </>
              }
              end={
                <>
                  {active ? <HealthIndicator health={health} /> : undefined}
                  <NotificationBell />
                </>
              }
            />
            <UnreachableBanner instance={fromPath ? active : undefined} health={health} />
            <div className="min-h-0 flex-1 overflow-auto">
              {unknownInstance ? (
                <div className="mx-auto w-full max-w-[1320px] px-8 pt-6">
                  <Callout tone="danger" title={`There is no instance ${fromPath}`}>
                    It may have been renamed or deleted. <Link to="/instances">See all instances</Link>.
                  </Callout>
                </div>
              ) : (
                <Outlet />
              )}
            </div>
          </AppShell>
          <CommandPalette
            open={paletteOpen}
            onOpenChange={setPaletteOpen}
            navigation={navigation}
            commands={commands}
            instance={instanceSlug}
            instanceId={active?.id}
          />
        </ReauthProvider>
        <Toaster />
      </TooltipProvider>
    </RealtimeProvider>
  );
}
