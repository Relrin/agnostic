// The workflow tree as a flow graph: components with typed input and output ports and the rows they show,
// group frames for Steps / Loop / Parallel, the workflow's input and output, drop zones for empty lanes, and the
// connections between ports, each with the slot its "+" inserts into. Nodes are addressed by their config path,
// ports by a handle id (`in`, `out`, `choices[2]`, `true`, `false`). The canvas, the layout and the Langflow
// export all read this one projection, so they agree on what connects to what.
import type { Config } from "@agnostic/studio";
import {
  FLOW_NODE_WIDTH,
  GROUP_FOOTER,
  GROUP_HEADER,
  IO_NODE,
  flowNodeHeight,
  type FlowRow,
  type PortType,
} from "@agnostic/ui";

import {
  LANES,
  childPath,
  children,
  executorOf,
  nodeName,
  nodeType,
  rootSteps,
  type Executor,
  type Lane,
  type NodeType,
  type Slot,
  type WorkflowNode,
} from "./tree";

export const START = "start";
export const END = "end";
export const PLACEHOLDER = { width: 220, height: 56 } as const;

export type GraphPort = { id: string; side: "in" | "out"; type: PortType; label: string };

export type GraphNode = {
  id: string;
  kind: "component" | "group" | "input" | "output" | "placeholder";
  type?: NodeType | undefined;
  parent: string | undefined;
  ports: GraphPort[];
  rows: FlowRow[];
  width: number;
  height: number;
  /** A group's frame header and footer, which its padding leaves room for. */
  footer?: boolean | undefined;
  /** For a placeholder: where a dropped step goes. */
  slot?: Slot | undefined;
};

export type GraphEdge = {
  id: string;
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
  port: PortType;
  /** Where "+" on this connection inserts. */
  slot?: Slot | undefined;
};

export type FlowGraph = { nodes: GraphNode[]; edges: GraphEdge[] };

/** What the canvas knows about an executor beyond its id: an agent's model and tools. */
export type ExecutorDetails = { model?: string | undefined; tools?: readonly string[] | undefined };
export type DetailsLookup = (executor: Executor) => ExecutorDetails | undefined;

const KIND_TITLE: Record<Executor["kind"], string> = {
  agent: "Agent",
  team: "Team",
  workflow: "Workflow",
  function: "Function",
};

