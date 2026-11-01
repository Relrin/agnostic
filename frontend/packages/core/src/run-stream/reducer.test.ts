import { describe, expect, it } from "vitest";

import {
  agentCancelled,
  agentCompleted,
  agentContinued,
  agentError,
  agentPaused,
  teamCoordinate,
  teamTasks,
  workflowRouterLoop,
  workflowStepPaused,
} from "./__fixtures__/streams";
import { fromStoredRun } from "./history";
import { initialRunState, isSettled, reduceAll, reduceRun } from "./reducer";

describe("agent runs", () => {
  it("streams content and tool calls to completion", () => {
    const state = reduceAll(agentCompleted);
    expect(state).toMatchObject({
      kind: "agent",
      status: "completed",
      runId: "run_9f2c41",
      sessionId: "ses_7f3a91c2",
      componentId: "support-triage",
      model: "mock-1",
      content: "Done. Order ord_1001: shipped",
      lastEventIndex: 7,
      unknownEvents: 0,
    });
    expect(state.tools).toEqual([
      expect.objectContaining({ id: "call_1", name: "lookup_order", status: "done", durationMs: 400 }),
    ]);
    expect(state.metrics?.total_tokens).toBe(2106);
    expect((state.endedAt ?? 0) - (state.startedAt ?? 0)).toBe(3000);
    expect(isSettled(state)).toBe(true);
  });

  it("pauses on a tool that needs approval, then continues", () => {
    const paused = reduceAll(agentPaused);
    expect(paused.status).toBe("paused");
    expect(paused.pause).toEqual({
      kind: "tools",
      tools: [expect.objectContaining({ tool_name: "refund_customer" })],
    });
    expect(paused.tools[0]).toMatchObject({
      name: "refund_customer",
      status: "paused",
      requiresConfirmation: true,
    });
    expect(isSettled(paused)).toBe(true);

    const done = reduceAll(agentContinued);
    expect(done.status).toBe("completed");
    expect(done.pause).toBeUndefined();
    expect(done.tools).toEqual([
      expect.objectContaining({
        id: "call_refund",
        status: "done",
        args: { customer_id: "cus_8812", amount: 45 },
      }),
    ]);
    expect(done.content).toBe("Done. Refunded 45.00 to cus_8812.");
  });

  it("records errors and cancellations", () => {
    expect(reduceAll(agentError)).toMatchObject({
      status: "error",
      error: { message: "provider overloaded", type: "ModelProviderError" },
    });
    expect(reduceAll(agentCancelled)).toMatchObject({
      status: "cancelled",
      cancelReason: "Cancelled by user",
      content: "Looking",
    });
  });

  it("skips events it already applied (a /resume replay) and tolerates unknown ones", () => {
    const halfway = reduceAll(agentCompleted.slice(0, 4));
    const replayed = reduceAll(agentCompleted, halfway);
    expect(replayed.content).toBe("Done. Order ord_1001: shipped");
    expect(replayed.eventCount).toBe(agentCompleted.length);

    const odd = reduceRun(initialRunState(), { event: "BrandNewEvent", event_index: 0 });
    expect(odd.unknownEvents).toBe(1);
    expect(reduceRun(odd, { event: "catch_up" })).toBe(odd);
  });
});

describe("team runs", () => {
  it("nests member runs under the team (coordinate mode)", () => {
    const state = reduceAll(teamCoordinate);
    expect(state).toMatchObject({
      kind: "team",
      status: "completed",
      content: "Summary: 3 articles cover refunds.",
    });
    expect(state.tools.map((tool) => [tool.name, tool.status])).toEqual([
      ["delegate_task_to_member", "done"],
    ]);
    expect(state.memberOrder).toEqual(["run_member1"]);
    expect(state.members.run_member1).toMatchObject({
      name: "KB researcher",
      status: "completed",
      content: "Found 3 articles.",
      depth: 1,
    });
    expect(state.members.run_member1?.tools).toEqual([
      expect.objectContaining({ name: "search_knowledge", status: "done" }),
    ]);
  });

  it("tracks tasks (tasks mode)", () => {
    const state = reduceAll(teamTasks);
    expect(state.tasks).toEqual([
      { id: "t1", title: "Collect docs", status: "completed", assignee: "kb-researcher" },
      { id: "t2", title: "Summarise", status: "completed", assignee: undefined },
    ]);
    expect(state.status).toBe("completed");
  });
});

describe("workflow runs", () => {
  it("builds the step tree for routers and loops", () => {
    const state = reduceAll(workflowRouterLoop);
    expect(state).toMatchObject({
      kind: "workflow",
      status: "completed",
      content: "Refund drafted and researched.",
      openSteps: [],
    });
    const [triage, router, loop] = state.steps;
    expect(triage).toMatchObject({
      name: "triage",
      kind: "step",
      status: "completed",
      content: "Looks like a refund.",
    });
    expect(router).toMatchObject({ kind: "router", status: "completed", selected: ["billing"] });
    expect(router?.children).toEqual([
      expect.objectContaining({ name: "billing", status: "completed", content: "Refund drafted." }),
    ]);
    expect(loop).toMatchObject({ kind: "loop", iteration: 2, maxIterations: 2, status: "completed" });
    expect(loop?.children.map((child) => child.name)).toEqual(["kb"]);
    expect(state.unknownEvents).toBe(0);
  });

  it("pauses on a HumanReview step with its requirements", () => {
    const state = reduceAll(workflowStepPaused);
    expect(state.status).toBe("paused");
    expect(state.pause).toMatchObject({ kind: "steps", event: "StepPaused" });
    expect(state.pause?.kind === "steps" && state.pause.stepRequirements[0]?.user_input_schema).toHaveLength(
      2,
    );
    expect(state.steps[0]).toMatchObject({ name: "approve", status: "paused" });
  });
});

describe("stored runs", () => {
  it("replays stored events through the reducer", () => {
    const state = fromStoredRun(
      { run_id: "run_9f2c41", status: "COMPLETED", run_input: "where is my order?", events: agentCompleted },
      "ses_7f3a91c2",
    );
    expect(state).toMatchObject({
      status: "completed",
      input: "where is my order?",
      content: "Done. Order ord_1001: shipped",
    });
  });

  it("rebuilds a paused run from its fields when events weren't stored", () => {
    const state = fromStoredRun({
      run_id: "run_9f2c41",
      agent_id: "support-triage",
      status: "PAUSED",
      content: "",
      tools: [
        {
          tool_call_id: "c1",
          tool_name: "refund_customer",
          tool_args: { amount: 49 },
          requires_confirmation: true,
        },
      ],
      created_at: "2026-11-01T10:42:00Z",
    });
    expect(state.status).toBe("paused");
    expect(state.tools[0]).toMatchObject({ name: "refund_customer", status: "paused" });
    expect(state.pause).toEqual({
      kind: "tools",
      tools: [expect.objectContaining({ tool_name: "refund_customer" })],
    });
  });
});
