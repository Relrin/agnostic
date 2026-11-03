// The run reducer: AgentOS SSE events → one RunState per run. Pure and tolerant: unknown events are counted,
// not fatal, and events already applied (same or lower event_index, e.g. replayed by /resume) are skipped.
import {
  baseEventName,
  META_EVENTS,
  type RunEvent,
  type StepRequirement,
  type ToolExecution,
} from "./events";

export type ComponentKind = "agent" | "team" | "workflow";
export type RunStatus = "pending" | "running" | "paused" | "completed" | "error" | "cancelled";

export type ToolCall = {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error" | "paused";
  startedAt?: number | undefined;
  durationMs?: number | undefined;
  result?: unknown;
  requiresConfirmation?: boolean | undefined;
};

export type MemberRun = {
  runId: string;
  name: string;
  agentId?: string | undefined;
  depth: number;
  content: string;
  tools: ToolCall[];
  status: RunStatus;
};

export type TeamTask = { id: string; title: string; status: string; assignee?: string | undefined };

export type StepKind = "step" | "loop" | "router" | "parallel" | "condition" | "steps";

export type StepNode = {
  id: string;
  name: string;
  kind: StepKind;
  status: RunStatus;
  children: StepNode[];
  content: string;
  tools: ToolCall[];
  iteration?: number | undefined;
  maxIterations?: number | undefined;
  selected?: string[] | undefined;
  startedAt?: number | undefined;
  endedAt?: number | undefined;
  error?: string | undefined;
};

export type Pause =
  | { kind: "tools"; tools: ToolExecution[] }
  | { kind: "requirements"; requirements: Record<string, unknown>[] }
  | { kind: "steps"; event: string; stepRequirements: StepRequirement[] };

export type RunState = {
  kind?: ComponentKind | undefined;
  runId?: string | undefined;
  sessionId?: string | undefined;
  componentId?: string | undefined;
  componentName?: string | undefined;
  model?: string | undefined;
  status: RunStatus;
  input?: string | undefined;
  content: string;
  /** The parsed output when the component has an output schema (the completed run's `content` is an object). */
  structured?: unknown;
  reasoning: string;
  tools: ToolCall[];
  members: Record<string, MemberRun>;
  memberOrder: string[];
  tasks: TeamTask[];
  steps: StepNode[];
  openSteps: string[];
  pause?: Pause | undefined;
  error?: { message: string; type?: string | undefined } | undefined;
  cancelReason?: string | undefined;
  metrics?: Record<string, unknown> | undefined;
  citations?: unknown;
  references?: unknown[] | undefined;
  sessionState?: Record<string, unknown> | undefined;
  startedAt?: number | undefined;
  endedAt?: number | undefined;
  lastEventIndex: number;
  eventCount: number;
  unknownEvents: number;
};

export function initialRunState(partial: Partial<RunState> = {}): RunState {
  return {
    status: "pending",
    content: "",
    reasoning: "",
    tools: [],
    members: {},
    memberOrder: [],
    tasks: [],
    steps: [],
    openSteps: [],
    lastEventIndex: -1,
    eventCount: 0,
    unknownEvents: 0,
    ...partial,
  };
}

export const TERMINAL: ReadonlySet<RunStatus> = new Set(["completed", "error", "cancelled", "paused"]);

/** Whether the stream for this run is finished (paused runs wait for /continue, which opens a new stream). */
export function isSettled(state: RunState): boolean {
  return TERMINAL.has(state.status);
}

// ---------------------------------------------------------------- helpers

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function isStructured(value: unknown): value is object {
  return typeof value === "object" && value !== null;
}

function seconds(event: RunEvent): number | undefined {
  return typeof event.created_at === "number" ? event.created_at * 1000 : undefined;
}

function toolFrom(execution: ToolExecution | null | undefined, event: RunEvent): ToolCall | undefined {
  if (!execution) return undefined;
  const id = execution.tool_call_id ?? execution.tool_name;
  if (!id) return undefined;
  return {
    id,
    name: execution.tool_name ?? "tool",
    args: execution.tool_args ?? {},
    status: "running",
    startedAt: seconds(event),
    requiresConfirmation: execution.requires_confirmation ?? undefined,
  };
}