/** A CEL expression broken before its top-level `||`, `&&`, `?` and `:` so the node can show it on a few lines. */
export function celLines(expression: string): string[] {
  const lines: string[] = [];
  let current = "";
  let quote: string | undefined;
  let depth = 0;
  for (let index = 0; index < expression.length; index += 1) {
    const char = expression[index] ?? "";
    if (quote) {
      current += char;
      if (char === "\\") {
        current += expression[index + 1] ?? "";
        index += 1;
      } else if (char === quote) quote = undefined;
      continue;
    }
    if (char === '"' || char === "'") quote = char;
    if (char === "(" || char === "[" || char === "{") depth += 1;
    if (char === ")" || char === "]" || char === "}") depth -= 1;
    const rest = expression.slice(index);
    if (depth === 0 && current.trim() && /^ (\|\||&&|\?|:) /.test(rest)) {
      lines.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  if (current.trim()) lines.push(current.trim());
  return lines.length ? lines : [expression];
}

function callableRow(node: WorkflowNode, field: string, label: string): FlowRow | undefined {
  const value = node[field];
  if (typeof value === "boolean") return { kind: "field", label, value: `always ${String(value)}` };
  if (typeof value !== "string" || value === "")
    return { kind: "field", label, value: "not set yet", mono: false };
  if (node[`${field}_type`] === "function") return { kind: "field", label: `${label} · function`, value };
  return { kind: "area", label: `${label} · CEL`, lines: celLines(value) };
}

function component(id: string, parent: string | undefined, type: NodeType, rows: FlowRow[]): GraphNode {
  const ports: GraphPort[] = rows.flatMap((row) =>
    row.kind === "in" || row.kind === "out"
      ? [{ id: row.id, side: row.kind, type: row.port, label: row.label }]
      : [],
  );
  return {
    id,
    kind: "component",
    type,
    parent,
    ports,
    rows,
    width: FLOW_NODE_WIDTH,
    height: flowNodeHeight(rows),
  };
}

/** A tool block on an agent node; tool catalog names start with their level (org-, team-, custom-). */
export function toolChip(name: string): { label: string; tone?: "org" | "team" | "custom" } {
  const level = /^(org|team|custom)-/.exec(name)?.[1] as "org" | "team" | "custom" | undefined;
  return level ? { label: name, tone: level } : { label: name };
}

/** The rows a node shows, from its config (and what's known about its executor). */
export function rowsOf(node: WorkflowNode, details?: DetailsLookup): FlowRow[] {
  const type = nodeType(node);
  const input: FlowRow = { kind: "in", id: "in", label: "Input", port: "message" };
  switch (type) {
    case "Step": {
      const executor = executorOf(node);
      const known = executor ? details?.(executor) : undefined;
      const rows: FlowRow[] = [
        {
          kind: "desc",
          text: executor ? `${KIND_TITLE[executor.kind]} · ${executor.id}` : "No executor yet: pick one",
        },
        input,
      ];
      if (known?.model) rows.push({ kind: "field", label: "Model", value: known.model });
      if (known?.tools?.length)
        rows.push({ kind: "chips", label: "Tools", items: known.tools.map(toolChip) });
      rows.push({ kind: "sep" }, { kind: "out", id: "out", label: "Response", port: "message" });
      return rows;
    }
    case "Router": {
      const choices = children(node, "choices");
      const rows: FlowRow[] = [{ kind: "desc", text: "Router · runs one choice" }, input];
      const selector = callableRow(node, "selector", "Selector");
      if (selector) rows.push(selector);
      if (choices.length === 0) rows.push({ kind: "out", id: "add", label: "No choices yet", port: "route" });
      choices.forEach((choice, index) => {
        rows.push({
          kind: "out",
          id: `choices[${String(index)}]`,
          label: nodeName(choice) || `Choice ${String(index + 1)}`,
          port: "route",
        });
      });
      return rows;
    }
    case "Condition": {
      const rows: FlowRow[] = [{ kind: "desc", text: "Condition · if, else" }, input];
      const evaluator = callableRow(node, "evaluator", "Evaluator");
      if (evaluator) rows.push(evaluator);
      rows.push(
        { kind: "out", id: "true", label: "True", port: "route" },
        { kind: "out", id: "false", label: "Else", port: "route" },
      );
      return rows;
    }
    case "Steps":
    case "Loop":
    case "Parallel":
      return [];
  }
}

/** A group's label on its frame: "LOOP · MAX 3", "PARALLEL", "STEPS". */
export function groupLabel(node: WorkflowNode): string {
  const type = nodeType(node);
  if (type === "Loop") {
    const max = typeof node.max_iterations === "number" ? node.max_iterations : 3;
    return `LOOP · MAX ${String(max)}`;
  }
  return type.toUpperCase();
}

type Exit = { node: string; handle: string; port: PortType };

/** The flow graph of a workflow. */
export function buildFlowGraph(
  config: Config | undefined,
  options: { inputLabel?: string; details?: DetailsLookup } = {},
): FlowGraph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const parentOf = (container: string) => (container === "root" ? undefined : container);

  const connect = (exits: Exit[], target: string, slot?: Slot) => {
    exits.forEach((exit, index) => {
      edges.push({
        id: `${exit.node}:${exit.handle}->${target}`,
        source: exit.node,
        sourceHandle: exit.handle,
        target,
        targetHandle: "in",
        port: exit.port,
        // One "+" per join: on the last of the connections meeting at the target.
        slot: index === exits.length - 1 ? slot : undefined,
      });
    });
  };

  const placeholder = (id: string, container: string, slot: Slot) => {
    nodes.push({
      id,
      kind: "placeholder",
      parent: parentOf(container),
      ports: [
        { id: "in", side: "in", type: "message", label: "Input" },
        { id: "out", side: "out", type: "message", label: "Output" },
      ],
      rows: [],
      ...PLACEHOLDER,
      slot,
    });
  };

  /** A lane's nodes in sequence after `from`; returns what the next node connects from. */
  const sequence = (
    items: WorkflowNode[],
    container: string,
    parent: string,
    lane: Lane,
    from: Exit[],
  ): Exit[] => {
    let exits = from;
    items.forEach((item, index) => {
      const path = childPath(parent, lane, index);
      const placed = emit(item, path, container);
      if (exits.length) connect(exits, path, { parent, lane, index });
      exits = placed;
    });
    return exits;
  };

  const emit = (item: WorkflowNode, path: string, container: string): Exit[] => {
    const type = nodeType(item);
    if (type === "Steps" || type === "Loop" || type === "Parallel") {
      nodes.push({
        id: path,
        kind: "group",
        type,
        parent: parentOf(container),
        ports: [
          { id: "in", side: "in", type: "message", label: "Input" },
          { id: "out", side: "out", type: "message", label: "Output" },
        ],
        rows: [],
        width: FLOW_NODE_WIDTH,
        height: GROUP_HEADER + (type === "Loop" ? GROUP_FOOTER : 0),
        footer: type === "Loop",
      });
      const inner = children(item, "steps");
      if (inner.length === 0) placeholder(`${path}::empty`, path, { parent: path, lane: "steps", index: 0 });
      else if (type === "Parallel")
        inner.forEach((child, index) => emit(child, childPath(path, "steps", index), path));
      else sequence(inner, path, path, "steps", []);
      return [{ node: path, handle: "out", port: "message" }];
    }
    const rows = rowsOf(item, options.details);
    nodes.push(component(path, parentOf(container), type, rows));
    if (type === "Step") return [{ node: path, handle: "out", port: "message" }];

    // Router and Condition: the branches follow the node in the same container and join at the next node.
    const exits: Exit[] = [];
    if (type === "Router") {
      const choices = children(item, "choices");
      if (choices.length === 0) {
        const id = `${path}::choices`;
        placeholder(id, container, { parent: path, lane: "choices", index: 0 });
        connect([{ node: path, handle: "add", port: "route" }], id);
        return [{ node: id, handle: "out", port: "message" }];
      }
      choices.forEach((choice, index) => {
        const choicePath = childPath(path, "choices", index);
        const placed = emit(choice, choicePath, container);
        connect([{ node: path, handle: `choices[${String(index)}]`, port: "route" }], choicePath);
        exits.push(...placed);
      });
      return exits;
    }
    for (const lane of LANES[type]) {
      const handle = lane === "else_steps" ? "false" : "true";
      const from: Exit = { node: path, handle, port: "route" };
      const items = children(item, lane);
      if (items.length === 0) {
        if (lane === "steps") {
          const id = `${path}::${lane}`;
          placeholder(id, container, { parent: path, lane, index: 0 });
          connect([from], id);
          exits.push({ node: id, handle: "out", port: "message" });
        } else {
          // No else branch: when the check is false the run goes straight on.
          exits.push(from);
        }
        continue;
      }
      exits.push(...sequence(items, container, path, lane, [from]));
    }
    return exits;
  };

  nodes.push({
    id: START,
    kind: "input",
    parent: undefined,
    ports: [{ id: "out", side: "out", type: "message", label: options.inputLabel ?? "input" }],
    rows: [],
    ...IO_NODE,
  });
  const steps = rootSteps(config);
  const exits = sequence(steps, "root", "", "steps", [{ node: START, handle: "out", port: "message" }]);
  nodes.push({
    id: END,
    kind: "output",
    parent: undefined,
    ports: [{ id: "in", side: "in", type: "message", label: "Output" }],
    rows: [],
    ...IO_NODE,
  });
  connect(exits, END, { parent: "", lane: "steps", index: steps.length });
  return { nodes, edges };
}

/** What the layout depends on: nodes, their sizes and parents, and the connections. Names and settings that
 * don't change a node's size don't move anything. */
export function layoutKey(graph: FlowGraph): string {
  return JSON.stringify([
    graph.nodes.map((node) => [node.id, node.parent ?? "", node.width, node.height, node.ports.length]),
    graph.edges.map((edge) => edge.id),
  ]);
}

/** The port types a graph uses, for the legend. */
export function portTypesOf(graph: FlowGraph): PortType[] {
  const used = new Set(graph.edges.map((edge) => edge.port));
  return (["message", "data", "route"] as const).filter((type) => used.has(type));
}

function preview(text: string, max = 36): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function callableChip(node: WorkflowNode, field: string): string | undefined {
  const value = node[field];
  if (typeof value === "boolean") return `always ${value ? "true" : "false"}`;
  if (typeof value !== "string" || value === "") return undefined;
  if (node[`${field}_type`] === "function") return `fn · ${value}`;
  return `cel · ${preview(value)}`;
}

const CHIP_KIND: Record<Executor["kind"], string> = {
  agent: "agent",
  team: "team",
  workflow: "workflow",
  function: "fn",
};

/** How a node reads besides its rows: the description assistive tech hears ("agent · support-triage", a CEL
 * preview), the idle meta ("avg 1.1 s", "3 choices") and a Loop's "until …". */
export function describeNode(
  node: WorkflowNode,
  avgMs: number | undefined,
): { chip?: string | undefined; meta?: string | undefined; footer?: string | undefined } {
  const type = nodeType(node);
  const stats =
    avgMs !== undefined
      ? `avg ${avgMs >= 1000 ? `${(avgMs / 1000).toFixed(1)} s` : `${String(Math.round(avgMs))} ms`}`
      : undefined;
  switch (type) {
    case "Step": {
      const executor = executorOf(node);
      return {
        meta: stats,
        chip: executor ? `${CHIP_KIND[executor.kind]} · ${executor.id}` : "no executor yet",
      };
    }
    case "Router": {
      const count = children(node, "choices").length;
      return {
        meta: `${String(count)} choice${count === 1 ? "" : "s"}`,
        chip: callableChip(node, "selector"),
      };
    }
    case "Condition":
      return { meta: stats, chip: callableChip(node, "evaluator") };
    case "Loop": {
      const until = callableChip(node, "end_condition");
      return { footer: until ? `until ${until.replace(/^cel · /, "")}` : undefined };
    }
    case "Parallel": {
      const count = children(node, "steps").length;
      return { meta: `${String(count)} branch${count === 1 ? "" : "es"}` };
    }
    case "Steps": {
      const count = children(node, "steps").length;
      return { meta: `${String(count)} step${count === 1 ? "" : "s"}` };
    }
  }
}
