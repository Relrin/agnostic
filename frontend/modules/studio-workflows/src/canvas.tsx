// The workflow canvas: React Flow drawing the tree that layout.ts placed. Start, steps, containers holding their steps,
// Condition and Router branches with their labels, "+" on every connector (click to add a step, or drop a palette
// item or a step's grip on it), and the end. Keyboard: arrows move between steps, Enter opens the inspector, Delete
// removes (with undo), Ctrl+C / Ctrl+V copy and paste a subtree, Ctrl+Z / Ctrl+Shift+Z undo and redo.
import {
  Background,
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getSmoothStepPath,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Config } from "@agnostic/studio";
import {
  BranchLabel,
  InsertButton,
  NODE_COLORS,
  NodeCard,
  WorkflowGlyph,
  cn,
  type BranchTone,
  type WorkflowNodeStatus,
} from "@agnostic/ui";
import { GripVertical, Plus } from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
} from "react";

import { DRAG_TYPE, readDragItem, useBuilderContext, type DragItem } from "./context";
import { useBuilder } from "./history";
import { START, layoutWorkflow, type Layout, type LayoutEdge, type LayoutNode } from "./layout";
import { executorLabel } from "./schema";
import {
  LANES,
  children,
  executorOf,
  neighbour,
  nodeAt,
  nodeName,
  nodeType,
  parentOf,
  rootSteps,
  type NodeType,
  type Slot,
  type WorkflowNode,
} from "./tree";

export type Offsets = Record<string, { x: number; y: number }>;

type CardData = {
  path: string;
  type: NodeType;
  title: string;
  meta?: string | undefined;
  chip?: string | undefined;
  status: WorkflowNodeStatus;
  problems: number;
  footer?: string | undefined;
};
type TerminalData = { label: string; start: boolean };
type PlaceholderData = { slot: Slot };
type StepFlowNode = Node<CardData, "step">;
type ContainerFlowNode = Node<CardData, "container">;
type TerminalFlowNode = Node<TerminalData, "terminal">;
type PlaceholderFlowNode = Node<PlaceholderData, "placeholder">;
type FlowNode = StepFlowNode | ContainerFlowNode | TerminalFlowNode | PlaceholderFlowNode;
type InsertFlowEdge = Edge<
  { slot?: Slot | undefined; label?: string | undefined; tone?: BranchTone | undefined },
  "insert"
>;

const HIDDEN_HANDLE = "!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent";

