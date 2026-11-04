// SSE event sequences for the RunStream reducer tests, in the shapes AgentOS 3.1 emits.
// Hand-written from the documented payloads for exact assertions; `recorded/` holds real runs captured with
// `scripts/record_sse_fixtures.py` (re-record them for a new agno minor).
import type { RunEvent } from "../events";

const T = 1_793_534_400;
const AGENT = {
  run_id: "run_9f2c41",
  session_id: "ses_7f3a91c2",
  agent_id: "support-triage",
  agent_name: "Support triage",
};

export const agentCompleted: RunEvent[] = [
  { event: "RunStarted", event_index: 0, created_at: T, ...AGENT, model: "mock-1", model_provider: "mock" },
  {
    event: "ToolCallStarted",
    event_index: 1,
    created_at: T + 1,
    ...AGENT,
    tool: { tool_call_id: "call_1", tool_name: "lookup_order", tool_args: { order_id: "ord_1001" } },
  },
  {
    event: "ToolCallCompleted",
    event_index: 2,
    created_at: T + 1,
    ...AGENT,
    tool: {
      tool_call_id: "call_1",
      tool_name: "lookup_order",
      tool_args: { order_id: "ord_1001" },
      result: "Order ord_1001: shipped",
      metrics: { duration: 0.4 },
    },
  },
  {
    event: "RunContent",
    event_index: 3,
    created_at: T + 2,
    ...AGENT,
    content: "Done. ",
    content_type: "str",
  },
  { event: "ModelRequestCompleted", event_index: 4, created_at: T + 2, ...AGENT },
  {
    event: "RunContent",
    event_index: 5,
    created_at: T + 2,
    ...AGENT,
    content: "Order ord_1001: shipped",
    content_type: "str",
  },
  { event: "RunContentCompleted", event_index: 6, created_at: T + 3, ...AGENT },
  {
    event: "RunCompleted",
    event_index: 7,
    created_at: T + 3,
    ...AGENT,
    content: "Done. Order ord_1001: shipped",
    metrics: { input_tokens: 1800, output_tokens: 306, total_tokens: 2106, duration: 3.1 },
  },
];

export const agentPaused: RunEvent[] = [
  { event: "RunStarted", event_index: 0, created_at: T, ...AGENT, model: "mock-1" },
  {
    event: "RunPaused",
    event_index: 1,
    created_at: T + 1,
    ...AGENT,
    tools: [
      {
        tool_call_id: "call_refund",
        tool_name: "refund_customer",
        tool_args: { customer_id: "cus_8812", amount: 49, reason: "requested in chat" },
        requires_confirmation: true,
      },
    ],
  },
];

/** What /resume replays after the approval decision continued the run in the background. */
export const agentContinued: RunEvent[] = [
  ...agentPaused,
  { event: "RunContinued", event_index: 2, created_at: T + 60, ...AGENT },
  {
    event: "ToolCallStarted",
    event_index: 3,
    created_at: T + 60,
    ...AGENT,
    tool: {
      tool_call_id: "call_refund",
      tool_name: "refund_customer",
      tool_args: { customer_id: "cus_8812", amount: 45 },
    },
  },
  {
    event: "ToolCallCompleted",
    event_index: 4,
    created_at: T + 61,
    ...AGENT,
    tool: {
      tool_call_id: "call_refund",
      tool_name: "refund_customer",
      result: "Refunded 45.00 to cus_8812 (requested in chat).",
    },
  },
  {
    event: "RunContent",
    event_index: 5,
    created_at: T + 61,
    ...AGENT,
    content: "Done. Refunded 45.00 to cus_8812.",
  },
  { event: "RunCompleted", event_index: 6, created_at: T + 62, ...AGENT },
];

export const agentError: RunEvent[] = [
  { event: "RunStarted", event_index: 0, created_at: T, ...AGENT },
  {
    event: "RunError",
    event_index: 1,
    created_at: T + 1,
    ...AGENT,
    content: "provider overloaded",
    error_type: "ModelProviderError",
  },
];

