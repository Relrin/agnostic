// URL state, list queries and wording shared by the audit log, its saved views, the event aside and the export
// dialog: filters live in the URL (and in saved views) with the same keys the API takes.
import type { AuditEventOut, AuditListEventsData } from "@agnostic/api";
import type { DiffLine } from "@agnostic/ui";

export const FILTER_KEYS = [
  "q",
  "actor",
  "actor_kind",
  "action",
  "decision",
  "instance",
  "resource",
  "source",
  "since",
  "until",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type AuditFilters = Partial<Record<FilterKey, string | undefined>>;
export type AuditSearch = AuditFilters & { event?: string | undefined };

export type ActorKind = AuditEventOut["actor"]["kind"];
export type Decision = AuditEventOut["decision"];
export type Source = AuditEventOut["source"];

export const ACTOR_KINDS = ["user", "service_account", "system", "anonymous"] as const satisfies ActorKind[];
export const DECISIONS = ["allowed", "denied", "n_a"] as const satisfies Decision[];
export const SOURCES = ["control_plane", "agentos"] as const satisfies Source[];

export const ACTOR_KIND_LABELS: Record<ActorKind, string> = {
  user: "Any person",
  service_account: "Any service account",
  system: "System",
  anonymous: "Anonymous",
};
export const DECISION_LABELS: Record<Decision, string> = {
  allowed: "Allowed",
  denied: "Denied",
  n_a: "Not checked",
};
export const SOURCE_LABELS: Record<Source, string> = { control_plane: "Agnostic", agentos: "AgentOS" };

export const PAGE_SIZE = 50;
/** Retention when the policy can't be read (the default hot window). */
export const DEFAULT_RETENTION_DAYS = 400;

const ENUMS: Partial<Record<FilterKey, readonly string[]>> = {
  actor_kind: ACTOR_KINDS,
  decision: DECISIONS,
  source: SOURCES,
};

function clean(key: FilterKey, value: unknown): string | undefined {
  const text = typeof value === "number" ? String(value) : typeof value === "string" ? value.trim() : "";
  if (!text) return undefined;
  const allowed = ENUMS[key];
  return allowed && !allowed.includes(text) ? undefined : text;
}

export function readSearch(search: Record<string, unknown>): AuditSearch {
  const state: AuditSearch = {};
  for (const key of FILTER_KEYS) {
    const value = clean(key, search[key]);
    if (value) state[key] = value;
  }
  const event = typeof search.event === "string" && search.event.trim() ? search.event.trim() : undefined;
  if (event) state.event = event;
  return state;
}

/** Search params as they go in the URL: empty values left out. */
export function toSearch(state: AuditSearch): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(state)) {
    if (typeof value === "string" && value) out[key] = value;
  }
  return out;
}

/** Only the filter keys (no selection), e.g. for a saved view or an export. */
export function filtersOf(state: AuditFilters | Record<string, unknown>): AuditFilters {
  const out: AuditFilters = {};
  for (const key of FILTER_KEYS) {
    const value = clean(key, (state as Record<string, unknown>)[key]);
    if (value) out[key] = value;
  }
  return out;
}

export function hasFilters(filters: AuditFilters): boolean {
  return FILTER_KEYS.some((key) => filters[key]);
}

function sameValue(key: FilterKey, a: string | undefined, b: string | undefined): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (key === "since" || key === "until") return Date.parse(a) === Date.parse(b);
  return false;
}

/** Saved views store times as the API formats them; compare instants, not strings. */
export function sameFilters(a: AuditFilters, b: AuditFilters): boolean {
  return FILTER_KEYS.every((key) => sameValue(key, a[key], b[key]));
}

export type EventsQuery = NonNullable<AuditListEventsData["query"]>;

/** The list (and export) query for a set of filters; enum values were checked when the URL was read. */
export function eventsQuery(filters: AuditFilters): Omit<EventsQuery, "limit" | "cursor"> {
  const query: Omit<EventsQuery, "limit" | "cursor"> = {};
  if (filters.q) query.q = filters.q;
  if (filters.actor) query.actor = filters.actor;
  if (filters.actor_kind) query.actor_kind = filters.actor_kind as ActorKind;
  if (filters.action) query.action = filters.action;
  if (filters.decision) query.decision = filters.decision as Decision;
  if (filters.instance) query.instance = filters.instance;
  if (filters.resource) query.resource = filters.resource;
  if (filters.source) query.source = filters.source as Source;
  if (filters.since) query.since = filters.since;
  if (filters.until) query.until = filters.until;
  return query;
}

/** `?format=csv&decision=denied…` for the streaming export. */
export function exportPath(format: "csv" | "jsonl", filters: AuditFilters): string {
  const params = new URLSearchParams({ format });
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (value) params.set(key, value);
  }
  return `/api/v1/audit/export?${params.toString()}`;
}

// ---------------------------------------------------------------- time

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "17:04:12" (UTC). */
export function utcTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(11, 19);
}

/** "31 Oct" (UTC). */
export function utcDay(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `${String(date.getUTCDate())} ${MONTHS[date.getUTCMonth()] ?? ""}`;
}