function preview(text: string, max = 36): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function seconds(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${String(Math.round(ms))} ms`;
}

function callable(node: WorkflowNode, field: string): string | undefined {
  const value = node[field];
  if (typeof value === "boolean") return `always ${value ? "true" : "false"}`;
  if (typeof value !== "string" || value === "") return undefined;
  if (node[`${field}_type`] === "function") return `fn · ${value}`;
  return `cel · ${preview(value)}`;
}

/** How a node reads on the canvas. */
export function describeNode(
  node: WorkflowNode,
  avgMs: number | undefined,
): Omit<CardData, "path" | "status" | "problems"> {
  const type = nodeType(node);
  const title = nodeName(node);
  const stats = avgMs !== undefined ? `avg ${seconds(avgMs)}` : undefined;
  switch (type) {
    case "Step": {
      const executor = executorOf(node);
      return { type, title, meta: stats, chip: executor ? executorLabel(executor) : "no executor yet" };
    }
    case "Router": {
      const count = children(node, "choices").length;
      return {
        type,
        title,
        meta: `${String(count)} choice${count === 1 ? "" : "s"}`,
        chip: callable(node, "selector"),
      };
    }
    case "Condition":
      return { type, title, meta: stats, chip: callable(node, "evaluator") };
    case "Loop": {
      const max = typeof node.max_iterations === "number" ? node.max_iterations : 3;
      const until = callable(node, "end_condition");
      return {
        type,
        title,
        meta: `max ${String(max)}`,
        footer: until ? `until ${until.replace(/^cel · /, "")}` : undefined,
      };
    }
    case "Parallel": {
      const count = children(node, "steps").length;
      return { type, title, meta: `${String(count)} branch${count === 1 ? "" : "es"}` };
    }
    case "Steps": {
      const count = children(node, "steps").length;
      return { type, title, meta: `${String(count)} step${count === 1 ? "" : "s"}` };
    }
  }
}

/** The shape layout depends on: node types and how many children each has, not names or settings. */
export function structureKey(config: Config | undefined): string {
  const shape = (node: WorkflowNode): unknown => {
    const type = nodeType(node);
    return [type, ...LANES[type].map((lane) => children(node, lane).map(shape))];
  };
  return JSON.stringify(rootSteps(config).map(shape));
}

// ---------------------------------------------------------------- nodes

function Grip({ path }: { path: string }) {
  const { readOnly } = useBuilderContext();
  if (readOnly) return null;
  return (
    <span
      draggable
      role="button"
      tabIndex={-1}
      aria-label="Drag to move this step"
      className="nodrag absolute top-2 -left-5 cursor-grab text-fg-faint hover:text-fg-secondary"
      onDragStart={(event) => {
        event.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ move: path } satisfies DragItem));
        event.dataTransfer.effectAllowed = "move";
      }}
    >
      <GripVertical aria-hidden className="size-4" />
    </span>
  );
}

const StepView = memo(function StepView({ data }: NodeProps<StepFlowNode>) {
  const { store } = useBuilderContext();
  const selected = useBuilder(store, (state) => state.selected === data.path);
  return (
    <div className="relative" data-path={data.path}>
      <Handle type="target" position={Position.Top} isConnectable={false} className={HIDDEN_HANDLE} />
      <Grip path={data.path} />
      <NodeCard
        type={data.type}
        title={data.title}
        meta={data.meta}
        chip={data.chip}
        status={data.status}
        problems={data.problems}
        selected={selected}
        onSelect={() => {
          store.getState().select(data.path);
        }}
      />
      <Handle type="source" position={Position.Bottom} isConnectable={false} className={HIDDEN_HANDLE} />
    </div>
  );
});

const ContainerView = memo(function ContainerView({ data, width, height }: NodeProps<ContainerFlowNode>) {
  const { store, actions, readOnly, doc } = useBuilderContext();
  const selected = useBuilder(store, (state) => state.selected === data.path);
  const color = NODE_COLORS[data.type];
  return (
    <div
      data-path={data.path}
      className={cn(
        "relative rounded-card border bg-canvas/80",
        selected && "ring-[3px] ring-accent/16",
        data.status === "running" && "ring-[3px] ring-info/30",
      )}
      style={{
        width,
        height,
        borderColor: selected ? "var(--accent)" : `color-mix(in srgb, ${color} 45%, transparent)`,
      }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} className={HIDDEN_HANDLE} />
      <Grip path={data.path} />
      <button
        type="button"
        aria-pressed={selected}
        aria-label={`${data.type} ${data.title}${data.problems ? `, ${String(data.problems)} problems` : ""}`}
        className="flex w-full items-center gap-2 rounded-t-card px-3 py-2 text-left focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none"
        onClick={() => {
          store.getState().select(data.path);
        }}
      >
        <WorkflowGlyph type={data.type} />
        <span className="font-mono text-[10.5px] uppercase" style={{ color }}>
          {data.type}
        </span>
        <span className="truncate text-[13px] font-medium">{data.title || "Untitled"}</span>
        <span className="flex-1" />
        {data.problems > 0 && <span className="text-[11px] text-danger">{data.problems}</span>}
        {data.meta && <span className="text-[11px] text-fg-muted">{data.meta}</span>}
      </button>
      {!readOnly && (
        <button
          type="button"
          aria-label={`Add a step at the end of ${data.title || data.type}`}
          className="nodrag absolute right-2 bottom-2 inline-flex size-[22px] items-center justify-center rounded-full border border-border bg-surface text-fg-secondary hover:border-accent hover:text-accent"
          onClick={() => {
            const node = nodeAt(doc.config, data.path);
            actions.add({ parent: data.path, lane: "steps", index: children(node, "steps").length }, "Step");
          }}
        >
          <Plus aria-hidden className="size-3.5" />
        </button>
      )}
      {data.footer && (
        <span className="absolute bottom-2.5 left-3 max-w-[70%] truncate font-mono text-[10.5px] text-fg-muted">
          {data.footer}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} isConnectable={false} className={HIDDEN_HANDLE} />
    </div>
  );
});

const TerminalView = memo(function TerminalView({ data }: NodeProps<TerminalFlowNode>) {
  return (
    <div className="flex h-8 items-center gap-2 rounded-full border border-border-strong bg-surface px-4 text-[12.5px]">
      {!data.start && (
        <Handle type="target" position={Position.Top} isConnectable={false} className={HIDDEN_HANDLE} />
      )}
      <span
        aria-hidden
        className={cn("size-[7px]", data.start ? "rounded-full bg-accent" : "rounded-[2px] bg-fg-muted")}
      />
      <span className="truncate">{data.label}</span>
      {data.start && (
        <Handle type="source" position={Position.Bottom} isConnectable={false} className={HIDDEN_HANDLE} />
      )}
    </div>
  );
});

function useDropOn(slot: Slot | undefined) {
  const { actions } = useBuilderContext();
  return useCallback(
    (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      const item = readDragItem(event.dataTransfer);
      if (item && slot) actions.drop(slot, item);
    },
    [actions, slot],
  );
}

const PlaceholderView = memo(function PlaceholderView({
  data,
  width,
  height,
}: NodeProps<PlaceholderFlowNode>) {
  const { actions, readOnly } = useBuilderContext();
  const drop = useDropOn(data.slot);
  return (
    <div
      className="flex items-center justify-center gap-2 rounded-control border border-dashed border-border-dashed text-[12px] text-fg-muted"
      style={{ width, height }}
      onDragOver={(event) => {
        event.preventDefault();
      }}
      onDrop={drop}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} className={HIDDEN_HANDLE} />
      <InsertButton
        label="Add a step here"
        disabled={readOnly}
        onInsert={() => {
          actions.add(data.slot, "Step");
        }}
        onDropItem={drop}
      />
      Drop a step here
      <Handle type="source" position={Position.Bottom} isConnectable={false} className={HIDDEN_HANDLE} />
    </div>
  );
});

// ---------------------------------------------------------------- edges

function InsertEdge(props: EdgeProps<InsertFlowEdge>) {
  const { actions, readOnly } = useBuilderContext();
  const [path, labelX, labelY] = getSmoothStepPath({ ...props, borderRadius: 10 });
  const slot = props.data?.slot;
  const drop = useDropOn(slot);
  return (
    <>
      <BaseEdge id={props.id} path={path} style={{ stroke: "var(--border-strong)", strokeWidth: 2 }} />
      <EdgeLabelRenderer>
        {props.data?.label && props.data.tone && (
          <div
            className="nodrag nopan pointer-events-none absolute"
            style={{
              transform: `translate(-50%, -100%) translate(${String(props.targetX)}px, ${String(props.targetY - 6)}px)`,
            }}
          >
            <BranchLabel tone={props.data.tone}>{props.data.label}</BranchLabel>
          </div>
        )}
        {slot && !readOnly && (
          <div
            className="nodrag nopan absolute"
            style={{
              transform: `translate(-50%, -50%) translate(${String(labelX)}px, ${String(labelY)}px)`,
              pointerEvents: "all",
            }}
          >
            <InsertButton
              onInsert={() => {
                actions.add(slot, "Step");
              }}
              onDropItem={drop}
            />
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
}

const NODE_TYPES_MAP = {
  step: StepView,
  container: ContainerView,
  terminal: TerminalView,
  placeholder: PlaceholderView,
};
const EDGE_TYPES_MAP = { insert: InsertEdge };

// ---------------------------------------------------------------- the canvas

export type CanvasProps = {
  config: Config | undefined;
  inputLabel: string;
  statuses: ReadonlyMap<string, WorkflowNodeStatus>;
  problems: ReadonlyMap<string, number>;
  stats: ReadonlyMap<string, number>;
  offsets: Offsets;
  onOffsets: (offsets: Offsets) => void;
  onOpenInspector: () => void;
  /** Bumped by "Auto-layout": drop manual offsets and fit the view. */
  layoutVersion: number;
};

function problemsUnder(problems: ReadonlyMap<string, number>, path: string): number {
  return problems.get(path) ?? 0;
}

function toFlow(
  layout: Layout,
  config: Config | undefined,
  props: CanvasProps,
): { nodes: FlowNode[]; edges: InsertFlowEdge[] } {
  const nodes: FlowNode[] = layout.nodes.map((item: LayoutNode): FlowNode => {
    const offset = props.offsets[item.id];
    const position = { x: item.x + (offset?.x ?? 0), y: item.y + (offset?.y ?? 0) };
    const base = {
      id: item.id,
      position,
      ...(item.parent ? { parentId: item.parent, extent: "parent" as const } : {}),
      width: item.width,
      height: item.height,
    };
    if (item.kind === "terminal") {
      const start = item.id === START;
      return {
        ...base,
        type: "terminal",
        draggable: false,
        selectable: false,
        data: { label: start ? `Start · ${props.inputLabel}` : "End", start },
      };
    }
    if (item.kind === "placeholder") {
      return {
        ...base,
        type: "placeholder",
        draggable: false,
        selectable: false,
        data: { slot: item.slot ?? { parent: "", lane: "steps", index: 0 } },
      };
    }
    const node = nodeAt(config, item.id) ?? {};
    const shown = describeNode(node, props.stats.get(nodeName(node)));
    const data: CardData = {
      path: item.id,
      ...shown,
      status: props.statuses.get(nodeName(node)) ?? "idle",
      problems: problemsUnder(props.problems, item.id),
    };
    return item.kind === "container"
      ? { ...base, type: "container", data, selectable: false }
      : { ...base, type: "step", data, selectable: false };
  });
  const edges: InsertFlowEdge[] = layout.edges.map((item: LayoutEdge) => ({
    id: item.id,
    source: item.source,
    target: item.target,
    type: "insert",
    selectable: false,
    data: { slot: item.slot, label: item.label, tone: item.tone },
  }));
  return { nodes, edges };
}

/** The canvas. It needs a React Flow provider around it (the toolbar's zoom buttons share it). */
export function WorkflowCanvas(props: CanvasProps) {
  const { config, offsets, onOffsets, onOpenInspector, layoutVersion } = props;
  const { store, actions, readOnly } = useBuilderContext();
  const flow = useReactFlow();
  const [layout, setLayout] = useState<Layout | undefined>(undefined);
  const key = structureKey(config);
  const latestConfig = useRef(config);
  useEffect(() => {
    latestConfig.current = config;
  }, [config]);

  useEffect(() => {
    let cancelled = false;
    void layoutWorkflow(latestConfig.current).then((next) => {
      if (!cancelled) setLayout(next);
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  // Open on the start of the workflow (a long one doesn't fit): the start and the first steps, at most at 100 %.
  const opened = useRef(false);
  const fitStart = useCallback(
    (duration: number) => {
      const first = [
        START,
        ...rootSteps(latestConfig.current)
          .slice(0, 4)
          .map((_, index) => `steps[${String(index)}]`),
      ];
      void flow.fitView({ nodes: first.map((id) => ({ id })), maxZoom: 1, padding: 0.2, duration });
    },
    [flow],
  );
  useEffect(() => {
    if (!layout || opened.current) return;
    opened.current = true;
    requestAnimationFrame(() => {
      fitStart(0);
    });
  }, [layout, fitStart]);
  useEffect(() => {
    if (layoutVersion > 0) fitStart(200);
  }, [layoutVersion, fitStart]);

  const shown = useMemo(
    () => (layout ? toFlow(layout, config, props) : { nodes: [], edges: [] }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `props` fields listed individually
    [layout, config, props.statuses, props.problems, props.stats, props.offsets, props.inputLabel],
  );

  const selectAndShow = useCallback(
    (path: string | undefined) => {
      store.getState().select(path);
      if (!path) return;
      const internal = flow.getInternalNode(path);
      if (!internal) return;
      const { x, y } = internal.internals.positionAbsolute;
      const width = internal.measured.width ?? 0;
      const height = internal.measured.height ?? 0;
      void flow.setCenter(x + width / 2, y + height / 2, { zoom: flow.getZoom(), duration: 150 });
      requestAnimationFrame(() => {
        document.querySelector<HTMLElement>(`[data-path="${CSS.escape(path)}"] button`)?.focus();
      });
    },
    [flow, store],
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const selected = store.getState().selected;
    const command = event.metaKey || event.ctrlKey;
    const arrows: Record<string, "up" | "down" | "left" | "right"> = {
      ArrowUp: "up",
      ArrowDown: "down",
      ArrowLeft: "left",
      ArrowRight: "right",
    };
    const direction = arrows[event.key];
    if (direction) {
      event.preventDefault();
      selectAndShow(neighbour(config, selected, direction));
      return;
    }
    if (event.key === "Enter" && selected) {
      event.preventDefault();
      onOpenInspector();
      return;
    }
    if ((event.key === "Delete" || event.key === "Backspace") && selected && !readOnly) {
      event.preventDefault();
      actions.remove(selected);
      return;
    }
    if (command && event.key.toLowerCase() === "c" && selected) {
      event.preventDefault();
      actions.copy(selected);
      return;
    }
    if (command && event.key.toLowerCase() === "v") {
      event.preventDefault();
      const place = selected ? parentOf(selected) : undefined;
      actions.paste(
        place
          ? { parent: place.parent, lane: place.lane, index: place.index + 1 }
          : { parent: "", lane: "steps", index: rootSteps(config).length },
      );
      return;
    }
    if (command && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) actions.redo();
      else actions.undo();
      return;
    }
    if (command && event.key.toLowerCase() === "y") {
      event.preventDefault();
      actions.redo();
    }
  };

  return (
    // The canvas takes keyboard commands (arrows, Enter, Delete, copy and paste, undo), so it is focusable.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="application"
      aria-label="Workflow canvas"
      aria-roledescription="workflow canvas"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- see above
      tabIndex={0}
      className="relative h-full min-h-0 w-full outline-none focus-visible:ring-1 focus-visible:ring-accent/40"
      onKeyDown={onKeyDown}
    >
      <ReactFlow<FlowNode, InsertFlowEdge>
        nodes={shown.nodes}
        edges={shown.edges}
        nodeTypes={NODE_TYPES_MAP}
        edgeTypes={EDGE_TYPES_MAP}
        nodesConnectable={false}
        nodesDraggable={!readOnly}
        elementsSelectable={false}
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        onlyRenderVisibleElements
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        onNodeDragStop={(_, node) => {
          const placed = layout?.nodes.find((item) => item.id === node.id);
          if (!placed) return;
          onOffsets({
            ...offsets,
            [node.id]: { x: node.position.x - placed.x, y: node.position.y - placed.y },
          });
        }}
        onPaneClick={() => {
          store.getState().select(undefined);
        }}
      >
        <Background gap={20} size={1} color="var(--border)" />
      </ReactFlow>
      {shown.nodes.length === 0 && (
        <div
          role="status"
          className="absolute inset-0 flex items-center justify-center text-[12.5px] text-fg-muted"
        >
          Laying out the workflow…
        </div>
      )}
    </div>
  );
}

export { ReactFlowProvider as CanvasProvider, useReactFlow as useCanvas };
