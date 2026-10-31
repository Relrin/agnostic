// Module SDK: every feature module exports one manifest; the shell composes routes, sidebar entries
// and command-palette actions from them. Modules never import each other.
import type { ComponentType, ReactNode } from "react";

export type NavGroupId = "main" | "build" | "observe" | "context" | "control" | "access" | "footer";

export type NavIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

export type NavBadge =
  | { kind: "count"; value: number; tone?: "warning" | "danger" | "muted"; label: string }
  | { kind: "dot"; tone?: "danger" | "warning" | "accent"; label: string };

/** Where a module page lives: under an instance (`/i/:instance/...`) or org-wide (`/...`). */
export type ModuleScope = "instance" | "org";

export type NavEntry = {
  /** Sidebar key (matches the prototype's nav ids, e.g. "approvals"). */
  id: string;
  group: NavGroupId;
  label: string;
  icon: NavIcon;
  /** Path relative to the module scope, e.g. "hello" → `/i/:instance/hello`. */
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
};

export type Capability = string;
export type Scope = string;

export type ModuleRoute = {
  /** Path relative to the scope root, e.g. "hello" or "hello/$greetingId". */
  path: string;
  component: () => ReactNode;
};

export type ModuleManifest = {
  id: string;
  scope: ModuleScope;
  routes: readonly ModuleRoute[];
  nav?: readonly NavEntry[];
  commands?: readonly CommandDefinition[];
  /** When to show the module at all (capability matrix and effective scopes; wired in P01). */
  requires?: { capabilities?: readonly Capability[]; anyScope?: readonly Scope[] };
};

/** Identity helper that type-checks a manifest. */
export function defineModule<const M extends ModuleManifest>(manifest: M): M {
  return manifest;
}
