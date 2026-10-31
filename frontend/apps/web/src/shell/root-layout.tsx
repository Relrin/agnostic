import { systemReadiness } from "@agnostic/api";
import {
  activeNavId,
  buildNavigation,
  collectCommands,
  scopedPath,
  type ResolvedNavEntry,
} from "@agnostic/core";
import {
  AppShell,
  AppSidebar,
  Breadcrumb,
  HealthIndicator,
  InstanceSwitcher,
  PageHeader,
  TooltipProvider,
  type AppSidebarItem,
  type Health,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { useMemo, useState } from "react";

import { MODULES } from "../modules";
import { CommandPalette } from "./command-palette";
import { GROUP_LABELS, NAV_CATALOG } from "./nav-catalog";
import { DEFAULT_INSTANCE, PLACEHOLDER_INSTANCES, PLACEHOLDER_ORG, PLACEHOLDER_USER } from "./session";

/** Control-plane readiness as the header's health line (instance health replaces it in P01). */
function useControlPlaneHealth(): Health {
  const { data } = useQuery({
    queryKey: ["shell", "readiness"],
    queryFn: async (): Promise<Health> => {
      const started = performance.now();
      try {
        await systemReadiness();
        return { state: "healthy", latencyMs: Math.round(performance.now() - started) };
      } catch {
        return { state: "degraded", latencyMs: Math.round(performance.now() - started) };
      }
    },
    refetchInterval: 30_000,
    retry: false,
  });
  return data ?? { state: "unknown" };
}

/** `/i/<instance>/…` → instance; org-wide pages keep the default instance in the header. */
function instanceFromPath(pathname: string): string {
  const match = /^\/i\/([^/]+)/.exec(pathname);
  return match?.[1] ? decodeURIComponent(match[1]) : DEFAULT_INSTANCE;
}

function toSidebarItem(entry: ResolvedNavEntry, instance: string): AppSidebarItem {
  return {
    id: entry.id,
    label: entry.label,
    icon: entry.icon,
    to: scopedPath(entry.scope, entry.path, instance),
    badge: entry.badge,
  };
}

export function RootLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const instance = instanceFromPath(pathname);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const health = useControlPlaneHealth();

  const navigation = useMemo(() => buildNavigation(NAV_CATALOG, MODULES), []);
  const commands = useMemo(() => collectCommands(MODULES), []);
  const activeId = activeNavId(navigation, pathname, instance);
  const active = [...navigation.groups.flatMap((group) => group.items), ...navigation.footer].find(
    (entry) => entry.id === activeId,
  );
  const instanceInfo = PLACEHOLDER_INSTANCES[instance] ?? { name: instance, env: "development" as const };

  const sidebar = (
    <AppSidebar
      org={PLACEHOLDER_ORG}
      user={PLACEHOLDER_USER}
      groups={navigation.groups.map((group) => ({
        id: group.id,
        ...(group.label ? { label: group.label } : {}),
        items: group.items.map((entry) => toSidebarItem(entry, instance)),
      }))}
      footer={navigation.footer.map((entry) => toSidebarItem(entry, instance))}
      activeId={activeId}
      onSearch={() => {
        setPaletteOpen(true);
      }}
      renderLink={({ item, className, active: isActive, children }) => (
        <Link to={item.to} className={className} {...(isActive ? { "aria-current": "page" as const } : {})}>
          {children}
        </Link>
      )}
    />
  );

  const groupLabel = active ? GROUP_LABELS[active.group] : undefined;

  return (
    <TooltipProvider delayDuration={300}>
      <AppShell sidebar={sidebar}>
        <PageHeader
          start={
            <>
              <InstanceSwitcher name={instanceInfo.name} env={instanceInfo.env} />
              <Breadcrumb
                items={[
                  ...(groupLabel ? [{ label: groupLabel }] : []),
                  { label: active?.label ?? "Not found" },
                ]}
              />
            </>
          }
          end={<HealthIndicator health={health} />}
        />
        <div className="min-h-0 flex-1 overflow-auto">
          <Outlet />
        </div>
      </AppShell>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        navigation={navigation}
        commands={commands}
        instance={instance}
      />
    </TooltipProvider>
  );
}