function upsertTool(tools: ToolCall[], tool: ToolCall): ToolCall[] {
  const index = tools.findIndex((item) => item.id === tool.id);
  if (index === -1) return [...tools, tool];
  const next = tools.slice();
  next[index] = { ...tools[index], ...tool, startedAt: tools[index]?.startedAt ?? tool.startedAt };
  return next;
}

function finishTool(
  tools: ToolCall[],
  execution: ToolExecution | null | undefined,
  event: RunEvent,
  failed: boolean,
): ToolCall[] {
  const started = toolFrom(execution, event);
  if (!started) return tools;
  const existing = tools.find((item) => item.id === started.id);
  const end = seconds(event);
  const measured = execution?.metrics?.duration;
  const durationMs =
    typeof measured === "number"
      ? measured * 1000
      : existing?.startedAt !== undefined && end !== undefined
        ? end - existing.startedAt
        : undefined;
  // Completion events often omit the arguments: keep what the start event said.
  return upsertTool(tools, {
    ...started,
    args: execution?.tool_args ?? existing?.args ?? {},
    requiresConfirmation: existing?.requiresConfirmation ?? started.requiresConfirmation,
    status: failed || execution?.tool_call_error ? "error" : "done",
    result: execution?.result,
    durationMs,
  });
}

function pauseTools(tools: ToolCall[], paused: ToolExecution[]): ToolCall[] {
  let next = tools;
  for (const execution of paused) {
    const id = execution.tool_call_id ?? execution.tool_name;
    if (!id) continue;
    next = upsertTool(next, {
      id,
      name: execution.tool_name ?? "tool",
      args: execution.tool_args ?? {},
      status: "paused",
      requiresConfirmation: execution.requires_confirmation ?? undefined,
    });
  }
  return next;
}

function resumeTools(tools: ToolCall[]): ToolCall[] {
  return tools.map((tool) => (tool.status === "paused" ? { ...tool, status: "running" } : tool));
}

function mapSteps(nodes: StepNode[], id: string, update: (node: StepNode) => StepNode): StepNode[] {
  const next = nodes.map((node) => {
    if (node.id === id) return update(node);
    const children = mapSteps(node.children, id, update);
    return children === node.children ? node : { ...node, children };
  });
  return next.some((node, index) => node !== nodes[index]) ? next : nodes;
}

function findStep(nodes: readonly StepNode[], id: string): StepNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findStep(node.children, id);
    if (found) return found;
  }
  return undefined;
}

function stepKey(event: RunEvent, kind: StepKind): string {
  const index = Array.isArray(event.step_index) ? event.step_index.join(".") : (event.step_index ?? "");
  return event.step_id ?? `${kind}:${event.step_name ?? "step"}:${String(index)}`;
}

function openStep(state: RunState, event: RunEvent, kind: StepKind): RunState {
  const id = stepKey(event, kind);
  if (findStep(state.steps, id)) {
    return {
      ...state,
      steps: mapSteps(state.steps, id, (node) => ({ ...node, status: "running" })),
      openSteps: kind === "step" ? state.openSteps : [...state.openSteps, id],
    };
  }
  const node: StepNode = {
    id,
    name: event.step_name ?? kind,
    kind,
    status: "running",
    children: [],
    content: "",
    tools: [],
    startedAt: seconds(event),
    maxIterations: typeof event.max_iterations === "number" ? event.max_iterations : undefined,
  };
  const parent = state.openSteps.at(-1);
  const steps = parent
    ? mapSteps(state.steps, parent, (container) => ({
        ...container,
        children: [...container.children, node],
      }))
    : [...state.steps, node];
  return { ...state, steps, openSteps: kind === "step" ? state.openSteps : [...state.openSteps, id] };
}

function closeStep(state: RunState, event: RunEvent, kind: StepKind, status: RunStatus): RunState {
  const id = stepKey(event, kind);
  const content = text(event.content);
  const steps = mapSteps(state.steps, id, (node) => ({
    ...node,
    status,
    endedAt: seconds(event),
    content: node.content || content,
    error: status === "error" ? content || node.error : node.error,
    selected: Array.isArray(event.selected_steps)
      ? (event.selected_steps as unknown[]).map(String)
      : node.selected,
  }));
  return {
    ...state,
    steps,
    openSteps: kind === "step" ? state.openSteps : state.openSteps.filter((open) => open !== id),
  };
}

