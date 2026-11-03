// Tree → ELK graph → positions. Steps, Loops and Parallels are compound nodes holding their steps; a Condition's
// true/else lanes and a Router's choices hang below the node as branches that join again at the next step. ELK
// (layered, top-down, hierarchy included) places everything; the layout runs in a worker when the browser has one,
// so a 200-step workflow lays out without stalling the canvas.
import type { Config } from "@agnostic/studio";
import type { ElkExtendedEdge, ElkNode } from "elkjs/lib/elk-api";

import {
  LANES,
  childPath,
  children,
  nodeName,
  nodeType,
  rootSteps,
  type Lane,
  type NodeType,
  type Slot,
  type WorkflowNode,
} from "./tree";

export const START = "start";
export const END = "end";
export const CARD = { width: 248, height: 76 };
export const TERMINAL = { width: 168, height: 32 };
export const PLACEHOLDER = { width: 208, height: 44 };
const HEADER = 44;
const FOOTER: Record<string, number> = { Loop: 34 };

export type LayoutNode = {
  id: string;
  kind: "step" | "container" | "terminal" | "placeholder";
  type?: NodeType;
  parent: string | undefined;
  x: number;
  y: number;
  width: number;
  height: number;
  /** For a placeholder: where a dropped step goes. */
  slot?: Slot | undefined;
};

export type LayoutEdge = {
  id: string;
  source: string;
  target: string;
  /** Where "+" on this connector inserts. */
  slot?: Slot | undefined;
  label?: string | undefined;
  tone?: "choice" | "true" | "else" | undefined;
};

export type Layout = { nodes: LayoutNode[]; edges: LayoutEdge[]; width: number; height: number };

type Built = {
  graph: ElkNode;
  edges: LayoutEdge[];
  kinds: Map<string, Omit<LayoutNode, "x" | "y" | "width" | "height">>;
};

const ROOT_OPTIONS = {
  "elk.algorithm": "layered",
  "elk.direction": "DOWN",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "elk.layered.spacing.nodeNodeBetweenLayers": "44",
  "elk.spacing.nodeNode": "28",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
  "elk.layered.crossingMinimization.semiInteractive": "true",
  "elk.edgeRouting": "ORTHOGONAL",
};

/** The ELK graph of a workflow, with the canvas's own notes on every node and edge. */
export function buildGraph(config: Config | undefined): Built {
  const edges: LayoutEdge[] = [];
  const kinds: Built["kinds"] = new Map();
  const root: ElkNode = { id: "root", layoutOptions: ROOT_OPTIONS, children: [], edges: [] };
  const nodes = new Map<string, ElkNode>([["root", root]]);
  const add = (container: string, node: ElkNode, meta: Omit<LayoutNode, "x" | "y" | "width" | "height">) => {
    nodes.get(container)?.children?.push(node);
    nodes.set(node.id, node);
    kinds.set(node.id, meta);
  };
  const connect = (sources: string[], target: string, extra: Partial<LayoutEdge> = {}) => {
    sources.forEach((source, index) => {
      // One "+" per join: on the last of the connectors meeting at the target.
      const slot = index === sources.length - 1 ? extra.slot : undefined;
      edges.push({ id: `${source}->${target}`, source, target, ...extra, slot });
    });
  };

  /** Lay a lane's nodes out in sequence after `from`; returns what the next step connects from. */
  const sequence = (
    items: WorkflowNode[],
    container: string,
    parent: string,
    lane: Lane,
    from: string[],
    first?: Partial<LayoutEdge>,
  ): string[] => {
    let exits = from;
    items.forEach((item, index) => {
      const path = childPath(parent, lane, index);
      const placed = emit(item, path, container);
      const extra =
        index === 0 ? { ...first, slot: { parent, lane, index } } : { slot: { parent, lane, index } };
      for (const entry of placed.entries) connect(exits, entry, exits.length ? extra : {});
      exits = placed.exits;
    });
    return exits;
  };

  const emit = (
    item: WorkflowNode,
    path: string,
    container: string,
  ): { entries: string[]; exits: string[] } => {
    const type = nodeType(item);
    if (type === "Step") {
      add(container, { id: path, ...CARD }, { id: path, kind: "step", type, parent: parentId(container) });
      return { entries: [path], exits: [path] };
    }
    if (type === "Steps" || type === "Loop" || type === "Parallel") {
      const compound: ElkNode = {
        id: path,
        children: [],
        layoutOptions: {
          "elk.padding": `[top=${String(HEADER)},left=16,bottom=${String(16 + (FOOTER[type] ?? 0))},right=16]`,
          "elk.spacing.nodeNode": "20",
        },
      };
      add(container, compound, { id: path, kind: "container", type, parent: parentId(container) });
      const inner = children(item, "steps");
      if (inner.length === 0) {
        const id = `${path}::empty`;
        add(
          path,
          { id, ...PLACEHOLDER },
          { id, kind: "placeholder", parent: path, slot: { parent: path, lane: "steps", index: 0 } },
        );
      } else if (type === "Parallel") {
        inner.forEach((child, index) => emit(child, childPath(path, "steps", index), path));
      } else {
        sequence(inner, path, path, "steps", []);
      }
      return { entries: [path], exits: [path] };
    }
    // Condition and Router: the node, then its branches in the same container, joining at the next step.
    add(container, { id: path, ...CARD }, { id: path, kind: "step", type, parent: parentId(container) });
    const exits: string[] = [];
    if (type === "Router") {
      const choices = children(item, "choices");
      choices.forEach((choice, index) => {
        const placed = emit(choice, childPath(path, "choices", index), container);
        for (const entry of placed.entries) {
          edges.push({
            id: `${path}->${entry}`,
            source: path,
            target: entry,
            label: nodeName(choice) || `choice ${String(index + 1)}`,
            tone: "choice",
          });
        }
        exits.push(...placed.exits);
      });
      if (choices.length === 0) exits.push(path);
      return { entries: [path], exits };
    }
    for (const lane of LANES[type]) {
      const items = children(item, lane);
      const tone = lane === "else_steps" ? "else" : "true";
      const label = lane === "else_steps" ? "else" : "true";
      if (items.length === 0) {
        if (lane === "steps") {
          const id = `${path}::${lane}`;
          add(
            container,
            { id, ...PLACEHOLDER },
            { id, kind: "placeholder", parent: parentId(container), slot: { parent: path, lane, index: 0 } },
          );
          edges.push({ id: `${path}->${id}`, source: path, target: id, label, tone });
          exits.push(id);
        } else {
          exits.push(path);
        }
        continue;
      }
      exits.push(...sequence(items, container, path, lane, [path], { label, tone }));
    }
    return { entries: [path], exits };
  };

  add("root", { id: START, ...TERMINAL }, { id: START, kind: "terminal", parent: undefined });
  const steps = rootSteps(config);
  const exits = sequence(steps, "root", "", "steps", [START]);
  add("root", { id: END, ...TERMINAL }, { id: END, kind: "terminal", parent: undefined });
  connect(exits, END, { slot: { parent: "", lane: "steps", index: steps.length } });
  root.edges = edges.map((edge): ElkExtendedEdge => ({
    id: edge.id,
    sources: [edge.source],
    targets: [edge.target],
  }));
  return { graph: root, edges, kinds };
}

