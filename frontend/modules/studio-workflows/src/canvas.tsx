// The workflow canvas: React Flow drawing the flow graph that layout.ts placed, left to right. The workflow's
// input, its components with their typed ports, groups holding their steps, Router choices and Condition branches
// leaving from their own ports, and the output; a "+" on every connection (click it, or drop a palette item or a
// step's grip on it) and drops on empty space append a step. Sticky notes, the port legend, zoom controls and a
// minimap sit over it, and the test run lights nodes and connections up as it goes. Keyboard: arrows move between
// steps, Enter opens the inspector, Delete removes (with undo), Ctrl+C / Ctrl+V copy and paste a subtree,
// Ctrl+Z / Ctrl+Shift+Z undo and redo.
import type { Config } from "@agnostic/studio";
import { Button, NODE_COLORS, PortLegend, tokens, type WorkflowNodeStatus } from "@agnostic/ui";
import {
  Background,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useStoreApi,
  useViewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Lock, LockOpen, Maximize, Minus, Plus, StickyNote } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from "react";

import { DRAG_TYPE, readDragItem, useBuilderContext } from "./context";
import { EDGE_VIEWS, type FlowEdgeType } from "./edges";
import {
  END,
  START,
  buildFlowGraph,
  describeNode,
  groupLabel,
  layoutKey,
  portTypesOf,
  type DetailsLookup,
  type FlowGraph,
} from "./graph";
import { layoutGraph, type Layout } from "./layout";
import { NODE_VIEWS, type FlowNode } from "./nodes";
import { NOTE_PREFIX, newNote, type Note, type Offsets } from "./notes";
import { seconds, type StepResult } from "./run-test";
import { executorOf, flatten, neighbour, nodeAt, nodeName, parentOf, rootSteps } from "./tree";

/** The component steps the test run has running, in reading order (containers don't count). */
function flattenRunning(config: Config | undefined, results: ReadonlyMap<string, StepResult>): string[] {
  return flatten(config)
    .filter((item) => item.type === "Step" && results.get(nodeName(item.node))?.status === "running")
    .map((item) => item.path);
}

export type { Offsets } from "./notes";

/** The lowest zoom at which the whole workflow is shown on open; below it the view starts on the first steps. */
const READABLE_ZOOM = 0.6;

export type CanvasProps = {
  config: Config | undefined;
  inputLabel: string;
  results: ReadonlyMap<string, StepResult>;
  problems: ReadonlyMap<string, number>;
  stats: ReadonlyMap<string, number>;
  details: DetailsLookup;
  offsets: Offsets;
  onOffsets: (offsets: Offsets) => void;
  notes: Note[];
  onNotes: (notes: Note[]) => void;
  onOpenInspector: () => void;
  /** Bumped by "Auto-layout": drop manual offsets and fit the view. */
  layoutVersion: number;
};

/** A token's value, for the minimap (SVG fills don't read CSS variables everywhere). */
function resolve(color: string): string {
  const name = /var\((--[\w-]+)\)/.exec(color)?.[1];
  return (name && tokens.allColors[name]) ?? color;
}

function statusOf(results: ReadonlyMap<string, StepResult>, name: string): WorkflowNodeStatus {
  return results.get(name)?.status ?? "idle";
}