/** The innermost running step: where agent output inside a workflow belongs. */
function currentStepId(state: RunState, event: RunEvent): string | undefined {
  if (event.step_id && findStep(state.steps, event.step_id)) return event.step_id;
  const running = (nodes: readonly StepNode[]): string | undefined => {
    for (let index = nodes.length - 1; index >= 0; index -= 1) {
      const node = nodes[index];
      if (!node) continue;
      const inner = running(node.children);
      if (inner) return inner;
      if (node.kind === "step" && node.status === "running") return node.id;
    }
    return undefined;
  };
  return running(state.steps);
}

function memberOf(state: RunState, event: RunEvent): MemberRun {
  const runId = event.run_id ?? "member";
  return (
    state.members[runId] ?? {
      runId,
      name: event.agent_name ?? event.agent_id ?? event.team_name ?? "member",
      agentId: event.agent_id ?? undefined,
      depth: event.nested_depth ?? 1,
      content: "",
      tools: [],
      status: "running",
    }
  );
}

function withMember(state: RunState, member: MemberRun): RunState {
  const known = member.runId in state.members;
  return {
    ...state,
    members: { ...state.members, [member.runId]: member },
    memberOrder: known ? state.memberOrder : [...state.memberOrder, member.runId],
  };
}

function str(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value) return value;
    if (typeof value === "number") return String(value);
  }
  return undefined;
}

function upsertTask(tasks: TeamTask[], event: RunEvent): TeamTask[] {
  const raw = (typeof event.task === "object" && event.task !== null ? event.task : event) as Record<
    string,
    unknown
  >;
  const id = str(raw.task_id, raw.id);
  if (!id) return tasks;
  const index = tasks.findIndex((item) => item.id === id);
  const existing = index === -1 ? undefined : tasks[index];
  // Updates carry only what changed: merge them over what is known.
  const task: TeamTask = {
    id,
    title: str(raw.title, raw.description, raw.name) ?? existing?.title ?? id,
    status: str(raw.status, raw.state) ?? existing?.status ?? "pending",
    assignee:
      (typeof raw.assignee === "string"
        ? raw.assignee
        : typeof raw.member_id === "string"
          ? raw.member_id
          : undefined) ?? existing?.assignee,
  };
  if (index === -1) return [...tasks, task];
  const next = tasks.slice();
  next[index] = task;
  return next;
}

// ---------------------------------------------------------------- nested runs

function reduceNested(state: RunState, event: RunEvent, name: string): RunState {
  if (state.kind === "workflow") {
    const stepId = currentStepId(state, event);
    if (!stepId) return state;
    if (name === "RunContent") {
      return {
        ...state,
        steps: mapSteps(state.steps, stepId, (node) => ({
          ...node,
          content: node.content + text(event.content),
        })),
      };
    }
    if (name === "ToolCallStarted" || name === "ToolCallCompleted" || name === "ToolCallError") {
      return {
        ...state,
        steps: mapSteps(state.steps, stepId, (node) => ({
          ...node,
          tools:
            name === "ToolCallStarted"
              ? (() => {
                  const tool = toolFrom(event.tool, event);
                  return tool ? upsertTool(node.tools, tool) : node.tools;
                })()
              : finishTool(node.tools, event.tool, event, name === "ToolCallError"),
        })),
      };
    }
    return state;
  }

  const member = memberOf(state, event);
  switch (name) {
    case "RunStarted":
      return withMember(state, { ...member, status: "running" });
    case "RunContent":
      return withMember(state, { ...member, content: member.content + text(event.content) });
    case "RunCompleted":
      return withMember(state, {
        ...member,
        status: "completed",
        content: member.content || text(event.content),
      });
    case "RunError":
      return withMember(state, { ...member, status: "error" });
    case "RunPaused":
      return withMember(state, {
        ...member,
        status: "paused",
        tools: pauseTools(member.tools, event.tools ?? []),
      });
    case "ToolCallStarted": {
      const tool = toolFrom(event.tool, event);
      return tool ? withMember(state, { ...member, tools: upsertTool(member.tools, tool) }) : state;
    }
    case "ToolCallCompleted":
    case "ToolCallError":
      return withMember(state, {
        ...member,
        tools: finishTool(member.tools, event.tool, event, name === "ToolCallError"),
      });
    default:
      return state;
  }
}

// ---------------------------------------------------------------- the reducer

