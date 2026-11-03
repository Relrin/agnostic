// URL state, list queries and wording shared by the approvals inbox, its detail aside and the routing sheet.
import type { ApprovalOut, ApprovalsListApprovalsData, DecideOut, StatusName } from "@agnostic/api";
import { toDate } from "@agnostic/core";
import { formatCountdown } from "@agnostic/ui";
import type { QueryClient } from "@tanstack/react-query";

export const STATUSES = [
  "pending",
  "approved",
  "rejected",
  "expired",
  "cancelled",
] as const satisfies readonly StatusName[];

export const STATUS_LABELS: Record<StatusName, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Expired",
  cancelled: "Cancelled",
};

export const SOURCE_KINDS = ["agent", "team", "workflow", "schedule"] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];
export const APPROVAL_TYPES = ["blocking", "audit"] as const;
export type ApprovalType = (typeof APPROVAL_TYPES)[number];

export const PAGE_SIZE = 50;

export type ApprovalSearch = {
  status: StatusName;
  tool?: string | undefined;
  /** `agent`, or `agent:billing-agent`. */
  source?: string | undefined;
  user?: string | undefined;
  schedule?: string | undefined;
  type?: ApprovalType | undefined;
  q?: string | undefined;
  page: number;
  approval?: string | undefined;
  /** From a Slack deep link: the decision the person clicked (never submitted on its own). */
  intent?: "approve" | "reject" | undefined;
};

export function readSearch(search: Record<string, unknown>): ApprovalSearch {
  const text = (key: string) => {
    const value = search[key];
    if (typeof value === "number") return String(value);
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
  };
  const status = text("status");
  const type = text("type");
  const intent = text("intent");
  const page = Number(text("page") ?? 1);
  return {
    status: STATUSES.includes(status as StatusName) ? (status as StatusName) : "pending",
    tool: text("tool"),
    source: text("source"),
    user: text("user"),
    schedule: text("schedule"),
    type: APPROVAL_TYPES.includes(type as ApprovalType) ? (type as ApprovalType) : undefined,
    q: text("q"),
    page: Number.isInteger(page) && page > 0 ? page : 1,
    approval: text("approval"),
    intent: intent === "approve" || intent === "reject" ? intent : undefined,
  };
}

/** Search params as they go in the URL: defaults and empty values left out. */
export function toSearch(state: ApprovalSearch): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(state)) {
    if (value === undefined || value === "") continue;
    if (key === "status" && value === "pending") continue;
    if (key === "page" && value === 1) continue;
    out[key] = value;
  }
  return out;
}

export function splitSource(source: string | undefined): { kind?: SourceKind; id?: string } {
  if (!source) return {};
  const [kind, ...rest] = source.split(":");
  const id = rest.join(":");
  return {
    ...(SOURCE_KINDS.includes(kind as SourceKind) ? { kind: kind as SourceKind } : {}),
    ...(id ? { id } : {}),
  };
}

export function listQuery(state: ApprovalSearch): NonNullable<ApprovalsListApprovalsData["query"]> {
  const source = splitSource(state.source);
  return {
    status: state.status,
    page: state.page,
    limit: PAGE_SIZE,
    ...(state.tool ? { tool: state.tool } : {}),
    ...(state.type ? { type: state.type } : {}),
    ...(source.kind ? { source_kind: source.kind } : {}),
    ...(source.id ? { source_id: source.id } : {}),
    ...(state.user ? { user_id: state.user } : {}),
    ...(state.schedule ? { schedule_id: state.schedule } : {}),
    ...(state.q ? { q: state.q } : {}),
  };
}

/** Lists, counts and details of every instance: after a decision, or Refresh. */
export async function refreshApprovals(client: QueryClient): Promise<void> {
  await Promise.all(
    ["approvalsListApprovals", "approvalsApprovalCounts", "approvalsGetApproval"].map((id) =>
      client.invalidateQueries({ queryKey: [{ _id: id }] }),
    ),
  );
}

/** "2h 14m" since `value` (no "ago"): the Age column and "requested … ago". */
export function formatAge(value: string | null | undefined, now: Date = new Date()): string {
  const date = toDate(value);
  if (!date) return "—";
  return formatCountdown(date, now).replace(/^in /, "").replace(/ ago$/, "");
}

export function sourceName(row: Pick<ApprovalOut, "source_name" | "source_id" | "component_id">): string {
  return row.source_name ?? row.source_id ?? row.component_id ?? "—";
}

export function userLabel(row: Pick<ApprovalOut, "user_name" | "user_id">): string {
  return row.user_name ?? row.user_id ?? "—";
}

/** What happened after a decision, in one sentence. */
export function outcomeText(result: DecideOut): string {
  if (result.already_resolved) return `Someone already ${result.status} this request.`;
  const verb = result.status === "approved" ? "Approved" : "Rejected";
  const edited = result.args_changed.length ? ` with edited ${result.args_changed.join(", ")}` : "";
  switch (result.continue_state) {
    case "continued":
      return `${verb}${edited} · the run is continuing.`;
    case "pending_admin":
      return `${verb}${edited} · the run waits for an admin approval: ${result.continue_detail ?? ""}`;
    case "conflict":
      return `${verb}${edited} · another continuation owns the run; it resumes when that finishes.`;
    case "failed":
      return `${verb}${edited}, but the run didn't continue: ${result.continue_detail ?? "unknown error"}.`;
    default:
      return `${verb}${edited}.`;
  }
}

/** A tool argument as text in the edit form. */
export function argText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/** The edited text back as a value of the original's type; `undefined` when it doesn't parse. */
export function parseArg(original: unknown, text: string): { value: unknown } | undefined {
  if (typeof original === "number") {
    const number = Number(text);
    return text.trim() !== "" && Number.isFinite(number) ? { value: number } : undefined;
  }
  if (typeof original === "boolean") return { value: text === "true" };
  if (typeof original === "string") return { value: text };
  if (original === null || original === undefined) return { value: text === "" ? original : text };
  try {
    return { value: JSON.parse(text) as unknown };
  } catch {
    return undefined;
  }
}
