// AgentOS run events as they arrive over SSE (agent, team and workflow runs).
// Payloads vary across agno minors, so everything except `event` is optional and read defensively.

export type ToolExecution = {
  tool_call_id?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  result?: unknown;
  tool_call_error?: boolean | null;
  requires_confirmation?: boolean | null;
  confirmed?: boolean | null;
  requires_user_input?: boolean | null;
  external_execution_required?: boolean | null;
  metrics?: { duration?: number | null } | null;
  created_at?: number | null;
};

export type UserInputField = {
  name: string;
  field_type?: string | null;
  description?: string | null;
  required?: boolean | null;
  allowed_values?: unknown[] | null;
  value?: unknown;
};

/** A paused workflow step (HumanReview): confirmation, user input, route selection or output review. */
export type StepRequirement = {
  step_id?: string | null;
  step_name?: string | null;
  step_index?: number | null;
  requires_confirmation?: boolean | null;
  confirmation_message?: string | null;
  confirmed?: boolean | null;
  requires_user_input?: boolean | null;
  user_input_message?: string | null;
  user_input_schema?: UserInputField[] | null;
  user_input?: Record<string, unknown> | null;
  requires_route_selection?: boolean | null;
  available_choices?: string[] | null;
  selected_choices?: string[] | null;
  allow_multiple_selections?: boolean | null;
  requires_output_review?: boolean | null;
  step_output?: unknown;
  timeout_at?: number | string | null;
  member_agent_name?: string | null;
  [key: string]: unknown;
};

export type RunEvent = {
  event: string;
  event_index?: number | null;
  created_at?: number | null;
  run_id?: string | null;
  session_id?: string | null;
  parent_run_id?: string | null;
  nested_depth?: number | null;
  agent_id?: string | null;
  agent_name?: string | null;
  team_id?: string | null;
  team_name?: string | null;
  workflow_id?: string | null;
  workflow_run_id?: string | null;
  step_id?: string | null;
  step_name?: string | null;
  step_index?: number | number[] | null;
  model?: string | null;
  model_provider?: string | null;
  content?: unknown;
  content_type?: string | null;
  reasoning_content?: string | null;
  citations?: unknown;
  references?: unknown[] | null;
  metrics?: Record<string, unknown> | null;
  tool?: ToolExecution | null;
  tools?: ToolExecution[] | null;
  requirements?: Record<string, unknown>[] | null;
  step_requirements?: StepRequirement[] | null;
  error_type?: string | null;
  error_id?: string | null;
  reason?: string | null;
  session_state?: Record<string, unknown> | null;
  [key: string]: unknown;
};

/** `/resume` control events, not part of the run. */
export const META_EVENTS = new Set(["catch_up", "replay", "subscribed", "error"]);

const RUN_PREFIXES = ["Team", "Workflow"] as const;

/** `TeamRunContent` → `RunContent`, `TeamToolCallStarted` → `ToolCallStarted`; workflow events keep their names. */
export function baseEventName(name: string): string {
  if (name.startsWith("Team") && !name.startsWith("TeamTask")) return name.slice(RUN_PREFIXES[0].length);
  return name;
}

export function parseEvent(name: string | undefined, data: string): RunEvent | undefined {
  try {
    const parsed = JSON.parse(data) as unknown;
    if (typeof parsed !== "object" || parsed === null) return undefined;
    const payload = parsed as Record<string, unknown>;
    const event = typeof payload.event === "string" ? payload.event : name;
    if (!event || event === "message") return undefined;
    return { ...payload, event };
  } catch {
    return undefined;
  }
}