const STEP_EVENTS: Record<string, [StepKind, "open" | "close"]> = {
  StepStarted: ["step", "open"],
  StepCompleted: ["step", "close"],
  LoopExecutionStarted: ["loop", "open"],
  LoopExecutionCompleted: ["loop", "close"],
  RouterExecutionStarted: ["router", "open"],
  RouterExecutionCompleted: ["router", "close"],
  ParallelExecutionStarted: ["parallel", "open"],
  ParallelExecutionCompleted: ["parallel", "close"],
  ConditionExecutionStarted: ["condition", "open"],
  ConditionExecutionCompleted: ["condition", "close"],
  StepsExecutionStarted: ["steps", "open"],
  StepsExecutionCompleted: ["steps", "close"],
};

const STEP_PAUSES = new Set([
  "StepPaused",
  "RouterPaused",
  "ConditionPaused",
  "StepExecutorPaused",
  "StepOutputReview",
  "WorkflowPaused",
]);

const IGNORED = new Set([
  "RunContentCompleted",
  "RunIntermediateContent",
  "ModelRequestStarted",
  "ModelRequestCompleted",
  "PreHookStarted",
  "PreHookCompleted",
  "PostHookStarted",
  "PostHookCompleted",
  "MemoryUpdateStarted",
  "MemoryUpdateCompleted",
  "SessionSummaryStarted",
  "SessionSummaryCompleted",
  "ParserModelResponseStarted",
  "ParserModelResponseCompleted",
  "OutputModelResponseStarted",
  "OutputModelResponseCompleted",
  "CompressionStarted",
  "CompressionCompleted",
  "FollowupsStarted",
  "FollowupsCompleted",
  "ReasoningStarted",
  "ReasoningCompleted",
  "WorkflowAgentStarted",
  "WorkflowAgentCompleted",
  "StepProgress",
  "StepOutput",
  "CustomEvent",
  "TeamTaskIterationStarted",
  "TeamTaskIterationCompleted",
]);

function kindOf(event: RunEvent): ComponentKind {
  if (event.event.startsWith("Workflow") || event.event.startsWith("Step")) return "workflow";
  if (event.event.startsWith("Team")) return "team";
  return "agent";
}

function started(state: RunState, event: RunEvent): RunState {
  const kind = state.kind ?? kindOf(event);
  return {
    ...state,
    kind,
    status: "running",
    runId: state.runId ?? event.run_id ?? event.workflow_run_id ?? undefined,
    sessionId: state.sessionId ?? event.session_id ?? undefined,
    componentId: state.componentId ?? event.workflow_id ?? event.team_id ?? event.agent_id ?? undefined,
    componentName:
      state.componentName ??
      (typeof event.workflow_name === "string" ? event.workflow_name : undefined) ??
      event.team_name ??
      event.agent_name ??
      undefined,
    model: event.model ?? state.model,
    startedAt: state.startedAt ?? seconds(event),
    pause: undefined,
  };
}

function completed(state: RunState, event: RunEvent): RunState {
  return {
    ...state,
    status: "completed",
    content: state.content || text(event.content),
    structured: isStructured(event.content) ? event.content : state.structured,
    metrics: event.metrics ?? state.metrics,
    citations: event.citations ?? state.citations,
    references: event.references ?? state.references,
    sessionState: event.session_state ?? state.sessionState,
    tools: state.tools.map((tool) => (tool.status === "running" ? { ...tool, status: "done" } : tool)),
    endedAt: seconds(event) ?? state.endedAt,
    pause: undefined,
  };
}

/** Is this event about the root run (as opposed to a team member or an agent inside a workflow step)? */
function isRoot(state: RunState, event: RunEvent, name: string): boolean {
  if (!state.runId || !event.run_id) return true;
  if (event.run_id === state.runId) return true;
  if (state.kind === "workflow")
    return name.startsWith("Workflow") || name.startsWith("Step") || name in STEP_EVENTS;
  return (event.nested_depth ?? 0) === 0 && !event.parent_run_id;
}

export function reduceRun(state: RunState, event: RunEvent): RunState {
  if (META_EVENTS.has(event.event)) return state;
  const index = typeof event.event_index === "number" ? event.event_index : undefined;
  if (index !== undefined && index <= state.lastEventIndex) return state;
  const counted: RunState = {
    ...state,
    lastEventIndex: index ?? state.lastEventIndex,
    eventCount: state.eventCount + 1,
  };
  return apply(counted, event);
}