/** "31 Oct 14:00" (UTC). */
function utcMoment(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${utcDay(date)} ${date.toISOString().slice(11, 16)}`;
}

export function startOfUtcDay(now: Date = new Date()): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}

export type RangePreset = { id: string; label: string; since: (now: Date) => Date };

const HOUR = 3_600_000;
export const RANGE_PRESETS: readonly RangePreset[] = [
  { id: "1h", label: "Last hour", since: (now) => new Date(now.getTime() - HOUR) },
  { id: "today", label: "Today", since: (now) => startOfUtcDay(now) },
  { id: "24h", label: "Last 24 hours", since: (now) => new Date(now.getTime() - 24 * HOUR) },
  { id: "7d", label: "Last 7 days", since: (now) => new Date(now.getTime() - 7 * 24 * HOUR) },
  { id: "30d", label: "Last 30 days", since: (now) => new Date(now.getTime() - 30 * 24 * HOUR) },
];

/** The date chip: "Any time", "Today, 31 Oct", "28 Oct 09:00 – now". */
export function describeRange(
  since: string | undefined,
  until: string | undefined,
  now = new Date(),
): string {
  if (!since && !until) return "Any time";
  if (since && !until && Date.parse(since) === startOfUtcDay(now).getTime()) return `Today, ${utcDay(now)}`;
  return `${since ? utcMoment(since) : "start"} – ${until ? utcMoment(until) : "now"}`;
}

/** `<input type="datetime-local">` ⇄ ISO, read as UTC (the log's clock). */
export function fromLocalInput(value: string): string | undefined {
  if (!value) return undefined;
  const date = new Date(`${value.length === 16 ? `${value}:00` : value}Z`);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

export function toLocalInput(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString().slice(0, 16);
}

/** "2 s ago", "4 min ago", "3 h ago". */
export function shortAgo(value: string | null | undefined, now: Date = new Date()): string | undefined {
  if (!value) return undefined;
  const seconds = Math.max(0, Math.round((now.getTime() - Date.parse(value)) / 1000));
  if (Number.isNaN(seconds)) return undefined;
  if (seconds < 60) return `${String(seconds)} s ago`;
  if (seconds < 3600) return `${String(Math.round(seconds / 60))} min ago`;
  if (seconds < 86_400) return `${String(Math.round(seconds / 3600))} h ago`;
  return `${String(Math.round(seconds / 86_400))} d ago`;
}

// ---------------------------------------------------------------- events

const STATUS_TEXT: Record<number, string> = {
  200: "OK",
  201: "Created",
  202: "Accepted",
  204: "No Content",
  400: "Bad Request",
  401: "Unauthorized",
  403: "Forbidden",
  404: "Not Found",
  409: "Conflict",
  413: "Content Too Large",
  422: "Unprocessable Content",
  429: "Too Many Requests",
  500: "Internal Server Error",
  502: "Bad Gateway",
  503: "Service Unavailable",
};

/** 403 → "403 Forbidden". */
export function responseText(status: number | null): string | undefined {
  if (status === null) return undefined;
  const text = STATUS_TEXT[status];
  return text ? `${String(status)} ${text}` : String(status);
}

/** The small line under a decision: the missing scope on a denial, the scope that allowed it otherwise. */
export function scopeLine(
  event: Pick<AuditEventOut, "decision" | "missing_scopes" | "scope_checked">,
): string {
  if (event.decision === "denied" && event.missing_scopes.length)
    return `missing ${event.missing_scopes.join(", ")}`;
  return event.scope_checked ?? "";
}

/** The scopes a temporary grant or request would add for a denied event. */
export function scopesToGrant(event: Pick<AuditEventOut, "missing_scopes" | "scope_checked">): string[] {
  if (event.missing_scopes.length) return [...event.missing_scopes];
  return event.scope_checked ? [event.scope_checked] : [];
}

export function isMachine(kind: ActorKind): boolean {
  return kind === "service_account" || kind === "system";
}

export function avatarKind(kind: ActorKind): "human" | "machine" | "system" {
  if (kind === "service_account") return "machine";
  if (kind === "system" || kind === "anonymous") return "system";
  return "human";
}

// ---------------------------------------------------------------- diffs

export type DiffView =
  | { kind: "lines"; title: string | undefined; lines: DiffLine[]; note: string | undefined }
  | {
      kind: "args";
      title: string | undefined;
      before: Record<string, unknown>;
      after: Record<string, unknown>;
      note: string | undefined;
    }
  | { kind: "json"; title: string | undefined; value: unknown };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const OPS: Record<string, DiffLine["op"]> = {
  add: "add",
  "+": "add",
  added: "add",
  remove: "remove",
  "-": "remove",
  "−": "remove",
  removed: "remove",
  change: "change",
  "~": "change",
  changed: "change",
};

function diffLine(value: unknown): DiffLine | undefined {
  if (typeof value === "string") return { op: "note", text: value };
  if (!isRecord(value) || typeof value.text !== "string") return undefined;
  const op = typeof value.op === "string" ? (OPS[value.op] ?? "note") : "note";
  return { op, text: value.text };
}

/**
 * An event's diff as it should be drawn: `{title, lines, note}` (roles, groups, bindings, requests) as a scope
 * diff, `{before, after}` or `{field: {before, after}}` as changed arguments, anything else as JSON.
 */
export function diffView(diff: Record<string, unknown> | null): DiffView | undefined {
  if (!diff || Object.keys(diff).length === 0) return undefined;
  const title = typeof diff.title === "string" ? diff.title : undefined;
  const note = typeof diff.note === "string" && diff.note ? diff.note : undefined;
  if (Array.isArray(diff.lines)) {
    const lines = diff.lines.map(diffLine).filter((line): line is DiffLine => line !== undefined);
    return { kind: "lines", title, lines, note };
  }
  if (isRecord(diff.before) || isRecord(diff.after)) {
    return {
      kind: "args",
      title,
      before: isRecord(diff.before) ? diff.before : {},
      after: isRecord(diff.after) ? diff.after : {},
      note,
    };
  }
  const rest = Object.fromEntries(
    Object.entries(diff).filter(([key]) => key !== "title" && key !== "note" && key !== "version"),
  );
  const fields = Object.entries(rest);
  if (
    fields.length > 0 &&
    fields.every(([, value]) => isRecord(value) && ("before" in value || "after" in value))
  ) {
    const before: Record<string, unknown> = {};
    const after: Record<string, unknown> = {};
    for (const [key, value] of fields) {
      const change = value as Record<string, unknown>;
      before[key] = change.before;
      after[key] = change.after;
    }
    return { kind: "args", title, before, after, note };
  }
  return { kind: "json", title, value: Object.keys(rest).length ? rest : diff };
}

// ---------------------------------------------------------------- links

export type EventLink = { key: string; label: string; to: string; search: Record<string, string> };

const LINK_LABELS: Record<string, string> = {
  role: "Open role",
  group: "Open group",
  person: "Open person",
  requests: "Open access requests",
  settings: "Open settings",
  schedule: "Open schedule",
  job: "Open job",
  approval: "Open approval",
  service_account: "Open service account",
};

function splitPath(path: string): { to: string; search: Record<string, string> } {
  const url = new URL(path, "http://agnostic.invalid");
  return { to: url.pathname, search: Object.fromEntries(url.searchParams.entries()) };
}

/** Deep links from `event.links` (paths, run and session ids) and the approval the event is about. */
export function eventLinks(event: AuditEventOut, instanceSlug: string | undefined): EventLink[] {
  const out: EventLink[] = [];
  const links = event.links ?? {};
  for (const [key, value] of Object.entries(links)) {
    if (typeof value !== "string" || !value.startsWith("/")) continue;
    out.push({ key, label: LINK_LABELS[key] ?? `Open ${key.replace(/_/g, " ")}`, ...splitPath(value) });
  }
  if (instanceSlug) {
    const base = `/i/${encodeURIComponent(instanceSlug)}`;
    const run = links.run_id;
    const session = links.session_id;
    if (typeof run === "string" && run)
      out.push({ key: "run_id", label: `Open trace ${run}`, to: `${base}/traces`, search: { run_id: run } });
    if (typeof session === "string" && session)
      out.push({
        key: "session_id",
        label: `Open session ${session}`,
        to: `${base}/sessions/${encodeURIComponent(session)}`,
        search: {},
      });
    if (
      event.resource_kind === "approval" &&
      event.resource_id &&
      !out.some((link) => link.key === "approval")
    )
      out.push({
        key: "approval",
        label: "Open approval",
        to: `${base}/approvals`,
        search: { approval: event.resource_id },
      });
  }
  return out;
}

// ---------------------------------------------------------------- summaries

const FILTER_LABELS: Record<FilterKey, string> = {
  q: "Search",
  actor: "Actor",
  actor_kind: "Actor",
  action: "Action",
  decision: "Decision",
  instance: "Instance",
  resource: "Resource",
  source: "Source",
  since: "Since",
  until: "Until",
};

/** "Decision: Denied · Instance: prod-agentos" (or "All events"), for the save and export dialogs. */
export function filterSummary(
  filters: AuditFilters,
  names: { actor?: (id: string) => string; instance?: (id: string) => string } = {},
): string {
  const parts: string[] = [];
  for (const key of FILTER_KEYS) {
    const value = filters[key];
    if (!value || key === "until") continue;
    let shown: string = value;
    if (key === "actor") shown = names.actor?.(value) ?? value;
    else if (key === "instance") shown = names.instance?.(value) ?? value;
    else if (key === "actor_kind") shown = ACTOR_KIND_LABELS[value as ActorKind];
    else if (key === "decision") shown = DECISION_LABELS[value as Decision];
    else if (key === "source") shown = SOURCE_LABELS[value as Source];
    else if (key === "since") {
      parts.push(`When: ${describeRange(filters.since, filters.until)}`);
      continue;
    }
    parts.push(`${FILTER_LABELS[key]}: ${shown}`);
  }
  if (filters.until && !filters.since) parts.push(`When: ${describeRange(undefined, filters.until)}`);
  return parts.length ? parts.join(" · ") : "All events";
}
