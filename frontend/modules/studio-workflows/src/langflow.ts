// Langflow flow JSON, both ways. A workflow exports as a Langflow flow: `ChatInput` and `ChatOutput` at its ends,
// one `genericNode` per step with its settings as template fields and its ports as outputs, Loop / Parallel / Steps
// as Langflow group nodes holding their steps in `node.flow`, sticky notes as `noteNode`s, and connections with
// Langflow's handle encoding (JSON with œ for quotes). Every node also carries its agno config and its place in the
// step tree (`metadata.agnostic`), so a flow exported here imports back as exactly the same workflow.
//
// A flow made in Langflow imports as well as it can: its chat input and output become the workflow's ends, every
// other component that passes messages or data on becomes a Step (in the order its connections run, named after
// the component, with no executor yet), and what doesn't carry over (tools and models wired into a component,
// branches) comes back as warnings.
import type { Config } from "@agnostic/studio";
import { isRecord } from "@agnostic/studio";

import { END, START, buildFlowGraph, type FlowGraph, type GraphNode } from "./graph";
import { layoutGraph, type Layout } from "./layout";
import { newNote, type Note, type Offsets } from "./notes";
import {
  LANES,
  childPath,
  nodeAt,
  nodeName,
  nodeType,
  parsePath,
  uniqueName,
  type Lane,
  type NodeType,
  type WorkflowNode,
} from "./tree";

export const LANGFLOW_VERSION = "1.13.0";

type Json = Record<string, unknown>;

export type LangflowHandle = Json;
export type LangflowNode = {
  id: string;
  type: "genericNode" | "noteNode";
  position: { x: number; y: number };
  width?: number;
  height?: number;
  data: { id: string; type: string; node: Json; showNode?: boolean };
};
export type LangflowEdge = {
  id: string;
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
  className?: string;
  /** The handles again, decoded; Langflow writes them, older or hand-made flows may not. */
  data?: { sourceHandle: LangflowHandle; targetHandle: LangflowHandle };
};
export type LangflowFlow = {
  id: string;
  name: string;
  description: string;
  is_component: false;
  tags: string[];
  last_tested_version: string;
  endpoint_name: string | null;
  data: {
    nodes: LangflowNode[];
    edges: LangflowEdge[];
    viewport: { x: number; y: number; zoom: number };
  };
};

// ---------------------------------------------------------------- handles

/** Langflow writes a handle as JSON with `œ` in place of every double quote. */
export function encodeHandle(handle: LangflowHandle): string {
  return JSON.stringify(handle).replaceAll('"', "œ");
}

