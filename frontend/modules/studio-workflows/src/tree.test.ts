// The workflow tree: paths, counting, every edit the canvas makes (insert, move, wrap, unwrap, remove, paste) and
// keyboard movement; every edit undoes through the history.
import type { Config } from "@agnostic/studio";
import { ticketRouter } from "@agnostic/testing";
import { describe, expect, it } from "vitest";

import { createBuilderStore, edit, redo, undo } from "./history";
import {
  cloneSubtree,
  flatten,
  insertNode,
  moveNode,
  names,
  neighbour,
  newNode,
  nodeAt,
  nodeName,
  parentOf,
  removeNode,
  stepCount,
  unwrapNode,
  wrapNode,
} from "./tree";

function names_(config: Config): string[] {
  return flatten(config).map((item) => nodeName(item.node));
}

describe("the workflow tree", () => {
  it("addresses nodes by path and counts every step and container", () => {
    const config = ticketRouter();
    expect(stepCount(config)).toBe(12);
    expect(nodeName(nodeAt(config, "steps[1].choices[1].steps[1]"))).toBe("Check status page");
    expect(parentOf("steps[1].choices[2].steps[0]")).toEqual({
      parent: "steps[1].choices[2]",
      lane: "steps",
      index: 0,
    });
    expect(flatten(config).find((item) => item.path === "steps[2].else_steps[0]")?.lane).toBe("else_steps");
  });

  it("inserts with unique names and removes", () => {
    const config = ticketRouter();
    const step = newNode("Step", names(config), { kind: "agent", id: "support-triage" });
    expect(step).toEqual({ type: "Step", name: "support-triage", agent_id: "support-triage" });
    expect(newNode("Router", new Set(["Router"]))).toMatchObject({ name: "Router 2", choices: [] });
    const path = insertNode(config, { parent: "", lane: "steps", index: 1 }, step);
    expect(path).toBe("steps[1]");
    expect(nodeName(nodeAt(config, "steps[2]"))).toBe("Route by category");
    expect(nodeName(removeNode(config, "steps[1]"))).toBe("support-triage");
    expect(stepCount(config)).toBe(12);
  });

  it("moves nodes between lanes and refuses to move a node into itself", () => {
    const config = ticketRouter();
    const moved = moveNode(config, "steps[0]", { parent: "steps[2]", lane: "else_steps", index: 0 });
    expect(moved).toBe("steps[1].else_steps[0]");
    expect(nodeName(nodeAt(config, "steps[0]"))).toBe("Route by category");
    expect(
      moveNode(config, "steps[0]", { parent: "steps[0].choices[1]", lane: "steps", index: 0 }),
    ).toBeUndefined();
    const later = moveNode(config, "steps[0]", { parent: "", lane: "steps", index: 2 });
    expect(later).toBe("steps[1]");
    expect(names_(config)[0]).toBe("Needs a human?");
  });

  it("wraps and unwraps", () => {
    const config = ticketRouter();
    wrapNode(config, "steps[0]", "Loop");
    expect(nodeAt(config, "steps[0]")).toMatchObject({ type: "Loop", name: "Loop", max_iterations: 3 });
    expect(nodeName(nodeAt(config, "steps[0].steps[0]"))).toBe("Classify ticket");
    unwrapNode(config, "steps[0]");
    expect(nodeName(nodeAt(config, "steps[0]"))).toBe("Classify ticket");
    expect(stepCount(config)).toBe(12);
  });

  it("pastes a copy whose names don't clash", () => {
    const config = ticketRouter();
    const copy = cloneSubtree(nodeAt(config, "steps[1].choices[2]") ?? {}, names(config));
    insertNode(config, { parent: "", lane: "steps", index: 3 }, copy);
    expect(names_(config).slice(-3)).toEqual(["Draft & review 2", "Draft reply 2", "Review tone 2"]);
  });

  it("moves through the tree with the arrow keys", () => {
    const config = ticketRouter();
    expect(neighbour(config, undefined, "down")).toBe("steps[0]");
    expect(neighbour(config, "steps[0]", "down")).toBe("steps[1]");
    expect(neighbour(config, "steps[1]", "down")).toBe("steps[1].choices[0]");
    expect(neighbour(config, "steps[1].choices[0]", "right")).toBe("steps[1].choices[1]");
    expect(neighbour(config, "steps[1].choices[1]", "left")).toBe("steps[1].choices[0]");
    expect(neighbour(config, "steps[0]", "up")).toBe("steps[0]");
  });
});

describe("the history", () => {
  it("undoes and redoes every edit", () => {
    let config: Config = ticketRouter();
    const setConfig = (update: (current: Config) => Config) => {
      config = update(config);
    };
    const store = createBuilderStore();
    edit(store, config, setConfig, "Add Step", (draft) =>
      insertNode(draft, { parent: "", lane: "steps", index: 0 }, newNode("Step", names(draft))),
    );
    edit(store, config, setConfig, "Remove", (draft) => removeNode(draft, "steps[2]"));
    expect(names_(config).slice(0, 3)).toEqual(["Step", "Classify ticket", "Needs a human?"]);
    expect(store.getState().past.map((entry) => entry.label)).toEqual(["Add Step", "Remove"]);

    expect(undo(store, setConfig)).toBe("Remove");
    expect(stepCount(config)).toBe(13);
    expect(undo(store, setConfig)).toBe("Add Step");
    expect(config).toEqual(ticketRouter());
    expect(redo(store, setConfig)).toBe("Add Step");
    expect(nodeName(nodeAt(config, "steps[0]"))).toBe("Step");
    expect(store.getState().future).toHaveLength(1);
    expect(undo(store, setConfig)).toBe("Add Step");
    expect(undo(store, setConfig)).toBeUndefined();
  });
});
