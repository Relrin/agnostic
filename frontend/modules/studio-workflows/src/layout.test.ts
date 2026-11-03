// Layout: the graph has a "+" on every connector at the right place, branches labelled and joined, containers as
// compound nodes; ELK places everything, a 200-step workflow included, without overlaps among siblings.
import type { Config } from "@agnostic/studio";
import { ticketRouter } from "@agnostic/testing";
import { describe, expect, it } from "vitest";

import { END, START, buildGraph, layoutWorkflow } from "./layout";

function big(count: number): Config {
  const steps = Array.from({ length: count / 4 }, (_, index) => ({
    type: "Router",
    name: `Route ${String(index)}`,
    selector: '"a"',
    choices: [
      { type: "Step", name: `A ${String(index)}`, agent_id: "a" },
      {
        type: "Parallel",
        name: `P ${String(index)}`,
        steps: [{ type: "Step", name: `B ${String(index)}`, agent_id: "b" }],
      },
    ],
  }));
  return { id: "big", steps };
}

describe("the workflow layout", () => {
  it("builds the graph with insert slots and branch labels", () => {
    const built = buildGraph(ticketRouter());
    const edge = (source: string, target: string) =>
      built.edges.find((item) => item.source === source && item.target === target);
    expect(edge(START, "steps[0]")?.slot).toEqual({ parent: "", lane: "steps", index: 0 });
    expect(edge("steps[0]", "steps[1]")?.slot).toEqual({ parent: "", lane: "steps", index: 1 });
    expect(edge("steps[1]", "steps[1].choices[2]")).toMatchObject({
      label: "Draft & review",
      tone: "choice",
    });
    expect(edge("steps[1].choices[1].steps[0]", "steps[1].choices[1].steps[1]")).toBeUndefined();
    expect(edge("steps[1].choices[2].steps[0]", "steps[1].choices[2].steps[1]")?.slot).toEqual({
      parent: "steps[1].choices[2]",
      lane: "steps",
      index: 1,
    });
    // Every choice joins at the condition; only the last connector carries the "+".
    const joins = built.edges.filter((item) => item.target === "steps[2]");
    expect(joins.map((item) => item.source)).toEqual([
      "steps[1].choices[0]",
      "steps[1].choices[1]",
      "steps[1].choices[2]",
    ]);
    expect(joins.filter((item) => item.slot)).toHaveLength(1);
    expect(edge("steps[2]", "steps[2].else_steps[0]")).toMatchObject({ label: "else", tone: "else" });
    expect(built.edges.filter((item) => item.target === END).map((item) => item.source)).toEqual([
      "steps[2].steps[0]",
      "steps[2].else_steps[0]",
    ]);
    expect(built.kinds.get("steps[1].choices[1]")?.kind).toBe("container");
    expect(built.kinds.get("steps[1].choices[1].steps[0]")?.parent).toBe("steps[1].choices[1]");
  });

  it("gives empty containers and lanes a drop zone", () => {
    const built = buildGraph({
      steps: [
        { type: "Loop", name: "L", steps: [] },
        { type: "Condition", name: "C", steps: [], else_steps: [] },
      ],
    });
    expect(built.kinds.get("steps[0]::empty")).toMatchObject({
      kind: "placeholder",
      slot: { parent: "steps[0]", lane: "steps", index: 0 },
    });
    expect(built.kinds.get("steps[1]::steps")?.slot).toEqual({ parent: "steps[1]", lane: "steps", index: 0 });
  });

  it("places the ticket router top-down", async () => {
    const layout = await layoutWorkflow(ticketRouter());
    const at = (id: string) => layout.nodes.find((node) => node.id === id);
    expect(at(START)?.y).toBeLessThan(at("steps[0]")?.y ?? 0);
    expect(at("steps[0]")?.y).toBeLessThan(at("steps[1]")?.y ?? 0);
    expect(at("steps[1]")?.y).toBeLessThan(at("steps[1].choices[0]")?.y ?? 0);
    expect(at("steps[2]")?.y).toBeLessThan(at(END)?.y ?? 0);
    const investigate = at("steps[1].choices[1]");
    expect(investigate?.width).toBeGreaterThan(at("steps[1].choices[1].steps[0]")?.width ?? 0);
  });

  it("lays out 200 steps", async () => {
    const config = big(200);
    const started = performance.now();
    const layout = await layoutWorkflow(config);
    expect(layout.nodes.filter((node) => node.kind !== "terminal")).toHaveLength(200);
    expect(performance.now() - started).toBeLessThan(5_000);
    const top = layout.nodes.filter((node) => node.parent === undefined && node.kind === "step");
    for (const [index, node] of top.entries()) {
      for (const other of top.slice(index + 1)) {
        const overlap =
          node.x < other.x + other.width &&
          other.x < node.x + node.width &&
          node.y < other.y + other.height &&
          other.y < node.y + node.height;
        expect(overlap).toBe(false);
      }
    }
  });
});