function toFlow(
  graph: FlowGraph,
  layout: Layout,
  config: Config | undefined,
  props: CanvasProps,
): { nodes: FlowNode[]; edges: FlowEdgeType[] } {
  const connected = new Map<string, string[]>();
  for (const edge of graph.edges) {
    connected.set(edge.source, [...(connected.get(edge.source) ?? []), edge.sourceHandle]);
    connected.set(edge.target, [...(connected.get(edge.target) ?? []), edge.targetHandle]);
  }
  const byId = new Map(graph.nodes.map((node) => [node.id, node]));
  const statusById = new Map<string, WorkflowNodeStatus>();
  const nodes: FlowNode[] = layout.nodes.flatMap((item): FlowNode[] => {
    const graphNode = byId.get(item.id);
    if (!graphNode) return [];
    const offset = props.offsets[item.id];
    const base = {
      id: item.id,
      position: { x: item.x + (offset?.x ?? 0), y: item.y + (offset?.y ?? 0) },
      ...(item.parent ? { parentId: item.parent, extent: "parent" as const } : {}),
      width: item.width,
      height: item.height,
      selectable: false,
    };
    if (graphNode.kind === "input" || graphNode.kind === "output") {
      const input = graphNode.kind === "input";
      return [
        {
          ...base,
          type: "io",
          draggable: false,
          data: {
            kind: graphNode.kind,
            title: input ? "Workflow input" : "Workflow output",
            description: input ? `Start · ${props.inputLabel}` : "The last step's response",
            connected: (connected.get(item.id) ?? []).length > 0,
          },
        },
      ];
    }
    if (graphNode.kind === "placeholder") {
      const slot = graphNode.slot ?? { parent: "", lane: "steps", index: 0 };
      return [
        {
          ...base,
          type: "placeholder",
          draggable: false,
          data: { slot, label: slot.lane === "choices" ? "Add a choice here" : "Add a step here" },
        },
      ];
    }
    const node = nodeAt(config, item.id) ?? {};
    const name = nodeName(node);
    const result = props.results.get(name);
    const status = statusOf(props.results, name);
    statusById.set(item.id, status);
    const shown = describeNode(node, props.stats.get(name));
    const problems = props.problems.get(item.id) ?? 0;
    if (graphNode.kind === "group") {
      return [
        {
          ...base,
          type: "frame",
          data: {
            path: item.id,
            type: graphNode.type ?? "Steps",
            title: name,
            label: groupLabel(node),
            footer: shown.footer,
            meta: shown.meta,
            status,
            problems,
            connected: connected.get(item.id) ?? [],
          },
        },
      ];
    }
    return [
      {
        ...base,
        type: "component",
        data: {
          path: item.id,
          type: graphNode.type ?? "Step",
          executor: executorOf(node)?.kind,
          title: name,
          rows: graphNode.rows,
          chip: shown.chip,
          meta: shown.meta,
          status,
          time: result?.ms !== undefined ? seconds(result.ms) : undefined,
          problems,
          connected: connected.get(item.id) ?? [],
          result,
        },
      },
    ];
  });
  const ran = (id: string) => {
    if (id === START) return props.results.size > 0;
    const status = statusById.get(id);
    return status === "done" || status === "running" || status === "paused";
  };
  const edges: FlowEdgeType[] = graph.edges.map((edge) => {
    const running = statusById.get(edge.target) === "running";
    return {
      id: edge.id,
      source: edge.source,
      sourceHandle: edge.sourceHandle,
      target: edge.target,
      targetHandle: edge.targetHandle,
      type: "flow",
      selectable: false,
      animated: running,
      data: { port: edge.port, slot: edge.slot, lit: ran(edge.source) && (running || ran(edge.target)) },
    };
  });
  const notes: FlowNode[] = props.notes.map((note) => ({
    id: note.id,
    type: "note",
    position: { x: note.x, y: note.y },
    width: note.width,
    // Until it's measured, so it counts as on screen right away.
    initialHeight: 96,
    selectable: false,
    zIndex: 10,
    data: {
      note,
      onChange: (next: Note) => {
        props.onNotes(props.notes.map((item) => (item.id === next.id ? next : item)));
      },
      onDelete: (id: string) => {
        props.onNotes(props.notes.filter((item) => item.id !== id));
      },
    },
  }));
  return { nodes: [...nodes, ...notes], edges };
}

