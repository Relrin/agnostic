// The workflow as a tree: nodes addressed by config paths (`steps[1].choices[2].steps[0]`), and the edits the canvas
// makes to it. Every edit is a tree operation (insert, move, wrap, unwrap, remove, update), so whatever the canvas
// does, the result is still a workflow agno can load. Functions here never mutate their input: the history wraps
// them in immer drafts.
import { isRecord, type Config } from "@agnostic/studio";

export type NodeType = "Step" | "Steps" | "Parallel" | "Condition" | "Loop" | "Router";
export type Lane = "steps" | "else_steps" | "choices";
export type WorkflowNode = Record<string, unknown>;

export const NODE_TYPES: readonly NodeType[] = ["Step", "Steps", "Parallel", "Condition", "Loop", "Router"];
export const CONTAINERS: readonly NodeType[] = ["Steps", "Parallel", "Condition", "Loop", "Router"];

/** Where children live, per node type: a Router's choices are its branches, a Condition has an else branch. */
export const LANES: Record<NodeType, readonly Lane[]> = {
  Step: [],
  Steps: ["steps"],
  Parallel: ["steps"],
  Loop: ["steps"],
  Condition: ["steps", "else_steps"],
  Router: ["choices"],
};

/** A place between nodes: `index` within `lane` of the node at `parent` (`""` is the workflow itself). */
export type Slot = { parent: string; lane: Lane; index: number };

export type Executor = { kind: "agent" | "team" | "workflow" | "function"; id: string };

export const EXECUTOR_FIELDS: Record<Executor["kind"], string> = {
  agent: "agent_id",
  team: "team_id",
  workflow: "workflow_id",
  function: "executor_ref",
};

export function nodeType(node: unknown): NodeType {
  const value = isRecord(node) ? node.type : undefined;
  return typeof value === "string" && (NODE_TYPES as readonly string[]).includes(value)
    ? (value as NodeType)
    : "Step";
}

export function nodeName(node: unknown): string {
  const value = isRecord(node) ? node.name : undefined;
  return typeof value === "string" ? value : "";
}

