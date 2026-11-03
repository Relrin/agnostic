// The scope catalog as a permission matrix, the role editor's draft, and what the editor sends to the control plane.
import type { MemberOut, RoleIn, RoleOut, ScopeOut } from "@agnostic/api";

export const MATRIX_ACTIONS = ["read", "run", "write", "delete"] as const;
export type MatrixAction = (typeof MATRIX_ACTIONS)[number];

/** Resources whose run can be narrowed to some components (`agents:<id>:run`). */
export const RUN_RESOURCES = ["agents", "teams", "workflows"] as const;
export type RunResource = (typeof RUN_RESOURCES)[number];
export const RUN_SINGULAR: Record<RunResource, string> = {
  agents: "agent",
  teams: "team",
  workflows: "workflow",
};

export type OrgRoleId = MemberOut["org_role"];
export const ORG_ROLE_IDS: readonly OrgRoleId[] = ["owner", "administrator", "member"];

/** What each org role carries, as the control plane grants it. */
export const ORG_ROLE_SUMMARY: Record<OrgRoleId, string> = {
  owner:
    "Everything in the control plane: members, roles, instances, settings and the audit log, including deleting instances and rotating their keys. Full access on every instance unless the org requires explicit bindings.",
  administrator:
    "The control plane like an Owner, except deleting instances, rotating instance keys and deleting the org. Full access on every instance unless the org requires explicit bindings.",
  member:
    "Signs in and sees the org, its instances, members and roles. Access to an instance comes only from access roles bound to them or their groups.",
};

export const ORG_ROLE_SCOPES: Record<OrgRoleId, readonly string[] | null> = {
  owner: null,
  administrator: null,
  member: ["org:read", "os:read", "org:members:read", "org:roles:read", "settings:read"],
};

export type MatrixGroupDef = { id: string; label: string; families: readonly string[] };

export const MATRIX_GROUPS: readonly MatrixGroupDef[] = [
  {
    id: "primitives",
    label: "Primitives & Studio",
    families: ["agents", "teams", "workflows", "components", "registry", "filesystem", "studio"],
  },
  {
    id: "runtime",
    label: "Runtime data",
    families: ["sessions", "memories", "learnings", "knowledge", "traces", "metrics", "evals", "evals:gates"],
  },
  { id: "control", label: "Control", families: ["approvals", "schedules", "queue"] },
  { id: "platform", label: "Platform", families: ["config", "service_accounts", "audit", "agent_os"] },
];

const FAMILY_LABELS: Record<string, string> = {
  agents: "Agents",
  teams: "Agent teams",
  workflows: "Workflows",
  components: "Studio components",
  registry: "Registry",
  filesystem: "File system",
  studio: "Studio",
  sessions: "Sessions",
  memories: "Memories",
  learnings: "Learnings",
  knowledge: "Knowledge",
  traces: "Traces",
  metrics: "Metrics",
  evals: "Evaluations",
  "evals:gates": "Publish gates",
  approvals: "Approvals",
  schedules: "Schedules",
  queue: "Queue",
  config: "Config",
  service_accounts: "Service accounts",
  audit: "Audit log",
  agent_os: "Instance admin",
  assistant: "Ask your OS",
};

/** Families org roles carry (members, roles, instances, org settings): not offered in an access role. */
const ORG_LEVEL = /^(org|os|settings)(:|$)/;