function CanvasControls({
  locked,
  onLock,
  onAddNote,
  readOnly,
}: {
  locked: boolean;
  onLock: () => void;
  onAddNote: () => void;
  readOnly: boolean;
}) {
  const flow = useReactFlow();
  const { zoom } = useViewport();
  return (
    <div
      role="group"
      aria-label="Canvas controls"
      className="flex items-center gap-0.5 rounded-segment border border-border bg-canvas/90 p-[3px]"
    >
      <Button
        variant="icon"
        size="28"
        aria-label="Zoom out"
        onClick={() => void flow.zoomOut({ duration: 150 })}
      >
        <Minus aria-hidden />
      </Button>
      <span className="w-11 text-center font-mono text-[11.5px] text-fg" aria-live="polite">
        {`${String(Math.round(zoom * 100))}%`}
      </span>
      <Button
        variant="icon"
        size="28"
        aria-label="Zoom in"
        onClick={() => void flow.zoomIn({ duration: 150 })}
      >
        <Plus aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="28"
        aria-label="Zoom to fit"
        onClick={() => void flow.fitView({ padding: 0.12, duration: 200, maxZoom: 1 })}
      >
        <Maximize aria-hidden />
        Fit
      </Button>
      <Button variant="ghost" size="28" onClick={() => void flow.zoomTo(1, { duration: 150 })}>
        100%
      </Button>
      <span aria-hidden className="mx-0.5 h-4 w-px bg-border-input" />
      <Button
        variant="icon"
        size="28"
        aria-label={locked ? "Unlock the canvas" : "Lock the canvas"}
        aria-pressed={locked}
        onClick={onLock}
      >
        {locked ? <Lock aria-hidden /> : <LockOpen aria-hidden />}
      </Button>
      {!readOnly && (
        <Button variant="ghost" size="28" onClick={onAddNote}>
          <StickyNote aria-hidden className="text-warning" />
          Add note
        </Button>
      )}
    </div>
  );
}

