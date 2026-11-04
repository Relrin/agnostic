// Flow graph → ELK → positions. The flow reads left to right: the workflow's input, its steps, and its output.
// Groups (Steps, Loop, Parallel) are compound nodes holding their steps; Router choices and Condition branches leave
// the node from their own ports, in the order they're written, and join again at the next node. Every port sits
// where the node draws it (the rows have fixed heights), so ELK orders layers and branches the way the canvas
// shows them. The layout runs in a worker when the browser has one, so a 200-step workflow lays out without
// stalling the canvas.
import type { Config } from "@agnostic/studio";
import { FLOW_ROW_HEIGHTS, GROUP_FOOTER, GROUP_HEADER, IO_NODE, flowRowHeight } from "@agnostic/ui";
import type { ElkExtendedEdge, ElkNode, ElkPort } from "elkjs/lib/elk-api";

import { END, START, buildFlowGraph, type FlowGraph, type GraphNode } from "./graph";
import type { NodeType } from "./tree";

export { END, START };

export type LayoutNode = {
  id: string;
  kind: GraphNode["kind"];
  type?: NodeType | undefined;
  parent: string | undefined;
  /** Relative to the parent group, as React Flow places child nodes. */
  x: number;
  y: number;
  width: number;
  height: number;
};

export type Layout = { nodes: LayoutNode[]; width: number; height: number };

const ROOT_OPTIONS = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "elk.layered.spacing.nodeNodeBetweenLayers": "84",
  "elk.layered.spacing.edgeNodeBetweenLayers": "24",
  "elk.spacing.nodeNode": "36",
  "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
  // Branches stay in the order they're written (Router choices top to bottom).
  "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
  "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
  "elk.edgeRouting": "SPLINES",
};

const portId = (node: string, handle: string) => `${node}#${handle}`;

/** Where each port is on its node, as the node draws it. */
function portsOf(node: GraphNode): ElkPort[] {
  const at = (id: string, side: "in" | "out", y: number): ElkPort => ({
    id: portId(node.id, id),
    width: 1,
    height: 1,
    x: side === "in" ? 0 : node.width,
    y,
    layoutOptions: { "elk.port.side": side === "in" ? "WEST" : "EAST" },
  });
  if (node.kind === "group") return node.ports.map((port) => at(port.id, port.side, GROUP_HEADER / 2));
  if (node.kind === "input" || node.kind === "output") {
    return node.ports.map((port) => at(port.id, port.side, IO_NODE.height - 17));
  }
  if (node.kind === "placeholder") return node.ports.map((port) => at(port.id, port.side, node.height / 2));
  let y = FLOW_ROW_HEIGHTS.border / 2 + FLOW_ROW_HEIGHTS.header;
  const found: ElkPort[] = [];
  for (const row of node.rows) {
    const height = flowRowHeight(row);
    if (row.kind === "in" || row.kind === "out") found.push(at(row.id, row.kind, y + height / 2));
    y += height;
  }
  return found;
}

/** The ELK graph of a flow graph. */
export function toElk(graph: FlowGraph): ElkNode {
  const root: ElkNode = { id: "root", layoutOptions: ROOT_OPTIONS, children: [], edges: [] };
  const elkNodes = new Map<string, ElkNode>([["root", root]]);
  for (const node of graph.nodes) {
    const elk: ElkNode =
      node.kind === "group"
        ? {
            id: node.id,
            children: [],
            ports: portsOf(node),
            layoutOptions: {
              "elk.portConstraints": "FIXED_POS",
              "elk.padding": `[top=${String(GROUP_HEADER + 18)},left=24,bottom=${String(22 + (node.footer ? GROUP_FOOTER : 0))},right=24]`,
              "elk.spacing.nodeNode": "24",
              "elk.layered.spacing.nodeNodeBetweenLayers": "64",
            },
          }
        : {
            id: node.id,
            width: node.width,
            height: node.height,
            ports: portsOf(node),
            layoutOptions: { "elk.portConstraints": "FIXED_POS" },
          };
    elkNodes.set(node.id, elk);
    elkNodes.get(node.parent ?? "root")?.children?.push(elk);
  }
  root.edges = graph.edges.map((edge): ElkExtendedEdge => ({
    id: edge.id,
    sources: [portId(edge.source, edge.sourceHandle)],
    targets: [portId(edge.target, edge.targetHandle)],
  }));
  return root;
}

/** Positions from ELK's answer: relative to the parent group, as React Flow places child nodes. */
export function positions(laidOut: ElkNode, graph: FlowGraph): Layout {
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const nodes: LayoutNode[] = [];
  const walk = (elk: ElkNode) => {
    for (const child of elk.children ?? []) {
      const node = byId.get(child.id);
      if (node) {
        nodes.push({
          id: node.id,
          kind: node.kind,
          type: node.type,
          parent: node.parent,
          x: child.x ?? 0,
          y: child.y ?? 0,
          width: child.width ?? node.width,
          height: child.height ?? node.height,
        });
      }
      walk(child);
    }
  };
  walk(laidOut);
  return { nodes, width: laidOut.width ?? 0, height: laidOut.height ?? 0 };
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

/** Lay a flow graph out (in a worker when there is one). */
export async function layoutGraph(graph: FlowGraph): Promise<Layout> {
  const elkGraph = toElk(graph);
  const elk = elkInWorker();
  const laidOut = elk
    ? await inWorker(elk, elkGraph).catch(() => inThread(elkGraph))
    : await inThread(elkGraph);
  return positions(laidOut, graph);
}

/** Lay a workflow out. */
export function layoutWorkflow(config: Config | undefined): Promise<Layout> {
  return layoutGraph(buildFlowGraph(config));
}
