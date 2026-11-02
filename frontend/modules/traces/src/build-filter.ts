// The trace list's filters as AgentOS's FilterExpr DSL for `POST /traces/search`. Only keys and operators that
// `GET /traces/filter-schema` advertises are used, so a runtime without a field never gets a filter it rejects.
import type { AgentOS } from "@agnostic/api";

export type TraceRange = "1h" | "24h" | "7d" | "30d";

export type TraceFilters = {
  q?: string | undefined;
  status?: "OK" | "ERROR" | undefined;
  /** `agent:support-triage`, `team:research-team`, `workflow:daily-brief`. */
  component?: string | undefined;
  user?: string | undefined;
  session?: string | undefined;
  runId?: string | undefined;
  range: TraceRange;
};

export type FilterExpr =
  | {
      op: "EQ" | "NEQ" | "GT" | "GTE" | "LT" | "LTE" | "CONTAINS" | "STARTSWITH";
      key: string;
      value: unknown;
    }
  | { op: "IN"; key: string; values: unknown[] }
  | { op: "AND" | "OR"; conditions: FilterExpr[] };

const RANGE_MS: Record<TraceRange, number> = {
  "1h": 3_600_000,
  "24h": 86_400_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
};

/** What a runtime supports when it has no filter-schema (agno 3.1 defaults). */
const DEFAULT_FIELDS: AgentOS.FilterFieldSchema[] = [
  ...["trace_id", "run_id", "session_id", "name", "user_id", "agent_id", "team_id", "workflow_id"].map(
    (key) => ({
      key,
      label: key,
      type: "string",
      operators: ["EQ", "NEQ", "CONTAINS", "STARTSWITH", "IN"],
    }),
  ),
  { key: "status", label: "Status", type: "enum", operators: ["EQ", "NEQ", "IN"], values: ["OK", "ERROR"] },
  { key: "start_time", label: "Start time", type: "datetime", operators: ["GT", "GTE", "LT", "LTE"] },
];

/** Free text matches these fields (names first; inputs and outputs aren't filterable columns in agno 3.1). */
const TEXT_KEYS = ["name", "trace_id", "run_id", "session_id", "user_id"];

export function buildTraceFilter(
  filters: TraceFilters,
  schema: AgentOS.FilterSchemaResponse | undefined,
  now: Date = new Date(),
): FilterExpr | undefined {
  const fields = new Map((schema?.fields ?? DEFAULT_FIELDS).map((field) => [field.key, field]));
  const supports = (key: string, op: string) =>
    fields.get(key)?.operators.some((operator) => operator.toUpperCase() === op) ?? false;
  const conditions: FilterExpr[] = [];
  const equal = (key: string, value: string | undefined) => {
    if (value && supports(key, "EQ")) conditions.push({ op: "EQ", key, value });
  };

  equal("status", filters.status);
  if (filters.component) {
    const [kind, ...rest] = filters.component.split(":");
    equal(`${kind ?? "agent"}_id`, rest.join(":"));
  }
  equal("user_id", filters.user);
  equal("session_id", filters.session);
  equal("run_id", filters.runId);
  if (supports("start_time", "GTE"))
    conditions.push({
      op: "GTE",
      key: "start_time",
      value: new Date(now.getTime() - RANGE_MS[filters.range]).toISOString(),
    });
  const text = filters.q?.trim();
  if (text) {
    const matches = TEXT_KEYS.filter((key) => supports(key, "CONTAINS")).map((key): FilterExpr => ({
      op: "CONTAINS",
      key,
      value: text,
    }));
    if (matches.length === 1 && matches[0]) conditions.push(matches[0]);
    else if (matches.length > 1) conditions.push({ op: "OR", conditions: matches });
  }
  if (conditions.length === 0) return undefined;
  return conditions.length === 1 ? conditions[0] : { op: "AND", conditions };
}