export function decodeHandle(handle: string): LangflowHandle | undefined {
  try {
    const parsed: unknown = JSON.parse(handle.replaceAll("œ", '"'));
    return isRecord(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

/** Langflow's id for a node: its component type and a short suffix. Stable per path, so exports diff cleanly. */
export function nodeId(type: string, path: string): string {
  let hash = 0x811c9dc5;
  for (const char of path) {
    hash ^= char.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  const letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
  let suffix = "";
  for (let index = 0; index < 5; index += 1) {
    suffix += letters[hash % letters.length] ?? "a";
    hash = Math.floor(hash / letters.length) + index * 7919;
  }
  return `${type}-${suffix}`;
}

const COMPONENT_TYPE: Record<NodeType, string> = {
  Step: "AgnoStep",
  Steps: "AgnoSteps",
  Parallel: "AgnoParallel",
  Condition: "AgnoCondition",
  Loop: "AgnoLoop",
  Router: "AgnoRouter",
};

const ICON: Record<NodeType, string> = {
  Step: "Box",
  Steps: "ListOrdered",
  Parallel: "Columns3",
  Condition: "Diamond",
  Loop: "Repeat",
  Router: "Split",
};

const DESCRIPTION: Record<NodeType, string> = {
  Step: "Runs an agent, a team, a workflow or a function.",
  Steps: "Runs its steps in sequence.",
  Parallel: "Runs its branches at once.",
  Condition: "Runs its steps when the check is true, its else steps otherwise.",
  Loop: "Repeats its steps until the end condition holds.",
  Router: "Runs the one choice its selector picks.",
};

/** A port's output name in Langflow (`response`, `choice_0`, `true_result`…) and back. */
export function outputName(handle: string): string {
  const choice = /^choices\[(\d+)\]$/.exec(handle);
  if (choice) return `choice_${choice[1] ?? "0"}`;
  return { out: "response", true: "true_result", false: "false_result" }[handle] ?? handle;
}

// ---------------------------------------------------------------- export

function fieldType(value: unknown): string {
  if (typeof value === "boolean") return "bool";
  if (typeof value === "number") return Number.isInteger(value) ? "int" : "float";
  if (typeof value === "string") return "str";
  return "dict";
}

/** A node's own settings: everything but its type and its lanes of children. */
function ownConfig(node: WorkflowNode): WorkflowNode {
  const lanes = new Set<string>(LANES[nodeType(node)]);
  return Object.fromEntries(Object.entries(node).filter(([key]) => !lanes.has(key)));
}

function template(node: WorkflowNode): Json {
  const fields: Json = {
    _type: "Component",
    input_value: {
      type: "str",
      name: "input_value",
      display_name: "Input",
      value: "",
      input_types: ["Message"],
      show: true,
      advanced: false,
      required: false,
      list: false,
      info: "The previous step's output.",
    },
  };
  for (const [key, value] of Object.entries(ownConfig(node))) {
    if (key === "type") continue;
    fields[key] = {
      type: fieldType(value),
      name: key,
      display_name: key.replaceAll("_", " ").replace(/^./, (first) => first.toUpperCase()),
      value,
      show: true,
      advanced: key !== "name" && !key.endsWith("_id") && key !== "executor_ref",
      required: key === "name",
      list: false,
      multiline: typeof value === "string" && value.length > 40,
    };
  }
  return fields;
}

function outputsOf(graphNode: GraphNode): Json[] {
  return graphNode.ports
    .filter((port) => port.side === "out")
    .map((port) => ({
      name: outputName(port.id),
      display_name: port.label,
      types: [port.type === "data" ? "Data" : "Message"],
      selected: port.type === "data" ? "Data" : "Message",
      method: port.type === "route" ? "route" : "run",
      cache: true,
      allows_loop: false,
      tool_mode: false,
    }));
}

type Placed = { x: number; y: number; width: number; height: number };

function ioNode(kind: "input" | "output", at: Placed, inputLabel: string): LangflowNode {
  const input = kind === "input";
  const type = input ? "ChatInput" : "ChatOutput";
  const id = nodeId(type, input ? START : END);
  return {
    id,
    type: "genericNode",
    position: { x: at.x, y: at.y },
    width: at.width,
    height: at.height,
    data: {
      id,
      type,
      node: {
        display_name: input ? "Chat Input" : "Chat Output",
        description: input ? `The workflow's input (${inputLabel}).` : "The workflow's last output.",
        icon: input ? "MessagesSquare" : "MessagesSquare",
        base_classes: ["Message"],
        template: {
          _type: "Component",
          input_value: {
            type: "str",
            name: "input_value",
            display_name: input ? "Input Text" : "Inputs",
            value: "",
            show: true,
            advanced: false,
            ...(input ? {} : { input_types: ["Data", "DataFrame", "Message"] }),
          },
        },
        outputs: [
          {
            name: "message",
            display_name: input ? "Chat Message" : "Output Message",
            types: ["Message"],
            selected: "Message",
            method: "message_response",
            cache: true,
          },
        ],
        metadata: { agnostic: { end: kind } },
      },
    },
  };
}

function langflowEdge(
  source: LangflowNode,
  outputNameValue: string,
  target: LangflowNode,
  outputTypes: string[],
): LangflowEdge {
  const sourceHandle = {
    dataType: source.data.type,
    id: source.id,
    name: outputNameValue,
    output_types: outputTypes,
  };
  const targetHandle = { fieldName: "input_value", id: target.id, inputTypes: ["Message"], type: "str" };
  const encodedSource = encodeHandle(sourceHandle);
  const encodedTarget = encodeHandle(targetHandle);
  return {
    id: `reactflow__edge-${source.id}${encodedSource}-${target.id}${encodedTarget}`,
    source: source.id,
    sourceHandle: encodedSource,
    target: target.id,
    targetHandle: encodedTarget,
    className: "",
    data: { sourceHandle, targetHandle },
  };
}

export type ExportInput = {
  config: Config | undefined;
  /** The workflow's id and name in Studio. */
  id: string;
  name: string;
  inputLabel: string;
  offsets: Offsets;
  notes: readonly Note[];
  viewport?: { x: number; y: number; zoom: number } | undefined;
  /** Lays the graph out; the canvas's own layout by default. */
  layout?: (graph: FlowGraph) => Promise<Layout>;
};

/** The workflow as a Langflow flow. */
export async function toLangflow(input: ExportInput): Promise<LangflowFlow> {
  const graph = buildFlowGraph(input.config, { inputLabel: input.inputLabel });
  const layout = await (input.layout ?? layoutGraph)(graph);
  const placed = new Map<string, Placed>(
    layout.nodes.map((node) => {
      const offset = input.offsets[node.id];
      return [
        node.id,
        {
          x: node.x + (offset?.x ?? 0),
          y: node.y + (offset?.y ?? 0),
          width: node.width,
          height: node.height,
        },
      ];
    }),
  );
  const at = (id: string): Placed => placed.get(id) ?? { x: 0, y: 0, width: 0, height: 0 };
  const byPath = new Map<string, LangflowNode>();
  const scopes = new Map<string, { nodes: LangflowNode[]; edges: LangflowEdge[] }>([
    ["", { nodes: [], edges: [] }],
  ]);
  const scopeOf = (graphNode: GraphNode) => scopes.get(graphNode.parent ?? "") ?? { nodes: [], edges: [] };

  for (const graphNode of graph.nodes) {
    if (graphNode.kind === "placeholder") continue;
    if (graphNode.kind === "input" || graphNode.kind === "output") {
      const io = ioNode(graphNode.kind, at(graphNode.id), input.inputLabel);
      byPath.set(graphNode.id, io);
      scopeOf(graphNode).nodes.push(io);
      continue;
    }
    const config = nodeAt(input.config, graphNode.id) ?? {};
    const type = graphNode.type ?? "Step";
    const componentType = COMPONENT_TYPE[type];
    const id = nodeId(componentType, graphNode.id);
    const box = at(graphNode.id);
    const node: Json = {
      display_name: nodeName(config) || type,
      description: DESCRIPTION[type],
      icon: ICON[type],
      base_classes: ["Message"],
      template: template(config),
      outputs: outputsOf(graphNode),
      field_order: ["input_value", ...Object.keys(ownConfig(config)).filter((key) => key !== "type")],
      frozen: false,
      minimized: false,
      metadata: { agnostic: { path: graphNode.id, node: ownConfig(config) } },
    };
    const flowNode: LangflowNode = {
      id,
      type: "genericNode",
      position: { x: box.x, y: box.y },
      width: box.width,
      height: box.height,
      data: { id, type: componentType, node },
    };
    if (graphNode.kind === "group") {
      const inner = { nodes: [] as LangflowNode[], edges: [] as LangflowEdge[] };
      scopes.set(graphNode.id, inner);
      node.flow = { data: { nodes: inner.nodes, edges: inner.edges, viewport: { x: 0, y: 0, zoom: 1 } } };
    }
    byPath.set(graphNode.id, flowNode);
    scopeOf(graphNode).nodes.push(flowNode);
  }
  for (const edge of graph.edges) {
    const source = byPath.get(edge.source);
    const target = byPath.get(edge.target);
    if (!source || !target) continue;
    const sourceNode = graph.nodes.find((item) => item.id === edge.source);
    const name = edge.source === START ? "message" : outputName(edge.sourceHandle);
    const types = [edge.port === "data" ? "Data" : "Message"];
    const scope = scopes.get(sourceNode?.parent ?? "") ?? scopes.get("");
    scope?.edges.push(langflowEdge(source, name, target, types));
  }
  const root = scopes.get("") ?? { nodes: [], edges: [] };
  for (const note of input.notes) {
    const id = nodeId("note", note.id);
    root.nodes.push({
      id,
      type: "noteNode",
      position: { x: note.x, y: note.y },
      width: note.width,
      data: {
        id,
        type: "note",
        node: {
          description: note.text,
          display_name: "",
          documentation: "",
          template: { backgroundColor: "amber" },
          metadata: { agnostic: { note: note.id } },
        },
      },
    });
  }
  return {
    id: input.id,
    name: input.name,
    description: typeof input.config?.description === "string" ? input.config.description : "",
    is_component: false,
    tags: ["agno"],
    last_tested_version: LANGFLOW_VERSION,
    endpoint_name: null,
    data: { nodes: root.nodes, edges: root.edges, viewport: input.viewport ?? { x: 0, y: 0, zoom: 1 } },
  };
}

// ---------------------------------------------------------------- import

export type ImportResult = {
  /** The workflow's steps, to replace the draft's. */
  steps: WorkflowNode[];
  notes: Note[];
  warnings: string[];
  /** `agnostic`: exported from Studio, read back exactly; `langflow`: a flow made in Langflow. */
  source: "agnostic" | "langflow";
};

/** Every node of a flow, group contents included. */
function allNodes(nodes: readonly unknown[]): LangflowNode[] {
  return nodes.flatMap((item): LangflowNode[] => {
    if (!isRecord(item) || !isRecord(item.data) || !isRecord(item.data.node)) return [];
    const node = item as unknown as LangflowNode;
    const flow = node.data.node.flow;
    const inner =
      isRecord(flow) && isRecord(flow.data) && Array.isArray(flow.data.nodes) ? flow.data.nodes : [];
    return [node, ...allNodes(inner)];
  });
}

function allEdges(nodes: readonly unknown[], edges: readonly unknown[]): LangflowEdge[] {
  const own = edges.filter((item): item is LangflowEdge => isRecord(item) && typeof item.source === "string");
  const inner = allNodes(nodes).flatMap((node) => {
    const flow = node.data.node.flow;
    return isRecord(flow) && isRecord(flow.data) && Array.isArray(flow.data.edges)
      ? flow.data.edges.filter(
          (item): item is LangflowEdge => isRecord(item) && typeof item.source === "string",
        )
      : [];
  });
  return [...own, ...inner];
}

function agnosticOf(node: LangflowNode): Json | undefined {
  const metadata = node.data.node.metadata;
  return isRecord(metadata) && isRecord(metadata.agnostic) ? metadata.agnostic : undefined;
}

function notesOf(nodes: LangflowNode[]): Note[] {
  return nodes
    .filter((node) => node.type === "noteNode")
    .map((node) => {
      const text = typeof node.data.node.description === "string" ? node.data.node.description : "";
      const note = newNote(Math.round(node.position.x), Math.round(node.position.y), text);
      const own = agnosticOf(node);
      return {
        ...note,
        id: typeof own?.note === "string" ? own.note : note.id,
        width: typeof node.width === "number" ? node.width : note.width,
      };
    });
}

/** Put nodes back in their tree from the paths they carry. */
function fromPaths(entries: { path: string; node: WorkflowNode }[]): WorkflowNode[] {
  const root: WorkflowNode = { steps: [] };
  const byPath = new Map<string, WorkflowNode>([["", root]]);
  const sorted = [...entries].sort((a, b) => parsePath(a.path).length - parsePath(b.path).length);
  for (const entry of sorted) {
    const segments = parsePath(entry.path);
    const last = segments.at(-1);
    if (!last) continue;
    const parent = segments
      .slice(0, -1)
      .reduce((prefix, segment) => childPath(prefix, segment.lane, segment.index), "");
    const owner = byPath.get(parent);
    if (!owner) continue;
    const node: WorkflowNode = { ...entry.node };
    for (const lane of LANES[nodeType(node)]) node[lane] = [];
    const lane = (Array.isArray(owner[last.lane]) ? owner[last.lane] : (owner[last.lane] = [])) as (
      WorkflowNode | undefined
    )[];
    lane[last.index] = node;
    byPath.set(entry.path, node);
  }
  // Drop holes (a node removed in Langflow) so every lane is a plain list again.
  const compact = (node: WorkflowNode) => {
    for (const lane of ["steps", "else_steps", "choices"] as Lane[]) {
      if (Array.isArray(node[lane])) {
        node[lane] = (node[lane] as (WorkflowNode | undefined)[]).filter(
          (item): item is WorkflowNode => !!item,
        );
        (node[lane] as WorkflowNode[]).forEach(compact);
      }
    }
  };
  compact(root);
  return root.steps as WorkflowNode[];
}

const INPUTS = new Set(["ChatInput", "TextInput", "Webhook"]);
const OUTPUTS = new Set(["ChatOutput", "TextOutput"]);
/** Connections that hand a component a capability rather than pass the run on. */
const ATTACHMENTS = new Set([
  "Tool",
  "LanguageModel",
  "Embeddings",
  "Memory",
  "VectorStore",
  "Retriever",
  "BaseChatMemory",
  "Toolset",
]);

function edgeTypes(edge: LangflowEdge): { out: string[]; in: string[] } {
  const source = isRecord(edge.data?.sourceHandle) ? edge.data.sourceHandle : decodeHandle(edge.sourceHandle);
  const target = isRecord(edge.data?.targetHandle) ? edge.data.targetHandle : decodeHandle(edge.targetHandle);
  const list = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);
  return { out: list(source?.output_types), in: list(target?.inputTypes) };
}

function isAttachment(edge: LangflowEdge): boolean {
  const types = edgeTypes(edge);
  return [...types.out, ...types.in].some((type) => ATTACHMENTS.has(type)) && !types.out.includes("Message");
}

function displayName(node: LangflowNode): string {
  const name = node.data.node.display_name;
  return typeof name === "string" && name.trim() ? name.trim() : node.data.type;
}

/** A flow made in Langflow: its message-passing components in the order they run, as Steps. */
function fromLangflowGraph(nodes: LangflowNode[], edges: LangflowEdge[], warnings: string[]): WorkflowNode[] {
  const components = nodes.filter(
    (node) =>
      node.type === "genericNode" &&
      !INPUTS.has(node.data.type) &&
      !OUTPUTS.has(node.data.type) &&
      !isRecord(node.data.node.flow),
  );
  const ids = new Set(components.map((node) => node.id));
  const attachments = edges.filter((edge) => isAttachment(edge));
  const flowEdges = edges.filter(
    (edge) => !isAttachment(edge) && ids.has(edge.source) && ids.has(edge.target),
  );
  const byId = new Map(nodes.map((node) => [node.id, node]));
  // A component that only hands others a tool or a model isn't a step of its own.
  const feeding = new Set(attachments.map((edge) => edge.source));
  const passing = new Set(flowEdges.flatMap((edge) => [edge.source, edge.target]));
  for (const edge of edges) {
    if (
      !isAttachment(edge) &&
      (INPUTS.has(byId.get(edge.source)?.data.type ?? "") ||
        OUTPUTS.has(byId.get(edge.target)?.data.type ?? ""))
    ) {
      passing.add(edge.source);
      passing.add(edge.target);
    }
  }
  const steps = components.filter((node) => passing.has(node.id) || !feeding.has(node.id));
  const stepIds = new Set(steps.map((node) => node.id));
  for (const edge of attachments) {
    const from = byId.get(edge.source);
    const into = byId.get(edge.target);
    if (from && into) {
      warnings.push(
        `${displayName(from)} is wired into ${displayName(into)} as a ${edgeTypes(edge).out[0] ?? "capability"}: give the step's agent that tool or model in the agent editor.`,
      );
    }
  }
  // Kahn's order over the message connections; ties go left to right, then top to bottom, as the flow reads.
  const incoming = new Map(steps.map((node) => [node.id, 0]));
  const next = new Map<string, string[]>();
  for (const edge of flowEdges) {
    if (!stepIds.has(edge.source) || !stepIds.has(edge.target)) continue;
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
    next.set(edge.source, [...(next.get(edge.source) ?? []), edge.target]);
  }
  const readingOrder = (a: string, b: string) => {
    const left = byId.get(a)?.position ?? { x: 0, y: 0 };
    const right = byId.get(b)?.position ?? { x: 0, y: 0 };
    return left.x - right.x || left.y - right.y;
  };
  const ready = steps.filter((node) => (incoming.get(node.id) ?? 0) === 0).map((node) => node.id);
  const order: string[] = [];
  while (ready.length) {
    ready.sort(readingOrder);
    const id = ready.shift();
    if (!id) break;
    order.push(id);
    const targets = next.get(id) ?? [];
    const from = byId.get(id);
    if (from && new Set(targets).size > 1) {
      warnings.push(
        `${displayName(from)} passes its output to ${String(new Set(targets).size)} components: they run one after another here. Wrap them in a Parallel to run them at once.`,
      );
    }
    for (const target of targets) {
      const left = (incoming.get(target) ?? 1) - 1;
      incoming.set(target, left);
      if (left === 0) ready.push(target);
    }
  }
  const cyclic = steps.filter((node) => !order.includes(node.id));
  if (cyclic.length) {
    warnings.push(`${cyclic.map(displayName).join(", ")} form a cycle: they come last, in reading order.`);
    order.push(...cyclic.map((node) => node.id).sort(readingOrder));
  }
  const taken = new Set<string>();
  const made = order.flatMap((id): WorkflowNode[] => {
    const node = byId.get(id);
    if (!node) return [];
    const name = uniqueName(taken, displayName(node));
    taken.add(name);
    return [{ type: "Step", name }];
  });
  if (made.length) {
    warnings.push(
      `${String(made.length)} step${made.length === 1 ? " has" : "s have"} no executor yet: pick an agent, team or function for each in the inspector.`,
    );
  }
  return made;
}

/** A Langflow flow (one exported here, or made in Langflow) as workflow steps and notes. */
export function fromLangflow(input: unknown): ImportResult {
  const flow = isRecord(input) ? input : {};
  const data = isRecord(flow.data) ? flow.data : {};
  const rawNodes = Array.isArray(data.nodes) ? data.nodes : [];
  const rawEdges = Array.isArray(data.edges) ? data.edges : [];
  if (rawNodes.length === 0) throw new Error("This file isn't a Langflow flow: it has no nodes.");
  const nodes = allNodes(rawNodes);
  const edges = allEdges(rawNodes, rawEdges);
  const notes = notesOf(nodes);
  const warnings: string[] = [];
  const components = nodes.filter((node) => node.type === "genericNode");
  const placed = components.flatMap((node) => {
    const own = agnosticOf(node);
    return own && typeof own.path === "string" && isRecord(own.node)
      ? [{ path: own.path, node: own.node, id: node.id }]
      : [];
  });
  if (placed.length > 0) {
    const steps = fromPaths(placed);
    const known = new Set(placed.map((item) => item.id));
    const added = components.filter(
      (node) => !known.has(node.id) && !INPUTS.has(node.data.type) && !OUTPUTS.has(node.data.type),
    );
    if (added.length) {
      const taken = new Set(placed.map((item) => nodeName(item.node)));
      for (const node of added) {
        const name = uniqueName(taken, displayName(node));
        taken.add(name);
        steps.push({ type: "Step", name });
      }
      warnings.push(
        `${added.map(displayName).join(", ")} ${added.length === 1 ? "was" : "were"} added in Langflow: ${added.length === 1 ? "it comes" : "they come"} last, with no executor yet.`,
      );
    }
    return { steps, notes, warnings, source: "agnostic" };
  }
  return { steps: fromLangflowGraph(nodes, edges, warnings), notes, warnings, source: "langflow" };
}
