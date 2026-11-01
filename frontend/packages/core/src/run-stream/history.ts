// Stored runs (`GET /sessions/{id}/runs`) → the same RunState the live stream produces, so Chat and Sessions render
// history and live runs with one component. When a run kept its events (`store_events=True`), they are replayed
// through the reducer; otherwise the state is rebuilt from the run's fields.
import type { AgentOS } from "@agnostic/api";

import type { RunEvent, StepRequirement, ToolExecution } from "./events";
import {
  initialRunState,
  reduceAll,
  type ComponentKind,
  type RunState,
  type RunStatus,
  type ToolCall,
} from "./reducer";

export type StoredRun = AgentOS.RunSchema | AgentOS.TeamRunSchema | AgentOS.WorkflowRunSchema;

const STATUS: Record<string, RunStatus> = {
  PENDING: "pending",
  RUNNING: "running",
  COMPLETED: "completed",
  PAUSED: "paused",
  CANCELLED: "cancelled",
  ERROR: "error",
  REGENERATED: "completed",
};

export function runStatus(status: string | null | undefined): RunStatus {
  return STATUS[(status ?? "").toUpperCase()] ?? "completed";
}

function epochMs(value: string | number | null | undefined): number | undefined {
  if (value === null || value === undefined) return undefined;
  if (typeof value === "number") return value > 1e11 ? value : value * 1000;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function kindOf(run: StoredRun): ComponentKind {
  if ("workflow_id" in run || "step_results" in run) return "workflow";
  if ("team_id" in run) return "team";
  return "agent";
}

function storedTools(run: StoredRun): ToolCall[] {
  const tools = ("tools" in run ? run.tools : undefined) as ToolExecution[] | null | undefined;
  return (tools ?? []).flatMap((tool) => {
    const id = tool.tool_call_id ?? tool.tool_name;
    if (!id) return [];
    const paused =
      tool.requires_confirmation === true && tool.confirmed !== true && tool.result === undefined;
    return [
      {
        id,
        name: tool.tool_name ?? "tool",
        args: tool.tool_args ?? {},
        status: tool.tool_call_error ? "error" : paused ? "paused" : "done",
        durationMs: typeof tool.metrics?.duration === "number" ? tool.metrics.duration * 1000 : undefined,
        result: tool.result,
        requiresConfirmation: tool.requires_confirmation ?? undefined,
      } satisfies ToolCall,
    ];
  });
}

export function fromStoredRun(run: StoredRun, sessionId?: string): RunState {
  const kind = kindOf(run);
  const base = initialRunState({
    kind,
    runId: run.run_id,
    sessionId,
    input: run.run_input ?? undefined,
    componentId:
      ("workflow_id" in run ? run.workflow_id : undefined) ??
      ("team_id" in run ? run.team_id : undefined) ??
      ("agent_id" in run ? run.agent_id : undefined) ??
      undefined,
  });
  const events = (run.events ?? []) as RunEvent[];
  if (events.length > 0) {
    const replayed = reduceAll(events, { ...base, status: "running" });
    return {
      ...replayed,
      status: runStatus(run.status),
      input: base.input,
      startedAt: replayed.startedAt ?? epochMs(run.created_at),
    };
  }
  const status = runStatus(run.status);
  const content =
    typeof run.content === "string" ? run.content : run.content ? JSON.stringify(run.content, null, 2) : "";
  const tools = storedTools(run);
  const stepRequirements = ("step_requirements" in run ? run.step_requirements : undefined) as
    StepRequirement[] | null | undefined;
  return {
    ...base,
    status,
    content,
    reasoning: run.reasoning_content ?? "",
    tools,
    metrics: run.metrics ?? undefined,
    citations: run.citations ?? undefined,
    references: run.references ?? undefined,
    startedAt: epochMs(run.created_at),
    pause:
      status !== "paused"
        ? undefined
        : kind === "workflow"
          ? { kind: "steps", event: "StepPaused", stepRequirements: stepRequirements ?? [] }
          : kind === "team"
            ? { kind: "requirements", requirements: [] }
            : {
                kind: "tools",
                tools: tools
                  .filter((tool) => tool.status === "paused")
                  .map((tool) => ({
                    tool_call_id: tool.id,
                    tool_name: tool.name,
                    tool_args: tool.args,
                    requires_confirmation: true,
                  })),
              },
  };
}

/** Total tokens of a run's metrics (`total_tokens`, or input + output). */
export function runTokens(metrics: Record<string, unknown> | undefined): number | undefined {
  if (!metrics) return undefined;
  const total = metrics.total_tokens;
  if (typeof total === "number") return total;
  const input = typeof metrics.input_tokens === "number" ? metrics.input_tokens : 0;
  const output = typeof metrics.output_tokens === "number" ? metrics.output_tokens : 0;
  return input + output || undefined;
}
