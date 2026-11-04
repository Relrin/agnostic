// Module SDK: every feature module exports one manifest; the shell composes routes, sidebar entries
// and command-palette actions from them. Modules never import each other.
import type { ComponentType, ReactNode } from "react";

export type NavGroupId = "main" | "build" | "observe" | "context" | "control" | "access" | "footer";

export type NavIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

export type NavBadge =
  | { kind: "count"; value: number; tone?: "warning" | "danger" | "muted"; label: string }
  | { kind: "dot"; tone?: "danger" | "warning" | "accent"; label: string };

/**
 * Where a module page lives: under an instance (`/i/:instance/...`), org-wide (`/...`), or public (outside the
 * signed-in shell: sign-in, invitations, first run).
 */
export type ModuleScope = "instance" | "org" | "public";

export type NavEntry = {
  /** Sidebar key (matches the prototype's nav ids, e.g. "approvals"). */
  id: string;
  group: NavGroupId;
  label: string;
  icon: NavIcon;
  /** Path relative to the module scope, e.g. "settings" → `/i/:instance/settings`. */
  path: string;
  /** Position inside its group; catalog entries use multiples of 10. */
  order?: number;
  badge?: NavBadge;
};

export type CommandDefinition = {
  id: string;
  label: string;
  group?: string;
  keywords?: readonly string[];
  icon?: NavIcon;
  /** Navigate to a path relative to the module scope. */
  path?: string;
  /** Pass what was typed in the palette along as `?q=` (e.g. "Ask your OS: why did…"). */
  withQuery?: boolean;
};

export type Capability = string;
export type Scope = string;

export type ModuleRoute = {
  /** Path relative to the scope root, e.g. "settings" or "settings/$section". */
  path: string;
  component: () => ReactNode;
};

export type ModuleManifest = {
  id: string;
  scope: ModuleScope;
  routes: readonly ModuleRoute[];
  nav?: readonly NavEntry[];
  commands?: readonly CommandDefinition[];
  /**
   * When to show the module at all: the active instance's capability matrix, the person's scopes, and
   * control-plane features that must be switched on (`GET /system/features`, e.g. "assistant").
   */
  requires?: {
    capabilities?: readonly Capability[];
    anyScope?: readonly Scope[];
    features?: readonly string[];
  };
};

/** Whether a module's nav entries show for the active instance (unknown capabilities don't hide anything). */
export function moduleAvailable(
  manifest: Pick<ModuleManifest, "requires">,
  capabilities: ReadonlyMap<string, string> | undefined,
): boolean {
  const needed = manifest.requires?.capabilities ?? [];
  if (!capabilities || needed.length === 0) return true;
  return needed.every((name) => {
    const status = capabilities.get(name);
    return status === undefined || status === "available" || status === "unknown";
  });
}

/** Whether every feature a module needs is on (a missing feature is off: its backend module isn't there). */
export function featuresOn(
  manifest: Pick<ModuleManifest, "requires">,
  features: Readonly<Record<string, boolean>> | undefined,
): boolean {
  const needed = manifest.requires?.features ?? [];
  return needed.every((name) => features?.[name] === true);
}

/** Identity helper that type-checks a manifest. */
export function defineModule<const M extends ModuleManifest>(manifest: M): M {
  return manifest;
}
