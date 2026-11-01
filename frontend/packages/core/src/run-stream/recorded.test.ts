// Runs recorded from the reference runtime (`scripts/record_sse_fixtures.py`, agno 3.1.12) folded through the reducer:
// every event is understood, indexes are dense, and each run ends where the runtime left it.
import { describe, expect, it } from "vitest";

import agentCompleted from "./__fixtures__/recorded/agent-completed.json";
import agentPausedContinued from "./__fixtures__/recorded/agent-paused-continued.json";
import teamCoordinate from "./__fixtures__/recorded/team-coordinate.json";
import teamTasks from "./__fixtures__/recorded/team-tasks.json";
import workflowLoopHitl from "./__fixtures__/recorded/workflow-loop-hitl.json";
import workflowRouter from "./__fixtures__/recorded/workflow-router.json";
import type { RunEvent } from "./events";
import { reduceAll } from "./reducer";

const RECORDED: Record<string, RunEvent[]> = {
  "agent-completed": agentCompleted,
  "agent-paused-continued": agentPausedContinued,
  "team-coordinate": teamCoordinate,
  "team-tasks": teamTasks,
  "workflow-loop-hitl": workflowLoopHitl,
  "workflow-router": workflowRouter,
};

describe.each(Object.entries(RECORDED))("recorded %s", (_name, events) => {
  it("understands every event and keeps the last index", () => {
    const state = reduceAll(events);
    expect(state.unknownEvents).toBe(0);
    expect(state.eventCount).toBe(events.length);
    expect(state.lastEventIndex).toBe(events.at(-1)?.event_index);
    expect(state.runId).toBe(events[0]?.run_id);
  });
});

describe("recorded runs end where the runtime left them", () => {
  it("agent: a tool call, then the answer", () => {
    const state = reduceAll(RECORDED["agent-completed"] ?? []);
    expect(state.status).toBe("completed");
    expect(state.tools.map((tool) => [tool.name, tool.status])).toEqual([["lookup_order", "done"]]);
    expect(state.content).not.toBe("");
  });

  it("agent: paused for refund_customer, approved, completed", () => {
    const events = RECORDED["agent-paused-continued"] ?? [];
    const paused = reduceAll(events.slice(0, events.findIndex((event) => event.event === "RunPaused") + 1));
    expect(paused.status).toBe("paused");
    expect(paused.pause?.kind).toBe("tools");
    expect(paused.tools[0]).toMatchObject({ name: "refund_customer", status: "paused" });
    const done = reduceAll(events);
    expect(done.status).toBe("completed");
    expect(done.tools[0]).toMatchObject({ name: "refund_customer", status: "done" });
  });

  it("team: coordinate and tasks modes", () => {
    expect(reduceAll(RECORDED["team-coordinate"] ?? [])).toMatchObject({ kind: "team", status: "completed" });
    const tasks = reduceAll(RECORDED["team-tasks"] ?? []);
    expect(tasks.status).toBe("completed");
    expect(tasks.tasks.length).toBeGreaterThan(0);
    expect(tasks.memberOrder.length).toBeGreaterThan(0);
  });

  it("workflow: a step executor pause, and a loop that ends on a HumanReview step", () => {
    const router = reduceAll(RECORDED["workflow-router"] ?? []);
    expect(router).toMatchObject({ kind: "workflow", status: "paused" });
    expect(router.pause?.kind).toBe("steps");

    const loop = reduceAll(RECORDED["workflow-loop-hitl"] ?? []);
    expect(loop.status).toBe("paused");
    expect(loop.steps.some((step) => step.kind === "loop")).toBe(true);
    expect(loop.pause?.kind === "steps" && loop.pause.event).toBe("StepPaused");
  });
});
