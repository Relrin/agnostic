// Shared wording of the Evaluations page.
import type { BatchOut } from "@agnostic/api";

export type EvalType = BatchOut["eval_type"];

export const EVAL_TYPES: readonly EvalType[] = ["accuracy", "agent_as_judge", "reliability", "performance"];

export const TYPE_LABEL: Record<EvalType, string> = {
  accuracy: "Accuracy",
  agent_as_judge: "Agent as judge",
  reliability: "Reliability",
  performance: "Performance",
};

export const TYPE_HINT: Record<EvalType, string> = {
  accuracy: "Score against expected answers",
  agent_as_judge: "Custom criteria, judged by a model",
  reliability: "Expected tool calls and args",
  performance: "Latency and memory use",
};

/** Scores below this are highlighted (the default pass threshold). */
export const LOW_SCORE = 7;

export function scoreText(score: number | null | undefined): string {
  if (score === null || score === undefined) return "—";
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}

/** "Showing 5 of 25 · v3 → v4 · below 7: 1 → 4". */
export function casesNote(
  shown: number,
  total: number,
  labels: { before?: string; after: string },
  below: { before?: number; after: number },
): string {
  const head = `Showing ${String(shown)} of ${String(total)}`;
  if (labels.before !== undefined && below.before !== undefined)
    return `${head} · ${labels.before} → ${labels.after} · below ${String(LOW_SCORE)}: ${String(below.before)} → ${String(below.after)}`;
  return `${head} · ${String(below.after)} below ${String(LOW_SCORE)} in ${labels.after}`;
}