/** The canvas. It needs a React Flow provider around it. */
export function WorkflowCanvas(props: CanvasProps) {
  const { config, offsets, onOffsets, onOpenInspector, layoutVersion, notes, onNotes } = props;
  const { store, actions, readOnly } = useBuilderContext();
  const flow = useReactFlow();
  const flowStore = useStoreApi();
  const frame = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<{ key: string; layout: Layout } | undefined>(undefined);
  const [locked, setLocked] = useState(false);
  const graph = useMemo(
    () => buildFlowGraph(config, { inputLabel: props.inputLabel, details: props.details }),
    [config, props.inputLabel, props.details],
  );
  const key = layoutKey(graph);
  const latestGraph = useRef(graph);
  useEffect(() => {
    latestGraph.current = graph;
  }, [graph]);

  useEffect(() => {
    let cancelled = false;
    void layoutGraph(latestGraph.current).then((next) => {
      if (!cancelled) setLayout({ key, layout: next });
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  // Show the whole workflow when it stays readable; a long one opens on its input and first steps instead.
  const opened = useRef(false);
  const fitStart = useCallback(
    (duration: number) => {
      const { width, height } = flowStore.getState();
      const whole = flow.getNodesBounds(flow.getNodes().filter((node) => !node.id.startsWith(NOTE_PREFIX)));
      const zoom = Math.min(width / (whole.width * 1.1), height / (whole.height * 1.1));
      if (zoom >= READABLE_ZOOM) {
        void flow.fitView({ maxZoom: 1, padding: 0.06, duration });
        return;
      }
      const first = [
        START,
        ...rootSteps(config)
          .slice(0, 2)
          .map((_, index) => `steps[${String(index)}]`),
      ];
      void flow.fitView({
        nodes: first.map((id) => ({ id })),
        minZoom: READABLE_ZOOM,
        maxZoom: 0.9,
        padding: 0.12,
        duration,
      });
    },
    [flow, flowStore, config],
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only "Auto-layout" refits
  }, [layoutVersion]);

  // Follow the test run: each step that starts running is brought into view.
  const runningPath = useMemo(() => {
    const running = flattenRunning(config, props.results);
    return running.at(-1);
  }, [config, props.results]);
  useEffect(() => {
    if (!runningPath) return;
    const internal = flow.getInternalNode(runningPath);
    if (!internal) return;
    const { x, y } = internal.internals.positionAbsolute;
    const width = internal.measured.width ?? 0;
    const height = internal.measured.height ?? 0;
    void flow.setCenter(x + width / 2, y + height / 2, { zoom: flow.getZoom(), duration: 450 });
  }, [runningPath, flow]);

  // While a new layout is on its way the previous one keeps the nodes it still has in place.
  const shown = useMemo(
    () => (layout ? toFlow(graph, layout.layout, config, props) : { nodes: [], edges: [] }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `props` fields listed individually
    [
      layout,
      graph,
      config,
      props.results,
      props.problems,
      props.stats,
      props.offsets,
      props.notes,
      props.inputLabel,
    ],
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
        document
          .querySelector<HTMLElement>(`[data-path="${CSS.escape(path)}"] button[aria-pressed]`)
          ?.focus();
      });
    },
    [flow, store],
  );

  const addNote = () => {
    const box = frame.current?.getBoundingClientRect();
    const center = flow.screenToFlowPosition({
      x: (box?.left ?? 0) + (box?.width ?? 0) / 2 - 120,
      y: (box?.top ?? 0) + (box?.height ?? 0) / 2 - 40,
    });
    onNotes([...notes, newNote(Math.round(center.x), Math.round(center.y))]);
  };

  const onDropAtEnd = (event: DragEvent<HTMLDivElement>) => {
    const item = readDragItem(event.dataTransfer);
    if (!item || readOnly) return;
    event.preventDefault();
    actions.drop({ parent: "", lane: "steps", index: rootSteps(config).length }, item);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Typing in a note is just typing.
    if (event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement) return;
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

  const legend = portTypesOf(graph);
  return (
    // The canvas takes keyboard commands (arrows, Enter, Delete, copy and paste, undo), so it is focusable.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      ref={frame}
      role="application"
      aria-label="Workflow canvas"
      aria-roledescription="workflow canvas"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- see above
      tabIndex={0}
      className="relative h-full min-h-0 w-full outline-none focus-visible:ring-1 focus-visible:ring-accent/40"
      onKeyDown={onKeyDown}
      onDragOver={(event) => {
        if (!readOnly && event.dataTransfer.types.includes(DRAG_TYPE)) event.preventDefault();
      }}
      onDrop={onDropAtEnd}
    >
      <ReactFlow<FlowNode, FlowEdgeType>
        nodes={shown.nodes}
        edges={shown.edges}
        nodeTypes={NODE_VIEWS}
        edgeTypes={EDGE_VIEWS}
        nodesConnectable={false}
        nodesDraggable={!readOnly && !locked}
        elementsSelectable={false}
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        onlyRenderVisibleElements
        minZoom={0.15}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        onNodeDragStop={(_, node) => {
          if (node.id.startsWith(NOTE_PREFIX)) {
            onNotes(
              notes.map((item) =>
                item.id === node.id
                  ? { ...item, x: Math.round(node.position.x), y: Math.round(node.position.y) }
                  : item,
              ),
            );
            return;
          }
          const placed = layout?.layout.nodes.find((item) => item.id === node.id);
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
        <Background gap={22} size={1.2} color="var(--border-strong)" />
        <Panel position="bottom-left" className="!m-3 flex flex-col items-start gap-2">
          <PortLegend types={legend} />
          <CanvasControls
            locked={locked}
            onLock={() => {
              setLocked((current) => !current);
            }}
            onAddNote={addNote}
            readOnly={readOnly}
          />
        </Panel>
        <MiniMap<FlowNode>
          position="bottom-right"
          ariaLabel="Workflow overview"
          pannable
          zoomable
          className="!m-3 overflow-hidden rounded-button border border-border-input"
          style={{ width: 196, height: 120 }}
          bgColor={resolve("var(--bg-canvas)")}
          maskColor="rgb(11 12 14 / 0.72)"
          maskStrokeColor={resolve("var(--accent)")}
          maskStrokeWidth={2}
          nodeBorderRadius={3}
          nodeColor={(node) => {
            if (node.type === "frame") return "transparent";
            if (node.type === "note") return resolve("var(--note-border)");
            if (node.type === "component") return resolve(NODE_COLORS[node.data.type]);
            return resolve("var(--fg-muted)");
          }}
          nodeStrokeColor={(node) =>
            node.type === "frame" ? resolve(NODE_COLORS[node.data.type]) : "transparent"
          }
          nodeStrokeWidth={6}
        />
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

export { END, START };
export { ReactFlowProvider as CanvasProvider, useReactFlow as useCanvas };