function apply(state: RunState, event: RunEvent): RunState {
  const name = baseEventName(event.event);
  const isTeamEvent = event.event.startsWith("Team") && !event.event.startsWith("TeamTask");
  if (state.kind === undefined && isTeamEvent) state = { ...state, kind: "team" };

  if (name === "RunStarted" || name === "WorkflowStarted") {
    if (state.runId && event.run_id && event.run_id !== state.runId && name === "RunStarted") {
      return reduceNested(state, event, name);
    }
    return started(state, event);
  }
  if (!isRoot(state, event, name)) return reduceNested(state, event, name);

  const step = STEP_EVENTS[name];
  if (step) {
    const [kind, action] = step;
    return action === "open" ? openStep(state, event, kind) : closeStep(state, event, kind, "completed");
  }

  switch (name) {
    case "RunContent":
      return {
        ...state,
        status: state.status === "pending" ? "running" : state.status,
        content: state.content + (typeof event.content === "string" ? event.content : ""),
        structured: isStructured(event.content) ? event.content : state.structured,
        reasoning: state.reasoning + (event.reasoning_content ?? ""),
        citations: event.citations ?? state.citations,
        references: event.references ?? state.references,
      };
    case "ReasoningContentDelta":
    case "ReasoningStep":
      return { ...state, reasoning: state.reasoning + text(event.reasoning_content ?? event.content) };
    case "RunCompleted":
    case "WorkflowCompleted":
      return completed(state, event);
    case "RunPaused": {
      const kind = state.kind === "team" || isTeamEvent ? "requirements" : "tools";
      const pause: Pause =
        kind === "requirements"
          ? { kind, requirements: event.requirements ?? [] }
          : { kind, tools: event.tools ?? [] };
      return { ...state, status: "paused", pause, tools: pauseTools(state.tools, event.tools ?? []) };
    }
    case "RunContinued":
    case "StepContinued":
    case "StepExecutorContinued":
    case "WorkflowContinued":
      return { ...state, status: "running", pause: undefined, tools: resumeTools(state.tools) };
    case "RunError":
    case "WorkflowError":
      return {
        ...state,
        status: "error",
        error: { message: text(event.content) || "The run failed.", type: event.error_type ?? undefined },
        endedAt: seconds(event) ?? state.endedAt,
      };
    case "StepError":
      return closeStep(state, event, "step", "error");
    case "RunCancelled":
    case "WorkflowCancelled":
      return {
        ...state,
        status: "cancelled",
        cancelReason: event.reason ?? (text(event.content) || undefined),
        endedAt: seconds(event) ?? state.endedAt,
      };
    case "ToolCallStarted": {
      const tool = toolFrom(event.tool, event);
      return tool ? { ...state, tools: upsertTool(state.tools, tool) } : state;
    }
    case "ToolCallCompleted":
    case "ToolCallError":
      return { ...state, tools: finishTool(state.tools, event.tool, event, name === "ToolCallError") };
    case "LoopIterationStarted":
    case "LoopIterationCompleted": {
      const loop = state.openSteps.at(-1);
      if (!loop) return state;
      const iteration = typeof event.iteration === "number" ? event.iteration : undefined;
      return {
        ...state,
        steps: mapSteps(state.steps, loop, (node) => ({
          ...node,
          iteration:
            iteration ?? (name === "LoopIterationStarted" ? (node.iteration ?? 0) + 1 : node.iteration),
        })),
      };
    }
    case "TeamTaskCreated":
    case "TeamTaskUpdated":
    case "TeamTaskStateUpdated":
      return { ...state, kind: "team", tasks: upsertTask(state.tasks, event) };
    default:
      break;
  }

  if (STEP_PAUSES.has(name)) {
    const requirements: StepRequirement[] = event.step_requirements ?? event.requirements ?? [];
    const stepId = event.step_id ?? undefined;
    return {
      ...state,
      kind: "workflow",
      status: "paused",
      pause: { kind: "steps", event: name, stepRequirements: requirements },
      steps: stepId ? mapSteps(state.steps, stepId, (node) => ({ ...node, status: "paused" })) : state.steps,
    };
  }
  if (IGNORED.has(name)) return state;
  return { ...state, unknownEvents: state.unknownEvents + 1 };
}

/** Fold a recorded event list (fixtures, stored `events`) into a state. */
export function reduceAll(events: readonly RunEvent[], from: RunState = initialRunState()): RunState {
  return events.reduce(reduceRun, from);
}