export const agentCancelled: RunEvent[] = [
  { event: "RunStarted", event_index: 0, created_at: T, ...AGENT },
  { event: "RunContent", event_index: 1, created_at: T, ...AGENT, content: "Looking" },
  { event: "RunCancelled", event_index: 2, created_at: T + 1, ...AGENT, reason: "Cancelled by user" },
];

const TEAM = {
  run_id: "run_team1",
  session_id: "ses_team",
  team_id: "research-team",
  team_name: "Research team",
};
const MEMBER = { run_id: "run_member1", session_id: "ses_team", parent_run_id: "run_team1", nested_depth: 1 };

export const teamCoordinate: RunEvent[] = [
  { event: "TeamRunStarted", event_index: 0, created_at: T, ...TEAM, model: "mock-1" },
  {
    event: "TeamToolCallStarted",
    event_index: 1,
    created_at: T,
    ...TEAM,
    tool: {
      tool_call_id: "call_delegate",
      tool_name: "delegate_task_to_member",
      tool_args: { member_id: "kb-researcher" },
    },
  },
  {
    event: "RunStarted",
    event_index: 2,
    created_at: T + 1,
    ...MEMBER,
    agent_id: "kb-researcher",
    agent_name: "KB researcher",
  },
  {
    event: "ToolCallStarted",
    event_index: 3,
    created_at: T + 1,
    ...MEMBER,
    agent_id: "kb-researcher",
    tool: { tool_call_id: "call_kb", tool_name: "search_knowledge", tool_args: { query: "refund policy" } },
  },
  {
    event: "ToolCallCompleted",
    event_index: 4,
    created_at: T + 2,
    ...MEMBER,
    agent_id: "kb-researcher",
    tool: { tool_call_id: "call_kb", tool_name: "search_knowledge", result: "3 articles" },
  },
  {
    event: "RunContent",
    event_index: 5,
    created_at: T + 2,
    ...MEMBER,
    agent_id: "kb-researcher",
    content: "Found 3 articles.",
  },
  { event: "RunCompleted", event_index: 6, created_at: T + 2, ...MEMBER, agent_id: "kb-researcher" },
  {
    event: "TeamToolCallCompleted",
    event_index: 7,
    created_at: T + 3,
    ...TEAM,
    tool: {
      tool_call_id: "call_delegate",
      tool_name: "delegate_task_to_member",
      result: "Found 3 articles.",
    },
  },
  {
    event: "TeamRunContent",
    event_index: 8,
    created_at: T + 3,
    ...TEAM,
    content: "Summary: 3 articles cover refunds.",
  },
  { event: "TeamRunCompleted", event_index: 9, created_at: T + 4, ...TEAM, metrics: { total_tokens: 900 } },
];

export const teamTasks: RunEvent[] = [
  { event: "TeamRunStarted", event_index: 0, created_at: T, ...TEAM, team_id: "onboarding-team" },
  {
    event: "TeamTaskCreated",
    event_index: 1,
    created_at: T,
    ...TEAM,
    task: { task_id: "t1", title: "Collect docs", status: "pending" },
  },
  {
    event: "TeamTaskCreated",
    event_index: 2,
    created_at: T,
    ...TEAM,
    task: { task_id: "t2", title: "Summarise", status: "pending" },
  },
  { event: "TeamTaskIterationStarted", event_index: 3, created_at: T, ...TEAM, iteration: 1 },
  {
    event: "TeamTaskStateUpdated",
    event_index: 4,
    created_at: T + 1,
    ...TEAM,
    task: { task_id: "t1", status: "completed", assignee: "kb-researcher" },
  },
  {
    event: "TeamTaskUpdated",
    event_index: 5,
    created_at: T + 2,
    ...TEAM,
    task: { task_id: "t2", status: "completed" },
  },
  { event: "TeamRunContent", event_index: 6, created_at: T + 2, ...TEAM, content: "All tasks done." },
  { event: "TeamRunCompleted", event_index: 7, created_at: T + 3, ...TEAM },
];

const FLOW = {
  run_id: "run_flow1",
  session_id: "ses_flow",
  workflow_id: "ticket-router",
  workflow_name: "Ticket router",
};
const STEP_AGENT = {
  run_id: "run_step_agent",
  session_id: "ses_flow",
  workflow_run_id: "run_flow1",
  agent_id: "support-triage",
};