export function children(node: unknown, lane: Lane): WorkflowNode[] {
  const value = isRecord(node) ? node[lane] : undefined;
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function rootSteps(config: Config | undefined): WorkflowNode[] {
  return children(config, "steps");
}

type Segment = { lane: Lane; index: number };

const SEGMENT = /(steps|else_steps|choices)\[(\d+)\]/g;

export function parsePath(path: string): Segment[] {
  return [...path.matchAll(SEGMENT)].map((match) => ({ lane: match[1] as Lane, index: Number(match[2]) }));
}

export function childPath(parent: string, lane: Lane, index: number): string {
  return `${parent ? `${parent}.` : ""}${lane}[${String(index)}]`;
}

export function parentOf(path: string): { parent: string; lane: Lane; index: number } | undefined {
  const segments = parsePath(path);
  const last = segments.at(-1);
  if (!last) return undefined;
  const parent = segments
    .slice(0, -1)
    .reduce((prefix, segment) => childPath(prefix, segment.lane, segment.index), "");
  return { parent, lane: last.lane, index: last.index };
}

export function nodeAt(config: Config | undefined, path: string): WorkflowNode | undefined {
  let current: unknown = config;
  for (const segment of parsePath(path)) {
    current = children(current, segment.lane)[segment.index];
    if (current === undefined) return undefined;
  }
  return path ? (current as WorkflowNode) : undefined;
}

/** A container (or the workflow, for `""`) to change; returns the same object for the root. */
function holder(config: Config, parent: string): Record<string, unknown> | undefined {
  return parent ? nodeAt(config, parent) : config;
}

function laneOf(owner: Record<string, unknown>, lane: Lane): WorkflowNode[] {
  if (!Array.isArray(owner[lane])) owner[lane] = [];
  return owner[lane] as WorkflowNode[];
}

// ---------------------------------------------------------------- reading the tree

export type FlatNode = {
  path: string;
  node: WorkflowNode;
  type: NodeType;
  depth: number;
  parent: string;
  lane: Lane;
  index: number;
};

/** Every node, depth first in reading order. */
export function flatten(config: Config | undefined): FlatNode[] {
  const found: FlatNode[] = [];
  const walk = (nodes: WorkflowNode[], parent: string, lane: Lane, depth: number) => {
    nodes.forEach((node, index) => {
      const path = childPath(parent, lane, index);
      const type = nodeType(node);
      found.push({ path, node, type, depth, parent, lane, index });
      for (const inner of LANES[type]) walk(children(node, inner), path, inner, depth + 1);
    });
  };
  walk(rootSteps(config), "", "steps", 1);
  return found;
}

/** Every Step and every container, as the builder counts them. */
export function stepCount(config: Config | undefined): number {
  return flatten(config).length;
}

export function executorOf(node: unknown): Executor | undefined {
  if (!isRecord(node) || nodeType(node) !== "Step") return undefined;
  for (const [kind, field] of Object.entries(EXECUTOR_FIELDS) as [Executor["kind"], string][]) {
    const value = node[field];
    if (typeof value === "string" && value) return { kind, id: value };
  }
  return undefined;
}

export function names(config: Config | undefined): Set<string> {
  return new Set(
    flatten(config)
      .map((item) => nodeName(item.node))
      .filter(Boolean),
  );
}

/** `base`, or `base 2`, `base 3`… so names stay unique (runs, stats and pins key on them). */
export function uniqueName(taken: Set<string>, base: string): string {
  if (!taken.has(base)) return base;
  let counter = 2;
  while (taken.has(`${base} ${String(counter)}`)) counter += 1;
  return `${base} ${String(counter)}`;
}

// ---------------------------------------------------------------- making nodes

const DEFAULT_NAMES: Record<NodeType, string> = {
  Step: "Step",
  Steps: "Steps",
  Parallel: "Parallel",
  Condition: "Condition",
  Loop: "Loop",
  Router: "Router",
};

/** A node as the palette adds it; a Step with an executor is named after it. */
export function newNode(type: NodeType, taken: Set<string>, executor?: Executor): WorkflowNode {
  const base = executor ? executor.id : DEFAULT_NAMES[type];
  const name = uniqueName(taken, base);
  switch (type) {
    case "Step":
      return executor ? { type, name, [EXECUTOR_FIELDS[executor.kind]]: executor.id } : { type, name };
    case "Steps":
    case "Parallel":
      return { type, name, steps: [] };
    case "Loop":
      return { type, name, steps: [], max_iterations: 3 };
    case "Condition":
      return { type, name, evaluator: "", evaluator_type: "cel", steps: [], else_steps: [] };
    case "Router":
      return { type, name, selector: "", selector_type: "cel", choices: [] };
  }
}

/** A copy of a subtree whose names don't clash with `taken` (pasting next to the original). */
export function cloneSubtree(node: WorkflowNode, taken: Set<string>): WorkflowNode {
  const copy = structuredClone(node);
  const rename = (item: WorkflowNode) => {
    const name = nodeName(item);
    if (name) {
      const fresh = uniqueName(taken, name);
      taken.add(fresh);
      item.name = fresh;
    }
    delete item.step_id;
    for (const lane of LANES[nodeType(item)]) children(item, lane).forEach(rename);
  };
  rename(copy);
  return copy;
}

// ---------------------------------------------------------------- edits (on a draft: they mutate `config`)

export function insertNode(config: Config, slot: Slot, node: WorkflowNode): string | undefined {
  const owner = holder(config, slot.parent);
  if (!owner) return undefined;
  const lane = laneOf(owner, slot.lane);
  const index = Math.min(Math.max(slot.index, 0), lane.length);
  lane.splice(index, 0, node);
  return childPath(slot.parent, slot.lane, index);
}

export function removeNode(config: Config, path: string): WorkflowNode | undefined {
  const place = parentOf(path);
  if (!place) return undefined;
  const owner = holder(config, place.parent);
  if (!owner) return undefined;
  const [removed] = laneOf(owner, place.lane).splice(place.index, 1);
  return removed;
}

/**
 * Remove several nodes in one edit. A node inside another removed node goes with it; the rest are taken out from
 * the last in reading order to the first, so removing one never renumbers a path still to remove.
 */
export function removeNodes(config: Config, paths: readonly string[]): WorkflowNode[] {
  const wanted = new Set(
    paths.filter((path) => !paths.some((other) => other !== path && contains(other, path))),
  );
  const order = flatten(config)
    .map((item) => item.path)
    .filter((path) => wanted.has(path))
    .reverse();
  return order.flatMap((path) => {
    const removed = removeNode(config, path);
    return removed ? [removed] : [];
  });
}

/**
 * Where each node path of `before` is in `after`. Edits keep the nodes they don't touch as the same objects, so a
 * node is followed by identity (a removed sibling shifts its path); a node the edit changed keeps its path unless
 * another node moved into it. A path whose node is gone answers `undefined`.
 */
export function followPaths(
  before: Config | undefined,
  after: Config | undefined,
): (path: string) => string | undefined {
  const old = flatten(before);
  const next = flatten(after);
  const known = new Set(old.map((item) => item.node));
  const pathOf = new Map(next.map((item) => [item.node, item.path]));
  const nodeAtPath = new Map(next.map((item) => [item.path, item.node]));
  const oldAt = new Map(old.map((item) => [item.path, item.node]));
  return (path) => {
    const node = oldAt.get(path);
    if (!node) return nodeAtPath.has(path) ? path : undefined;
    const moved = pathOf.get(node);
    if (moved !== undefined) return moved;
    const there = nodeAtPath.get(path);
    return there && !known.has(there) ? path : undefined;
  };
}

export function updateNode(config: Config, path: string, update: (node: WorkflowNode) => void): void {
  const node = nodeAt(config, path);
  if (node) update(node);
}

/** Whether `ancestor` is `path` or contains it. */
export function contains(ancestor: string, path: string): boolean {
  return path === ancestor || path.startsWith(`${ancestor}.`);
}

/** Move a node into a slot elsewhere; returns its new path. A node can't move into itself. */
export function moveNode(config: Config, path: string, slot: Slot): string | undefined {
  if (slot.parent && contains(path, slot.parent)) return undefined;
  const place = parentOf(path);
  const node = nodeAt(config, path);
  const source = place ? holder(config, place.parent) : undefined;
  const target = holder(config, slot.parent);
  if (!place || !node || !source || !target) return undefined;
  // Work on the lane arrays themselves: taking the node out renumbers paths, not the arrays.
  const from = laneOf(source, place.lane);
  const into = laneOf(target, slot.lane);
  const index = from === into && place.index < slot.index ? slot.index - 1 : slot.index;
  from.splice(place.index, 1);
  into.splice(Math.min(Math.max(index, 0), into.length), 0, node);
  return flatten(config).find((item) => item.node === node)?.path;
}

/** Put a node inside a new container in its place (a Step into a Loop, two steps into Parallel…). */
export function wrapNode(config: Config, path: string, type: Exclude<NodeType, "Step">): string | undefined {
  const node = nodeAt(config, path);
  const place = parentOf(path);
  if (!node || !place) return undefined;
  const container = newNode(type, names(config));
  laneOf(container, LANES[type][0] ?? "steps").push(node);
  const owner = holder(config, place.parent);
  if (!owner) return undefined;
  laneOf(owner, place.lane)[place.index] = container;
  return path;
}

/** Replace a container with its (first lane's) children, in its place. */
export function unwrapNode(config: Config, path: string): string | undefined {
  const node = nodeAt(config, path);
  const place = parentOf(path);
  if (!node || !place) return undefined;
  const type = nodeType(node);
  const lane = LANES[type][0];
  if (!lane) return undefined;
  const inner = children(node, lane);
  const owner = holder(config, place.parent);
  if (!owner) return undefined;
  laneOf(owner, place.lane).splice(place.index, 1, ...inner);
  return inner.length ? path : undefined;
}

// ---------------------------------------------------------------- moving through the tree

/** The node an arrow key goes to: up/down through reading order, left/right between sibling lanes. */
export function neighbour(
  config: Config | undefined,
  path: string | undefined,
  direction: "up" | "down" | "left" | "right",
): string | undefined {
  const order = flatten(config);
  if (order.length === 0) return undefined;
  const at = order.findIndex((item) => item.path === path);
  if (at < 0) return order[0]?.path;
  const current = order[at];
  if (!current) return undefined;
  if (direction === "down") return order[at + 1]?.path ?? current.path;
  if (direction === "up") return order[at - 1]?.path ?? current.path;
  const siblings = order.filter((item) => item.parent === current.parent && item.depth === current.depth);
  const position = siblings.findIndex((item) => item.path === current.path);
  const next = siblings[direction === "left" ? position - 1 : position + 1];
  return next?.path ?? current.path;
}