function parentId(container: string): string | undefined {
  return container === "root" ? undefined : container;
}

/** Positions from ELK's answer: relative to the parent container, as React Flow places child nodes. */
export function positions(laidOut: ElkNode, built: Built): Layout {
  const nodes: LayoutNode[] = [];
  const walk = (node: ElkNode) => {
    for (const child of node.children ?? []) {
      const meta = built.kinds.get(child.id);
      if (meta) {
        nodes.push({
          ...meta,
          x: child.x ?? 0,
          y: child.y ?? 0,
          width: child.width ?? CARD.width,
          height: child.height ?? CARD.height,
        });
      }
      walk(child);
    }
  };
  walk(laidOut);
  return { nodes, edges: built.edges, width: laidOut.width ?? 0, height: laidOut.height ?? 0 };
}

type Elk = { layout: (graph: ElkNode) => Promise<ElkNode> };
let workerElk: Promise<Elk> | undefined;
/** The worker failed once (no module workers, a CSP…): lay out on the main thread from then on. */
let workerBroken = false;
const WORKER_TIMEOUT_MS = 10_000;

/** ELK's own API talking to ELK's worker (layout.worker.ts loads it), so the work leaves the main thread. */
function elkInWorker(): Promise<Elk> | undefined {
  if (typeof Worker === "undefined" || workerBroken) return undefined;
  workerElk ??= import("elkjs/lib/elk-api.js").then(
    ({ default: ELK }) =>
      new ELK({
        workerFactory: () => new Worker(new URL("./layout.worker.ts", import.meta.url), { type: "module" }),
      }),
  );
  return workerElk;
}

async function inWorker(elk: Promise<Elk>, graph: ElkNode): Promise<ElkNode> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error("The layout worker didn't answer."));
    }, WORKER_TIMEOUT_MS);
  });
  try {
    return await Promise.race([(await elk).layout(graph), timeout]);
  } catch (error) {
    workerBroken = true;
    workerElk = undefined;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function inThread(graph: ElkNode): Promise<ElkNode> {
  const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
  return new ELK().layout(graph);
}

/** Lay the workflow out (in a worker when there is one). */
export async function layoutWorkflow(config: Config | undefined): Promise<Layout> {
  const built = buildGraph(config);
  const elk = elkInWorker();
  const laidOut = elk
    ? await inWorker(elk, built.graph).catch(() => inThread(built.graph))
    : await inThread(built.graph);
  return positions(laidOut, built);
}
