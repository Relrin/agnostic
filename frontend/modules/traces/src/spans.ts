// AgentOS trace details (a TraceNode tree) as flat waterfall rows with OpenInference-style attributes. Mirrors the
// backend parser, so span ids line up with the ghost bars of `…/traces/{id}/comparison`.
import type { AgentOS } from "@agnostic/api";
import type { SpanKindName, SpanRowView } from "@agnostic/ui";

export type FlatSpan = SpanRowView & { attributes: Record<string, unknown> };

const KINDS: Record<string, SpanKindName> = {
  WORKFLOW: "workflow",
  CHAIN: "workflow",
  STEP: "step",
  AGENT: "agent",
  TEAM: "team",
  LLM: "model",
  TOOL: "tool",
};
const OPENINFERENCE: Record<SpanKindName, string> = {
  workflow: "CHAIN",
  step: "CHAIN",
  agent: "AGENT",
  team: "AGENT",
  model: "LLM",
  tool: "TOOL",
  other: "UNKNOWN",
};
const METADATA_KEYS: Record<string, string> = {
  model: "llm.model_name",
  input_tokens: "llm.token_count.prompt",
  output_tokens: "llm.token_count.completion",
  total_input_tokens: "llm.token_count.prompt",
  total_output_tokens: "llm.token_count.completion",
  tool_name: "tool.name",
  parameters: "tool.parameters",
  run_id: "agno.run.id",
  session_id: "session.id",
  user_id: "user.id",
};

function time(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? undefined : parsed;
}

/** "1.50s", "350ms" → milliseconds. */
export function parseDuration(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const match = /^([\d.]+)\s*(ms|s|m)?$/.exec(value.trim());
  if (!match) return undefined;
  const amount = Number(match[1]);
  return match[2] === "ms" ? amount : match[2] === "m" ? amount * 60_000 : amount * 1000;
}

function attributes(
  node: AgentOS.TraceNode,
  kind: SpanKindName,
  durationMs: number,
): Record<string, unknown> {
  const result: Record<string, unknown> = { "openinference.span.kind": OPENINFERENCE[kind] };
  for (const [key, value] of Object.entries(node.metadata ?? {})) result[METADATA_KEYS[key] ?? key] = value;
  if (kind === "tool" && !("tool.name" in result)) result["tool.name"] = node.name;
  if (node.step_type) result["agno.step.type"] = node.step_type;
  result["input.value"] = node.input ?? null;
  result["output.value"] = node.output ?? null;
  result.status = node.status.toUpperCase();
  result.duration_ms = Math.round(durationMs);
  if (node.error) {
    const match = /^([A-Z][\w.]*): (.+)$/s.exec(node.error);
    if (match) {
      result["exception.type"] = match[1];
      result["exception.message"] = match[2];
    } else {
      result["exception.message"] = node.error;
    }
  }
  return result;
}

/** Depth first, children by start time (the waterfall's row order). */
export function flattenTrace(detail: AgentOS.TraceDetail): FlatSpan[] {
  const origin = time(detail.start_time);
  const spans: FlatSpan[] = [];
  const visit = (node: AgentOS.TraceNode, depth: number) => {
    const start = time(node.start_time);
    const end = time(node.end_time);
    const durationMs =
      start !== undefined && end !== undefined
        ? Math.max(end - start, 0)
        : (parseDuration(node.duration) ?? 0);
    const base = KINDS[node.type.toUpperCase()] ?? "other";
    const kind: SpanKindName = depth > 0 && (node.step_type || base === "workflow") ? "step" : base;
    spans.push({
      id: node.id,
      name: node.name,
      kind,
      depth,
      startMs: start !== undefined && origin !== undefined ? Math.max(start - origin, 0) : 0,
      durationMs,
      failed: node.status.toUpperCase() === "ERROR",
      attributes: attributes(node, kind, durationMs),
    });
    const children = [...(node.spans ?? [])].sort(
      (a, b) => (time(a.start_time) ?? 0) - (time(b.start_time) ?? 0),
    );
    for (const child of children) visit(child, depth + 1);
  };
  for (const root of [...detail.tree].sort((a, b) => (time(a.start_time) ?? 0) - (time(b.start_time) ?? 0)))
    visit(root, 0);
  return spans;
}

export type ModelRollup = { model: string; calls: number; prompt: number; completion: number };

/** Model calls in the trace, per model (most tokens first). */
export function modelRollup(spans: readonly FlatSpan[]): ModelRollup[] {
  const totals = new Map<string, ModelRollup>();
  for (const span of spans) {
    if (span.kind !== "model") continue;
    const named = span.attributes["llm.model_name"];
    const model = typeof named === "string" && named ? named : span.name;
    const entry = totals.get(model) ?? { model, calls: 0, prompt: 0, completion: 0 };
    entry.calls += 1;
    entry.prompt += Number(span.attributes["llm.token_count.prompt"] ?? 0);
    entry.completion += Number(span.attributes["llm.token_count.completion"] ?? 0);
    totals.set(model, entry);
  }
  return [...totals.values()].sort((a, b) => b.prompt + b.completion - (a.prompt + a.completion));
}

export function traceDurationMs(
  trace: Pick<AgentOS.TraceSummary, "start_time" | "end_time" | "duration">,
): number {
  const start = time(trace.start_time);
  const end = time(trace.end_time);
  return start !== undefined && end !== undefined ? end - start : (parseDuration(trace.duration) ?? 0);
}

/** Total tokens of a trace detail (the root span carries the totals). */
export function traceTokens(detail: { tree?: AgentOS.TraceNode[] | null }): number | undefined {
  const metadata = detail.tree?.[0]?.metadata;
  if (!metadata) return undefined;
  const prompt = Number(metadata.total_input_tokens ?? 0);
  const completion = Number(metadata.total_output_tokens ?? 0);
  return prompt + completion || undefined;
}