export function familyLabel(family: string): string {
  if (family in FAMILY_LABELS) return FAMILY_LABELS[family] ?? family;
  const words = family.replace(/[:_]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "knowledge write", "service accounts manage": how a cell is named to screen readers. */
export function cellName(family: string, action: string): string {
  return `${family.replace(/[:_]/g, " ")} ${action}`;
}

export function isMatrixAction(action: string): action is MatrixAction {
  return (MATRIX_ACTIONS as readonly string[]).includes(action);
}

export type MatrixRow =
  | {
      kind: "family";
      family: string;
      label: string;
      cells: Partial<Record<MatrixAction, ScopeOut>>;
    }
  /** An action outside read/run/write/delete (`queue:operate`, `agent_os:admin`): its own row, one checkbox. */
  | { kind: "extra"; family: string; label: string; spec: ScopeOut };

export type MatrixGroup = { id: string; label: string; rows: MatrixRow[] };

export type Permissions = Record<string, string[]>;

/**
 * Rows of the matrix from the scope catalog: a cell exists when `family:action` is catalogued. Hidden scopes and
 * org-level families stay out unless the role already holds them (so they can still be removed).
 */
export function buildMatrix(catalog: readonly ScopeOut[], held: Permissions): MatrixGroup[] {
  const holds = (spec: ScopeOut) => (held[spec.family] ?? []).includes(spec.action);
  const visible = catalog.filter(
    (spec) => holds(spec) || (!spec.hidden && !ORG_LEVEL.test(spec.family) && !spec.family.includes("*")),
  );
  const byFamily = new Map<string, ScopeOut[]>();
  for (const spec of visible) {
    const list = byFamily.get(spec.family) ?? [];
    list.push(spec);
    byFamily.set(spec.family, list);
  }
  const placed = new Set(MATRIX_GROUPS.flatMap((group) => group.families));
  const leftovers = [...byFamily.keys()].filter((family) => !placed.has(family)).sort();

  return MATRIX_GROUPS.map((group) => {
    const families = group.id === "platform" ? [...group.families, ...leftovers] : group.families;
    const rows: MatrixRow[] = [];
    for (const family of families) {
      const specs = byFamily.get(family);
      if (!specs) continue;
      const cells: Partial<Record<MatrixAction, ScopeOut>> = {};
      const extras: ScopeOut[] = [];
      for (const spec of specs) {
        if (isMatrixAction(spec.action)) cells[spec.action] = spec;
        else extras.push(spec);
      }
      const hasCells = Object.keys(cells).length > 0;
      if (hasCells) rows.push({ kind: "family", family, label: familyLabel(family), cells });
      for (const spec of extras.sort((a, b) => a.action.localeCompare(b.action))) {
        rows.push({
          kind: "extra",
          family,
          label: hasCells ? spec.description : familyLabel(family),
          spec,
        });
      }
    }
    return { id: group.id, label: group.label, rows };
  }).filter((group) => group.rows.length > 0);
}

export type RunChoice = "all" | string[];

export type RoleDraft = {
  name: string;
  description: string;
  color: string;
  permissions: Permissions;
  runScope: Record<RunResource, RunChoice>;
  /** `null`: bindable on every instance. */
  bindable: string[] | null;
};

function sortedPermissions(permissions: Record<string, readonly string[]>): Permissions {
  const out: Permissions = {};
  for (const family of Object.keys(permissions).sort()) {
    const actions = [...new Set(permissions[family] ?? [])].sort();
    if (actions.length) out[family] = actions;
  }
  return out;
}

export function draftOf(role: RoleOut): RoleDraft {
  const runScope = {} as Record<RunResource, RunChoice>;
  for (const resource of RUN_RESOURCES) {
    const value = role.run_scope[resource];
    runScope[resource] = Array.isArray(value) && value.length ? [...value] : "all";
  }
  return {
    name: role.name,
    description: role.description,
    color: role.color,
    permissions: sortedPermissions(role.permissions),
    runScope,
    bindable: role.bindable_instance_ids ? [...role.bindable_instance_ids] : null,
  };
}

export function has(permissions: Permissions, family: string, action: string): boolean {
  return (permissions[family] ?? []).includes(action);
}

export function withCell(permissions: Permissions, family: string, action: string, on: boolean): Permissions {
  const current = permissions[family] ?? [];
  const next = on ? [...current, action] : current.filter((item) => item !== action);
  return sortedPermissions({ ...permissions, [family]: next });
}

/** `family:action` for every checked cell. */
export function cellsOf(permissions: Permissions): Set<string> {
  return new Set(
    Object.entries(permissions).flatMap(([family, actions]) =>
      actions.map((action) => `${family}:${action}`),
    ),
  );
}

export function changedCells(base: RoleDraft, draft: RoleDraft): Set<string> {
  const before = cellsOf(base.permissions);
  const after = cellsOf(draft.permissions);
  return new Set([...before, ...after].filter((cell) => before.has(cell) !== after.has(cell)));
}

/** What is actually sent for a resource: a selection only counts while the role can run that resource. */
function effectiveRun(draft: RoleDraft, resource: RunResource): string {
  const choice = draft.runScope[resource];
  if (choice === "all" || !has(draft.permissions, resource, "run")) return "all";
  return JSON.stringify([...choice].sort());
}

export function runScopeChanged(base: RoleDraft, draft: RoleDraft, resource: RunResource): boolean {
  return effectiveRun(base, resource) !== effectiveRun(draft, resource);
}

export function bindableOn(bindable: string[] | null, instanceId: string): boolean {
  return bindable === null || bindable.includes(instanceId);
}

/** Toggle one instance pill; every instance on means "all" (`null`), so new instances are included too. */
export function toggleInstance(bindable: string[] | null, instanceId: string, all: readonly string[]) {
  const current = bindable ?? [...all];
  const next = current.includes(instanceId)
    ? current.filter((id) => id !== instanceId)
    : [...current, instanceId];
  return all.length > 0 && all.every((id) => next.includes(id)) ? null : next;
}

/** The save bar's count: changed cells, run-scope changes, instance toggles and name/description/color edits. */
export function changeCount(base: RoleDraft, draft: RoleDraft, instanceIds: readonly string[]): number {
  let count = changedCells(base, draft).size;
  count += RUN_RESOURCES.filter((resource) => runScopeChanged(base, draft, resource)).length;
  count += instanceIds.filter(
    (id) => bindableOn(base.bindable, id) !== bindableOn(draft.bindable, id),
  ).length;
  if (base.name.trim() !== draft.name.trim()) count += 1;
  if (base.description.trim() !== draft.description.trim()) count += 1;
  if (base.color.toLowerCase() !== draft.color.toLowerCase()) count += 1;
  return count;
}

export function bodyOf(draft: RoleDraft): RoleIn {
  const runScope: Record<string, string[]> = {};
  for (const resource of RUN_RESOURCES) {
    const choice = draft.runScope[resource];
    if (choice !== "all" && has(draft.permissions, resource, "run")) runScope[resource] = choice;
  }
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    color: draft.color,
    permissions: sortedPermissions(draft.permissions),
    run_scope: runScope,
    bindable_instance_ids: draft.bindable,
  };
}

/** Starting point of a blank role: the control plane needs at least one permission. */
export const BLANK_PERMISSIONS: Permissions = { agents: ["read"] };

export const ROLE_COLORS: readonly { value: string; label: string }[] = [
  { value: "#C5F25C", label: "Lime" },
  { value: "#7DA6FF", label: "Blue" },
  { value: "#B79CFF", label: "Purple" },
  { value: "#F2B54B", label: "Amber" },
  { value: "#FF8A80", label: "Coral" },
  { value: "#5CD6C2", label: "Teal" },
  { value: "#A9AFB8", label: "Grey" },
];

/** One line per scope for the token-scopes aside: added, removed, or unchanged (`note`). */
export function scopeLines(
  scopes: readonly string[],
  added: readonly string[],
  removed: readonly string[],
): { op: "add" | "remove" | "note"; text: string }[] {
  const plus = new Set(added);
  const minus = new Set(removed);
  return [...new Set([...scopes, ...removed])].sort().map((text) => ({
    op: plus.has(text) ? "add" : minus.has(text) ? "remove" : "note",
    text,
  }));
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${String(count)} ${count === 1 ? one : many}`;
}

/** "9 people · 2 groups": who holds a role. */
export function holdersLabel(role: Pick<RoleOut, "people" | "groups" | "service_accounts">): string {
  const parts = [plural(role.people, "person", "people")];
  if (role.groups) parts.push(plural(role.groups, "group"));
  if (role.service_accounts) parts.push(plural(role.service_accounts, "service account"));
  return parts.join(" · ");
}

/** A binding that keeps a role from being deleted (the 409 problem's `bindings`). */
export type BlockingBinding = {
  id: string;
  principal_kind: "user" | "group" | "service_account";
  principal_id: string;
  principal_name?: string | null;
  instance_id: string | null;
};

export function blockingBindings(error: unknown): BlockingBinding[] | undefined {
  if (typeof error !== "object" || error === null || !("bindings" in error)) return undefined;
  const bindings = error.bindings;
  return Array.isArray(bindings) ? (bindings as BlockingBinding[]) : undefined;
}
