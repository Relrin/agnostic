// Builds the sidebar from the shell's nav catalog (the prototype's full navigation) plus module manifests.
// Catalog entries no module implements yet stay visible and route to a "not built yet" page, so the shell
// matches the prototype from day one.
import type { CommandDefinition, ModuleManifest, ModuleScope, NavEntry, NavGroupId } from "./module";

export const NAV_GROUPS: readonly { id: NavGroupId; label?: string }[] = [
  { id: "main" },
  { id: "build", label: "Build" },
  { id: "observe", label: "Observe" },
  { id: "context", label: "Context" },
  { id: "control", label: "Control" },
  { id: "access", label: "Access" },
];

export type ResolvedNavEntry = NavEntry & {
  scope: ModuleScope;
  /** Module that implements the entry, or undefined for a catalog placeholder. */
  moduleId: string | undefined;
};

export type Navigation = {
  groups: { id: NavGroupId; label?: string; items: ResolvedNavEntry[] }[];
  footer: ResolvedNavEntry[];
};

export type CatalogEntry = NavEntry & { scope: ModuleScope };

export function buildNavigation(
  catalog: readonly CatalogEntry[],
  modules: readonly ModuleManifest[],
): Navigation {
  const byId = new Map<string, ResolvedNavEntry>();
  for (const entry of catalog) byId.set(entry.id, { ...entry, moduleId: undefined });
  for (const module of modules) {
    for (const entry of module.nav ?? []) {
      const base = byId.get(entry.id);
      byId.set(entry.id, { ...base, ...entry, scope: module.scope, moduleId: module.id });
    }
  }
  const sorted = [...byId.values()].sort((a, b) => (a.order ?? 1000) - (b.order ?? 1000));
  return {
    groups: NAV_GROUPS.map((group) => ({
      ...group,
      items: sorted.filter((entry) => entry.group === group.id),
    })),
    footer: sorted.filter((entry) => entry.group === "footer"),
  };
}

export function collectCommands(
  modules: readonly ModuleManifest[],
): (CommandDefinition & { scope: ModuleScope })[] {
  return modules.flatMap((module) =>
    (module.commands ?? []).map((command) => ({ ...command, scope: module.scope })),
  );
}

/** Absolute path of a scope-relative path, e.g. ("instance", "settings", "dev-prod") → "/i/dev-prod/settings". */
export function scopedPath(scope: ModuleScope, path: string, instance: string): string {
  const clean = path.replace(/^\/+/, "");
  return scope === "instance" ? `/i/${encodeURIComponent(instance)}/${clean}` : `/${clean}`;
}

/** The module id whose nav entry matches the current location (longest path wins). */
export function activeNavId(navigation: Navigation, pathname: string, instance: string): string | undefined {
  const entries = [...navigation.groups.flatMap((group) => group.items), ...navigation.footer];
  let best: { id: string; length: number } | undefined;
  for (const entry of entries) {
    const target = scopedPath(entry.scope, entry.path, instance);
    if ((pathname === target || pathname.startsWith(`${target}/`)) && target.length > (best?.length ?? -1)) {
      best = { id: entry.id, length: target.length };
    }
  }
  return best?.id;
}
