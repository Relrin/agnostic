// Layout: ELK places the flow graph left to right, groups as compound nodes around their steps, Router choices in
// the order they're written, and a 200-step workflow without overlaps among siblings.
import type { Config } from "@agnostic/studio";
import { ticketRouter } from "@agnostic/testing";
import { describe, expect, it } from "vitest";

import { buildFlowGraph } from "./graph";
import { END, START, layoutWorkflow, toElk } from "./layout";

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
  it("puts every port where the node draws it", () => {
    const elk = toElk(buildFlowGraph(ticketRouter()));
    const router = elk.children?.find((node) => node.id === "steps[1]");
    const ports = router?.ports ?? [];
    expect(ports.map((port) => port.id)).toEqual([
      "steps[1]#in",
      "steps[1]#choices[0]",
      "steps[1]#choices[1]",
      "steps[1]#choices[2]",
    ]);
    const ys = ports.slice(1).map((port) => port.y ?? 0);
    expect([...ys].sort((a, b) => a - b)).toEqual(ys);
    expect(ports[1]?.x).toBe(router?.width);
  });

  it("places the ticket router left to right", async () => {
    const layout = await layoutWorkflow(ticketRouter());
    const at = (id: string) => layout.nodes.find((node) => node.id === id);
    expect(at(START)?.x).toBeLessThan(at("steps[0]")?.x ?? 0);
    expect(at("steps[0]")?.x).toBeLessThan(at("steps[1]")?.x ?? 0);
    expect(at("steps[1]")?.x).toBeLessThan(at("steps[1].choices[0]")?.x ?? 0);
    expect(at("steps[2]")?.x).toBeLessThan(at(END)?.x ?? 0);
    // Choices top to bottom, in order.
    expect(at("steps[1].choices[0]")?.y).toBeLessThan(at("steps[1].choices[1]")?.y ?? 0);
    expect(at("steps[1].choices[1]")?.y).toBeLessThan(at("steps[1].choices[2]")?.y ?? 0);
    const investigate = at("steps[1].choices[1]");
    expect(investigate?.width).toBeGreaterThan(at("steps[1].choices[1].steps[0]")?.width ?? 0);
    expect(at("steps[1].choices[1].steps[0]")?.parent).toBe("steps[1].choices[1]");
  });

  it("lays out 200 steps", async () => {
    const config = big(200);
    const started = performance.now();
    const layout = await layoutWorkflow(config);
    expect(layout.nodes.filter((node) => node.kind !== "input" && node.kind !== "output")).toHaveLength(200);
    expect(performance.now() - started).toBeLessThan(5_000);
    const top = layout.nodes.filter((node) => node.parent === undefined && node.kind === "component");
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