export const workflowRouterLoop: RunEvent[] = [
  { event: "WorkflowStarted", event_index: 0, created_at: T, ...FLOW },
  {
    event: "StepStarted",
    event_index: 1,
    created_at: T,
    ...FLOW,
    step_id: "s_triage",
    step_name: "triage",
    step_index: 0,
  },
  { event: "RunStarted", event_index: 2, created_at: T, ...STEP_AGENT, step_id: "s_triage" },
  {
    event: "RunContent",
    event_index: 3,
    created_at: T,
    ...STEP_AGENT,
    step_id: "s_triage",
    content: "Looks like a refund.",
  },
  { event: "RunCompleted", event_index: 4, created_at: T + 1, ...STEP_AGENT, step_id: "s_triage" },
  {
    event: "StepCompleted",
    event_index: 5,
    created_at: T + 1,
    ...FLOW,
    step_id: "s_triage",
    step_name: "triage",
    step_index: 0,
  },
  {
    event: "RouterExecutionStarted",
    event_index: 6,
    created_at: T + 1,
    ...FLOW,
    step_id: "r_route",
    step_name: "route",
    step_index: 1,
  },
  {
    event: "StepStarted",
    event_index: 7,
    created_at: T + 1,
    ...FLOW,
    step_id: "s_billing",
    step_name: "billing",
    step_index: [1, 0],
  },
  {
    event: "StepCompleted",
    event_index: 8,
    created_at: T + 2,
    ...FLOW,
    step_id: "s_billing",
    step_name: "billing",
    content: "Refund drafted.",
  },
  {
    event: "RouterExecutionCompleted",
    event_index: 9,
    created_at: T + 2,
    ...FLOW,
    step_id: "r_route",
    step_name: "route",
    selected_steps: ["billing"],
  },
  {
    event: "LoopExecutionStarted",
    event_index: 10,
    created_at: T + 2,
    ...FLOW,
    step_id: "l_research",
    step_name: "research loop",
    max_iterations: 2,
  },
  {
    event: "LoopIterationStarted",
    event_index: 11,
    created_at: T + 2,
    ...FLOW,
    step_id: "l_research",
    iteration: 1,
  },
  { event: "StepStarted", event_index: 12, created_at: T + 2, ...FLOW, step_id: "s_kb", step_name: "kb" },
  { event: "StepCompleted", event_index: 13, created_at: T + 3, ...FLOW, step_id: "s_kb", step_name: "kb" },
  {
    event: "LoopIterationCompleted",
    event_index: 14,
    created_at: T + 3,
    ...FLOW,
    step_id: "l_research",
    iteration: 1,
  },
  {
    event: "LoopIterationStarted",
    event_index: 15,
    created_at: T + 3,
    ...FLOW,
    step_id: "l_research",
    iteration: 2,
  },
  {
    event: "LoopExecutionCompleted",
    event_index: 16,
    created_at: T + 4,
    ...FLOW,
    step_id: "l_research",
    step_name: "research loop",
  },
  {
    event: "WorkflowCompleted",
    event_index: 17,
    created_at: T + 4,
    ...FLOW,
    content: "Refund drafted and researched.",
  },
];

export const workflowStepPaused: RunEvent[] = [
  { event: "WorkflowStarted", event_index: 0, created_at: T, ...FLOW, workflow_id: "refund-review" },
  {
    event: "StepStarted",
    event_index: 1,
    created_at: T,
    ...FLOW,
    step_id: "s_approve",
    step_name: "approve",
  },
  {
    event: "StepPaused",
    event_index: 2,
    created_at: T + 1,
    ...FLOW,
    step_id: "s_approve",
    step_name: "approve",
    step_requirements: [
      {
        step_id: "s_approve",
        step_name: "approve",
        requires_confirmation: true,
        confirmation_message: "Issue the refund?",
        requires_user_input: true,
        user_input_message: "Confirm the amount",
        user_input_schema: [
          { name: "amount", field_type: "float", required: true },
          { name: "reason", field_type: "str", required: false },
        ],
      },
    ],
  },
];
