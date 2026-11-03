// The config document (Agno `to_dict()` shape) as plain JSON, with typed readers for the fields Studio shows.

export type Config = Record<string, unknown>;
export type EditableKind = "agent" | "team" | "workflow";
export type TeamMode = "coordinate" | "route" | "broadcast" | "tasks";
export const TEAM_MODES: readonly TeamMode[] = ["coordinate", "route", "broadcast", "tasks"];

export type ToolEntry = {
  name: string;
  toolkit?: string;
  requires_confirmation?: boolean;
  approval_type?: string;
  parameters?: unknown;
  [key: string]: unknown;
};

export type MemberEntry = { type: "agent" | "team"; agent_id?: string; team_id?: string };

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function text(config: Config, key: string): string | undefined {
  const value = config[key];
  return typeof value === "string" ? value : undefined;
}

export function flag(config: Config, key: string, fallback = false): boolean {
  const value = config[key];
  return typeof value === "boolean" ? value : fallback;
}

export function count(config: Config, key: string): number | undefined {
  const value = config[key];
  return typeof value === "number" ? value : undefined;
}

/** Instructions are a string or a list; the editor always works with the list. */
export function instructions(config: Config): string[] {
  const value = config.instructions;
  if (typeof value === "string") return value ? [value] : [];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function tools(config: Config): ToolEntry[] {
  const value = config.tools;
  return Array.isArray(value)
    ? value.filter((item): item is ToolEntry => isRecord(item) && typeof item.name === "string")
    : [];
}

export function members(config: Config): MemberEntry[] {
  const value = config.members;
  return Array.isArray(value) ? value.filter((item): item is MemberEntry => isRecord(item)) : [];
}

export function memberId(member: MemberEntry): string {
  return (member.type === "team" ? member.team_id : member.agent_id) ?? "";
}

/** The model's registry name (its id), from either stored form. */
export function modelId(value: unknown): string | undefined {
  if (isRecord(value) && typeof value.id === "string") return value.id;
  if (typeof value === "string" && value) return value.includes(":") ? value.split(":")[1] : value;
  return undefined;
}

export function refName(value: unknown, key = "name"): string | undefined {
  return isRecord(value) && typeof value[key] === "string" ? value[key] : undefined;
}

/** `mode` wins; without it agno derives the mode from the legacy flags. */
export function teamMode(config: Config): TeamMode {
  const mode = config.mode;
  if (typeof mode === "string" && (TEAM_MODES as readonly string[]).includes(mode)) return mode as TeamMode;
  if (flag(config, "respond_directly")) return "route";
  if (flag(config, "delegate_to_all_members")) return "broadcast";
  return "coordinate";
}

/** Set (or, with `undefined`, remove) a field without mutating the document. */
export function withField(config: Config, key: string, value: unknown): Config {
  const next = { ...config };
  if (value === undefined) {
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete -- config keys are field names
    delete next[key];
  } else {
    next[key] = value;
  }
  return next;
}

export function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Top-level fields whose values differ between two documents, in the order of `after`. */
export function changedFields(before: Config | undefined, after: Config): string[] {
  if (!before) return [];
  const keys = [...Object.keys(after), ...Object.keys(before).filter((key) => !(key in after))];
  return keys.filter((key) => !same(before[key], after[key]));
}

/** A short human form of a value: a model's id, a tool's name, on/off. */
export function display(value: unknown): string {
  if (value === undefined || value === null) return "none";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "string") return value.length > 40 ? `${value.slice(0, 39)}…` : value;
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return `${String(value.length)} item${value.length === 1 ? "" : "s"}`;
  if (isRecord(value)) {
    for (const key of ["id", "name", "agent_id", "team_id", "registry_id"]) {
      if (typeof value[key] === "string") return value[key];
    }
    return "{…}";
  }
  return JSON.stringify(value);
}

/** Pinned member versions from a version's links (`child_component_id` → `child_version`). */
/** Links that pin a child at a version: a team's members, a workflow's step executors. */
const PINNED_LINKS = new Set(["member", "step_agent", "step_team", "step_workflow"]);

export function pinsFrom(links: readonly Record<string, unknown>[] | undefined): Record<string, number> {
  const pins: Record<string, number> = {};
  for (const link of links ?? []) {
    if (typeof link.link_kind !== "string" || !PINNED_LINKS.has(link.link_kind)) continue;
    const child = link.child_component_id;
    const version = link.child_version;
    if (typeof child === "string" && typeof version === "number") pins[child] = version;
  }
  return pins;
}
