// Arranging by hand: removing several steps at once, manual moves that follow their steps through edits (removing a
// step never hands its place to the next one), group frames growing around moved steps, aligning, distributing,
// the grid and the selection rectangle.
import type { Config } from "@agnostic/studio";
import { describe, expect, it } from "vitest";

import { align, caught, distribute, fitGroups, rectBetween, toGrid, type Box } from "./arrange";
import { createBuilderStore, edit, undo } from "./history";
import type { FlowNode } from "./nodes";
import { followOffsets } from "./notes";
import { flatten, followPaths, nodeName, removeNode, removeNodes } from "./tree";

/** Parallel → Loop → two steps, then a step after the Parallel. */
function nested(): Config {
  return {
    id: "nested",
    steps: [
      {
        type: "Parallel",
        name: "Parallel",
        steps: [
          {
            type: "Loop",
            name: "Loop",
            max_iterations: 3,
            steps: [
              { type: "Step", name: "First", agent_id: "a" },
              { type: "Step", name: "Second", agent_id: "b" },
            ],
          },
        ],
      },
      { type: "Step", name: "After", agent_id: "c" },
    ],
  };
}

const names = (config: Config) => flatten(config).map((item) => nodeName(item.node));

describe("removing several steps", () => {
  it("removes siblings in any order without renumbering the ones still to go", () => {
    const store = createBuilderStore();
    let config = nested();
    edit(
      store,
      config,
      (update) => {
        config = update(config);
      },
      "Remove",
      (draft) => removeNodes(draft, ["steps[0].steps[0].steps[0]", "steps[0].steps[0].steps[1]"]),
    );
    expect(names(config)).toEqual(["Parallel", "Loop", "After"]);
    undo(store, (update) => {
      config = update(config);
    });
    expect(names(config)).toEqual(["Parallel", "Loop", "First", "Second", "After"]);
  });

  it("takes a step inside a removed container with the container", () => {
    const config = nested();
    const removed = removeNodes(config, ["steps[0].steps[0].steps[1]", "steps[0]", "steps[1]"]);
    expect(removed.map(nodeName)).toEqual(["After", "Parallel"]);
    expect(names(config)).toEqual([]);
  });
});

describe("manual moves follow their steps", () => {
  const remove = (config: Config, path: string): Config => {
    const store = createBuilderStore();
    let next = config;
    edit(
      store,
      config,
      (update) => {
        next = update(config);
      },
      "Remove",
      (draft) => removeNode(draft, path),
    );
    return next;
  };

  it("drops the removed step's move and shifts the next step's move with it", () => {
    const before = nested();
    const offsets = {
      start: { x: 5, y: 5 },
      "steps[0].steps[0].steps[0]": { x: 100, y: 0 },
      "steps[0].steps[0].steps[1]": { x: 0, y: 200 },
      "steps[0]": { x: 7, y: 7 },
    };
    const after = remove(before, "steps[0].steps[0].steps[0]");
    expect(followOffsets(offsets, followPaths(before, after))).toEqual({
      start: { x: 5, y: 5 },
      // "Second" is now first in the Loop, and keeps its own place.
      "steps[0].steps[0].steps[0]": { x: 0, y: 200 },
      // The Parallel changed (one step fewer inside) but it's still there.
      "steps[0]": { x: 7, y: 7 },
    });
  });

  it("moves a step's place up when a step before it goes", () => {
    const before = nested();
    const after = remove(before, "steps[0]");
    expect(followOffsets({ "steps[1]": { x: 1, y: 2 } }, followPaths(before, after))).toEqual({
      "steps[0]": { x: 1, y: 2 },
    });
  });

  it("keeps every move when the whole config is replaced (an edit in the code)", () => {
    const offsets = { "steps[1]": { x: 1, y: 2 } };
    expect(followOffsets(offsets, followPaths(nested(), nested()))).toBe(offsets);
  });
});

describe("group frames", () => {
  it("grow around a step moved past their edge, the frame around them too", () => {
    const frame = (id: string, parentId: string | undefined, width: number, height: number): FlowNode =>
      ({
        id,
        type: "frame",
        position: { x: 0, y: 0 },
        width,
        height,
        ...(parentId ? { parentId } : {}),
        data: { footer: undefined },
      }) as unknown as FlowNode;
    const step = {
      id: "steps[0].steps[0].steps[0]",
      type: "component",
      parentId: "steps[0].steps[0]",
      position: { x: 400, y: 300 },
      width: 200,
      height: 100,
      data: {},
    } as unknown as FlowNode;
    const fitted = fitGroups([
      frame("steps[0]", undefined, 300, 200),
      frame("steps[0].steps[0]", "steps[0]", 250, 150),
      step,
    ]);
    expect(fitted[1]).toMatchObject({ width: 624, height: 422 });
    expect(fitted[0]).toMatchObject({ width: 648, height: 444 });
  });
});

describe("arranging the selection", () => {
  const boxes: Box[] = [
    { id: "a", x: 0, y: 0, width: 100, height: 50 },
    { id: "b", x: 300, y: 40, width: 50, height: 100 },
    { id: "c", x: 120, y: 400, width: 100, height: 50 },
  ];

  it("aligns on the edges and centres of what's selected", () => {
    expect(Object.fromEntries(align(boxes, "left"))).toEqual({ b: { x: -300, y: 0 }, c: { x: -120, y: 0 } });
    expect(Object.fromEntries(align(boxes, "bottom"))).toEqual({
      a: { x: 0, y: 400 },
      b: { x: 0, y: 310 },
    });
    expect(align(boxes, "center").get("a")).toEqual({ x: 125, y: 0 });
  });

  it("spreads three or more evenly and leaves the outer ones in place", () => {
    const moves = distribute(boxes, "horizontal");
    expect(moves.has("a")).toBe(false);
    expect(moves.has("b")).toBe(false);
    // 350 wide in all, 250 of boxes: 50 between each.
    expect(moves.get("c")).toEqual({ x: 30, y: 0 });
  });

  it("snaps corners to the grid", () => {
    expect(Object.fromEntries(toGrid([{ id: "a", x: 12, y: 34, width: 1, height: 1 }], 22))).toEqual({
      a: { x: 10, y: 10 },
    });
  });

  it("catches what the rectangle touches, and groups only when it holds them", () => {
    const rect = rectBetween({ x: 90, y: 60 }, { x: -10, y: -10 });
    expect(caught({ id: "a", x: 80, y: 40, width: 100, height: 100 }, rect, false)).toBe(true);
    expect(caught({ id: "a", x: 80, y: 40, width: 100, height: 100 }, rect, true)).toBe(false);
    expect(caught({ id: "a", x: 0, y: 0, width: 50, height: 50 }, rect, true)).toBe(true);
  });
});
