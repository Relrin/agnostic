// The flow graph of the ticket router: typed ports per node type, Router choices leaving from their own ports in
// order, Condition true / else, an empty else running straight on, drop zones for empty lanes, the "+" slots, and
// an agent's model and tools on its node.
import { ticketRouter } from "@agnostic/testing";
import { describe, expect, it } from "vitest";

import { END, START, buildFlowGraph, celLines, layoutKey, portTypesOf, rowsOf, toolChip } from "./graph";

describe("the flow graph", () => {
  const graph = buildFlowGraph(ticketRouter(), { inputLabel: "input" });
  const node = (id: string) => graph.nodes.find((item) => item.id === id);
  const edge = (source: string, target: string) =>
    graph.edges.find((item) => item.source === source && item.target === target);

  it("gives every node type its ports", () => {
    expect(node(START)?.ports).toEqual([{ id: "out", side: "out", type: "message", label: "input" }]);
    expect(node("steps[0]")?.ports.map((port) => `${port.side}:${port.id}:${port.type}`)).toEqual([
      "in:in:message",
      "out:out:message",
    ]);
    expect(node("steps[1]")?.ports.map((port) => [port.id, port.label])).toEqual([
      ["in", "Input"],
      ["choices[0]", "Billing"],
      ["choices[1]", "Investigate"],
      ["choices[2]", "Draft & review"],
    ]);
    expect(node("steps[2]")?.ports.map((port) => port.id)).toEqual(["in", "true", "false"]);
    expect(node("steps[1].choices[1]")).toMatchObject({ kind: "group", type: "Parallel" });
    expect(node("steps[1].choices[2].steps[0]")?.parent).toBe("steps[1].choices[2]");
    expect(node(END)?.kind).toBe("output");
  });

  it("connects ports with the slot their + inserts into", () => {
    expect(edge(START, "steps[0]")).toMatchObject({
      sourceHandle: "out",
      targetHandle: "in",
      port: "message",
      slot: { parent: "", lane: "steps", index: 0 },
    });
    expect(edge("steps[1]", "steps[1].choices[2]")).toMatchObject({
      sourceHandle: "choices[2]",
      port: "route",
    });
    expect(edge("steps[1]", "steps[1].choices[2]")?.slot).toBeUndefined();
    // A Parallel's branches aren't chained; a Loop's steps are.
    expect(edge("steps[1].choices[1].steps[0]", "steps[1].choices[1].steps[1]")).toBeUndefined();
    expect(edge("steps[1].choices[2].steps[0]", "steps[1].choices[2].steps[1]")?.slot).toEqual({
      parent: "steps[1].choices[2]",
      lane: "steps",
      index: 1,
    });
    const joins = graph.edges.filter((item) => item.target === "steps[2]");
    expect(joins.map((item) => item.source)).toEqual([
      "steps[1].choices[0]",
      "steps[1].choices[1]",
      "steps[1].choices[2]",
    ]);
    expect(joins.filter((item) => item.slot)).toHaveLength(1);
    expect(edge("steps[2]", "steps[2].steps[0]")?.sourceHandle).toBe("true");
    expect(edge("steps[2]", "steps[2].else_steps[0]")?.sourceHandle).toBe("false");
    expect(graph.edges.filter((item) => item.target === END).map((item) => item.source)).toEqual([
      "steps[2].steps[0]",
      "steps[2].else_steps[0]",
    ]);
    expect(portTypesOf(graph)).toEqual(["message", "route"]);
  });

  it("runs straight on when a Condition has no else, and gives empty lanes a drop zone", () => {
    const built = buildFlowGraph({
      steps: [
        { type: "Condition", name: "C", evaluator: "true", steps: [{ type: "Step", name: "A" }] },
        { type: "Loop", name: "L", steps: [] },
        { type: "Router", name: "R", choices: [] },
      ],
    });
    const find = (source: string, handle: string) =>
      built.edges.find((item) => item.source === source && item.sourceHandle === handle);
    expect(find("steps[0]", "false")?.target).toBe("steps[1]");
    expect(built.nodes.find((item) => item.id === "steps[1]::empty")).toMatchObject({
      kind: "placeholder",
      parent: "steps[1]",
      slot: { parent: "steps[1]", lane: "steps", index: 0 },
    });
    expect(find("steps[2]", "add")?.target).toBe("steps[2]::choices");
    expect(built.nodes.find((item) => item.id === "steps[2]::choices")?.slot).toEqual({
      parent: "steps[2]",
      lane: "choices",
      index: 0,
    });
  });

  it("shows what a step runs, its agent's model and tools, and CEL on a few lines", () => {
    const rows = rowsOf({ type: "Step", name: "Classify", agent_id: "support-triage" }, () => ({
      model: "claude-opus-5-5",
      tools: ["kb_lookup", "zendesk_search"],
    }));
    expect(rows).toContainEqual({ kind: "desc", text: "Agent · support-triage" });
    expect(rows).toContainEqual({ kind: "field", label: "Model", value: "claude-opus-5-5" });
    expect(rows).toContainEqual({
      kind: "chips",
      label: "Tools",
      items: [{ label: "kb_lookup" }, { label: "zendesk_search" }],
    });
    expect(toolChip("team-data-search")).toEqual({ label: "team-data-search", tone: "team" });
    // With the registry known, the model shows its provider's logo and each tool its service's.
    const branded = rowsOf({ type: "Step", name: "Classify", agent_id: "support-triage" }, () => ({
      model: "claude-opus-5-5",
      modelBrand: "anthropic",
      tools: ["org-linear", "kb_lookup"],
      looks: { "org-linear": { kind: "mcp", brand: "linear" }, kb_lookup: { kind: "code" } },
    }));
    expect(branded).toContainEqual({
      kind: "field",
      label: "Model",
      value: "claude-opus-5-5",
      brand: "anthropic",
    });
    expect(branded).toContainEqual({
      kind: "chips",
      label: "Tools",
      items: [
        { label: "org-linear", tone: "org", kind: "mcp", brand: "linear" },
        { label: "kb_lookup", kind: "code" },
      ],
    });
    expect(celLines('input.contains("a || b") || input.contains("c") ? "Billing" : "Other"')).toEqual([
      'input.contains("a || b")',
      '|| input.contains("c")',
      '? "Billing"',
      ': "Other"',
    ]);
    // A name change doesn't move anything; a new row does.
    const renamed = ticketRouter() as { steps: { name: string }[] };
    if (renamed.steps[0]) renamed.steps[0].name = "Triage";
    expect(layoutKey(buildFlowGraph(renamed))).toBe(layoutKey(buildFlowGraph(ticketRouter())));
  });
});
