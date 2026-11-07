// The workflow canvas: React Flow drawing the flow graph that layout.ts placed, left to right. The workflow's
// input, its components with their typed ports, groups holding their steps, Router choices and Condition branches
// leaving from their own ports, and the output; a "+" on every connection (click it, or drop a palette item or a
// step's grip on it) and drops on empty space append a step. Sticky notes, the port legend, zoom controls and a
// minimap sit over it, and the test run lights nodes and connections up as it goes.
//
// Every node moves freely, the workflow's input and output included; a step moved inside a group stays in it and
// the frame grows around it. Snapping to the grid is off until it's switched on. Dragging with the right mouse
// button draws a selection rectangle (Shift or Ctrl adds to the selection, as does Shift- or Ctrl-clicking a node);
// the picked nodes move together, and the selection bar aligns, distributes, snaps them to the grid or deletes them.
//
// Keyboard: arrows move between steps, Enter opens the inspector, Delete removes the selection (with undo),
// Ctrl+A picks every node, Escape lets go, Ctrl+C / Ctrl+V copy and paste a subtree, Ctrl+Z / Ctrl+Shift+Z undo
// and redo.
import type { Config } from "@agnostic/studio";
import { Button, NODE_COLORS, PortLegend, toast, tokens, type WorkflowNodeStatus } from "@agnostic/ui";
import {
  Background,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useStoreApi,
  useViewport,
  type NodeChange,
  type XYPosition,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlignCenterHorizontal,
  AlignCenterVertical,
  AlignEndHorizontal,
  AlignEndVertical,
  AlignHorizontalDistributeCenter,
  AlignStartHorizontal,
  AlignStartVertical,
  AlignVerticalDistributeCenter,
  Grid3x3,
  Lock,
  LockOpen,
  Magnet,
  Maximize,
  Minus,
  Plus,
  StickyNote,
  Trash2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import {
  CHILD_EXTENT,
  GRID,
  align,
  caught,
  distribute,
  fitGroups,
  rectBetween,
  toGrid,
  type Alignment,
  type Axis,
  type Box,
  type Moves,
} from "./arrange";
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
import { useBuilder } from "./history";
import { layoutGraph, type Layout } from "./layout";
import { NODE_VIEWS, type FlowNode } from "./nodes";
import { NOTE_PREFIX, newNote, type CanvasState, type Note, type Offsets } from "./notes";
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
  notes: Note[];
  onNotes: (notes: Note[]) => void;
  /** Moves of steps and notes together, as one change (moving a selection, aligning it). */
  onArrange: (next: Partial<CanvasState>) => void;
  onOpenInspector: () => void;
  /** Bumped by "Auto-layout": drop manual offsets and fit the view. */
  layoutVersion: number;
};

/** Whether snapping to the grid is on: the viewer's own preference, remembered in this browser. */
const SNAP_KEY = "agnostic.workflow-canvas.snap";

function readSnap(): boolean {
  try {
    return window.localStorage.getItem(SNAP_KEY) === "on";
  } catch {
    return false;
  }
}

function writeSnap(on: boolean) {
  try {
    window.localStorage.setItem(SNAP_KEY, on ? "on" : "off");
  } catch {
    // Without storage the choice lasts until the page closes.
  }
}

/** A step's id is its config path (`steps[0].choices[1]`); the input, output, drop zones and notes are not steps. */
function isStep(id: string): boolean {
  return id.includes("[") && !id.includes("::");
}

/** The ring around a picked input, output or note (steps show it on their own frame). */
const PICKED_RING = "rounded-card outline-2 outline-offset-4 outline-accent";

/** The smallest drag that draws a selection rectangle, in screen pixels. */
const MARQUEE_MIN = 4;

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
      ...(item.parent ? { parentId: item.parent, extent: CHILD_EXTENT } : {}),
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
  snap,
  onSnap,
  onAddNote,
  readOnly,
}: {
  locked: boolean;
  onLock: () => void;
  snap: boolean;
  onSnap: () => void;
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
      <Button
        variant="icon"
        size="28"
        aria-label="Snap to grid"
        title={snap ? "Snapping to the grid: on" : "Snapping to the grid: off (nodes move freely)"}
        aria-pressed={snap}
        className="aria-pressed:bg-segment-active aria-pressed:text-accent"
        onClick={onSnap}
      >
        <Magnet aria-hidden />
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

function BarButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button variant="icon" size="28" aria-label={label} title={label} disabled={disabled} onClick={onClick}>
      {children}
    </Button>
  );
}

const ALIGNMENTS: { value: Alignment; label: string; icon: ReactNode }[] = [
  { value: "left", label: "Align left", icon: <AlignStartVertical aria-hidden /> },
  { value: "center", label: "Align centres horizontally", icon: <AlignCenterVertical aria-hidden /> },
  { value: "right", label: "Align right", icon: <AlignEndVertical aria-hidden /> },
  { value: "top", label: "Align top", icon: <AlignStartHorizontal aria-hidden /> },
  { value: "middle", label: "Align middles vertically", icon: <AlignCenterHorizontal aria-hidden /> },
  { value: "bottom", label: "Align bottom", icon: <AlignEndHorizontal aria-hidden /> },
];

/** What can be done with the picked nodes: align, distribute, snap to the grid, delete, let go. */
function SelectionBar({
  count,
  movable,
  readOnly,
  onAlign,
  onDistribute,
  onGrid,
  onDelete,
  onClear,
}: {
  count: number;
  /** How many of them can move on their own (a step inside a picked group moves with it). */
  movable: number;
  readOnly: boolean;
  onAlign: (alignment: Alignment) => void;
  onDistribute: (axis: Axis) => void;
  onGrid: () => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  return (
    <div
      role="toolbar"
      aria-label="Selected nodes"
      className="flex items-center gap-0.5 rounded-segment border border-border bg-canvas/95 p-[3px] shadow-popover"
    >
      <span className="px-2 text-[12px] text-fg-secondary" aria-live="polite">
        {`${String(count)} selected`}
      </span>
      <span aria-hidden className="mx-0.5 h-4 w-px bg-border-input" />
      {ALIGNMENTS.map((item) => (
        <BarButton
          key={item.value}
          label={item.label}
          disabled={readOnly || movable < 2}
          onClick={() => {
            onAlign(item.value);
          }}
        >
          {item.icon}
        </BarButton>
      ))}
      <span aria-hidden className="mx-0.5 h-4 w-px bg-border-input" />
      <BarButton
        label="Distribute horizontally"
        disabled={readOnly || movable < 3}
        onClick={() => {
          onDistribute("horizontal");
        }}
      >
        <AlignHorizontalDistributeCenter aria-hidden />
      </BarButton>
      <BarButton
        label="Distribute vertically"
        disabled={readOnly || movable < 3}
        onClick={() => {
          onDistribute("vertical");
        }}
      >
        <AlignVerticalDistributeCenter aria-hidden />
      </BarButton>
      <BarButton label="Snap the selection to the grid" disabled={readOnly || movable < 1} onClick={onGrid}>
        <Grid3x3 aria-hidden />
      </BarButton>
      <span aria-hidden className="mx-0.5 h-4 w-px bg-border-input" />
      <BarButton label="Delete the selection" disabled={readOnly} onClick={onDelete}>
        <Trash2 aria-hidden />
      </BarButton>
      <BarButton label="Clear the selection" onClick={onClear}>
        <X aria-hidden />
      </BarButton>
    </div>
  );
}

/** The canvas. It needs a React Flow provider around it. */
export function WorkflowCanvas(props: CanvasProps) {
  const { config, offsets, onArrange, onOpenInspector, layoutVersion, notes, onNotes } = props;
  const { store, actions, readOnly } = useBuilderContext();
  const flow = useReactFlow();
  const flowStore = useStoreApi();
  const frame = useRef<HTMLDivElement>(null);
  const [layout, setLayout] = useState<{ key: string; layout: Layout } | undefined>(undefined);
  const [locked, setLocked] = useState(false);
  const [snap, setSnap] = useState(readSnap);
  const picked = useBuilder(store, (state) => state.picked);
  // Where the nodes being dragged are right now; saved as manual moves when the drag ends.
  const [live, setLive] = useState<Record<string, XYPosition>>({});
  // The selection rectangle, in the frame's own pixels.
  const [marquee, setMarquee] = useState<{ from: XYPosition; to: XYPosition } | undefined>(undefined);
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

  // The nodes as drawn: dragged ones where the pointer has them, picked ones marked (so they move together), and
  // group frames grown around their steps.
  const nodes = useMemo(() => {
    const pickedIds = new Set(picked);
    const placed = shown.nodes.map((node): FlowNode => {
      const position = live[node.id];
      const isPicked = pickedIds.has(node.id);
      if (!position && !isPicked) return node;
      const ring = isPicked && (node.type === "io" || node.type === "note") ? PICKED_RING : undefined;
      return { ...node, ...(position ? { position } : {}), selected: isPicked, className: ring } as FlowNode;
    });
    return fitGroups(placed);
  }, [shown.nodes, live, picked]);

  /** Save where nodes now are: steps (and the input and output) as moves off the layout, notes as they are. */
  const commit = useCallback(
    (moved: { id: string; position: XYPosition }[]) => {
      setLive({});
      if (moved.length === 0) return;
      const placed = new Map((layout?.layout.nodes ?? []).map((item) => [item.id, item]));
      const nextOffsets: Offsets = { ...offsets };
      const at = new Map(moved.map((item) => [item.id, item.position]));
      let notesMoved = false;
      for (const { id, position } of moved) {
        if (id.startsWith(NOTE_PREFIX)) {
          notesMoved = true;
          continue;
        }
        const origin = placed.get(id);
        if (origin)
          nextOffsets[id] = { x: Math.round(position.x - origin.x), y: Math.round(position.y - origin.y) };
      }
      const nextNotes = notesMoved
        ? notes.map((note) => {
            const position = at.get(note.id);
            return position ? { ...note, x: Math.round(position.x), y: Math.round(position.y) } : note;
          })
        : undefined;
      onArrange({ positions: nextOffsets, ...(nextNotes ? { notes: nextNotes } : {}) });
    },
    [layout, offsets, notes, onArrange],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) => {
      const moved: Record<string, XYPosition> = {};
      const selection = new Map<string, boolean>();
      for (const change of changes) {
        if (change.type === "position" && change.position) moved[change.id] = change.position;
        if (change.type === "select") selection.set(change.id, change.selected);
      }
      if (Object.keys(moved).length > 0) {
        setLive((current) => ({ ...current, ...moved }));
      }
      // Dragging a node outside the selection lets the selection go, as on a desktop.
      if (selection.size > 0) {
        const current = store.getState().picked;
        const kept = current.filter((id) => selection.get(id) !== false);
        const added = [...selection].filter(([id, on]) => on && !kept.includes(id)).map(([id]) => id);
        if (kept.length !== current.length || added.length > 0) store.getState().pick([...kept, ...added]);
      }
    },
    [store],
  );

  /** The picked nodes that move on their own (a node inside a picked group moves with the group), as boxes. */
  const pickedBoxes = useCallback((): Box[] => {
    const { nodeLookup } = flowStore.getState();
    const ids = new Set(store.getState().picked);
    const insidePicked = (id: string): boolean => {
      let parent = nodeLookup.get(id)?.parentId;
      while (parent) {
        if (ids.has(parent)) return true;
        parent = nodeLookup.get(parent)?.parentId;
      }
      return false;
    };
    return [...ids].flatMap((id) => {
      const node = nodeLookup.get(id);
      if (!node || insidePicked(id)) return [];
      const { x, y } = node.internals.positionAbsolute;
      return [
        {
          id,
          x,
          y,
          width: node.measured.width ?? node.width ?? 0,
          height: node.measured.height ?? node.height ?? 0,
        },
      ];
    });
  }, [flowStore, store]);

  /** Move the picked nodes by `moves` (canvas coordinates) and save it; a step stays inside its group. */
  const arrange = useCallback(
    (plan: (boxes: Box[]) => Moves) => {
      if (readOnly || locked) return;
      const { nodeLookup } = flowStore.getState();
      const moves = plan(pickedBoxes());
      const moved = [...moves].flatMap(([id, delta]) => {
        const node = nodeLookup.get(id);
        if (!node) return [];
        let position = { x: node.position.x + delta.x, y: node.position.y + delta.y };
        if (node.parentId) {
          position = {
            x: Math.max(position.x, CHILD_EXTENT[0][0]),
            y: Math.max(position.y, CHILD_EXTENT[0][1]),
          };
        }
        return [{ id, position }];
      });
      commit(moved);
    },
    [commit, flowStore, locked, pickedBoxes, readOnly],
  );

  const removePicked = useCallback(() => {
    if (readOnly) return;
    const ids = store.getState().picked;
    const steps = ids.filter(isStep);
    const noteIds = new Set(ids.filter((id) => id.startsWith(NOTE_PREFIX)));
    if (steps.length === 0 && noteIds.size === 0) {
      if (ids.length > 0) toast("The workflow's input and output stay: they can be moved, not removed.");
      return;
    }
    if (noteIds.size > 0) onNotes(notes.filter((note) => !noteIds.has(note.id)));
    if (steps.length > 0) actions.removeMany(steps);
    store.getState().pick([]);
  }, [actions, notes, onNotes, readOnly, store]);

  /** Keyboard focus back on the canvas once the focused node is gone, so the next key still reaches it. */
  const refocus = useCallback(() => {
    requestAnimationFrame(() => {
      if (!frame.current?.contains(document.activeElement)) frame.current?.focus({ preventScroll: true });
    });
  }, []);

  // ------------------------------------------------ the selection rectangle (right mouse button)
  const marqueeStart = useRef<{ from: XYPosition; additive: boolean } | undefined>(undefined);
  const onPointerDownCapture = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 2 || !frame.current) return;
    const target = event.target as Element;
    if (!target.closest(".react-flow__pane")) return;
    // It starts on empty canvas or inside a group frame, not on a step, a note or the controls.
    if (
      target.closest(
        ".react-flow__node-component, .react-flow__node-io, .react-flow__node-note, .react-flow__panel, button, textarea, input",
      )
    ) {
      return;
    }
    event.preventDefault();
    const box = frame.current.getBoundingClientRect();
    const from = { x: event.clientX - box.left, y: event.clientY - box.top };
    marqueeStart.current = { from, additive: event.shiftKey || event.ctrlKey || event.metaKey };
    const move = (moveEvent: PointerEvent) => {
      const to = { x: moveEvent.clientX - box.left, y: moveEvent.clientY - box.top };
      if (Math.abs(to.x - from.x) < MARQUEE_MIN && Math.abs(to.y - from.y) < MARQUEE_MIN) return;
      setMarquee({ from, to });
    };
    const up = (upEvent: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const start = marqueeStart.current;
      marqueeStart.current = undefined;
      setMarquee(undefined);
      const to = { x: upEvent.clientX - box.left, y: upEvent.clientY - box.top };
      if (!start || (Math.abs(to.x - from.x) < MARQUEE_MIN && Math.abs(to.y - from.y) < MARQUEE_MIN)) return;
      const rect = rectBetween(
        flow.screenToFlowPosition({ x: from.x + box.left, y: from.y + box.top }),
        flow.screenToFlowPosition({ x: upEvent.clientX, y: upEvent.clientY }),
      );
      const { nodeLookup } = flowStore.getState();
      const hit: string[] = [];
      for (const [id, node] of nodeLookup) {
        if (node.type === "placeholder" || node.hidden) continue;
        const { x, y } = node.internals.positionAbsolute;
        const width = node.measured.width ?? node.width ?? 0;
        const height = node.measured.height ?? node.height ?? 0;
        // A group is picked when the rectangle holds all of it; anything else when the rectangle touches it.
        if (caught({ id, x, y, width, height }, rect, node.type === "frame")) hit.push(id);
      }
      const state = store.getState();
      if (start.additive) {
        const base = state.picked.length === 0 && state.selected ? [state.selected] : state.picked;
        state.pick([...new Set([...base, ...hit])]);
        return;
      }
      state.pick(hit);
      const steps = hit.filter(isStep);
      state.select(steps.length === 1 && hit.length === 1 ? steps[0] : undefined);
      frame.current?.focus({ preventScroll: true });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const selectAndShow = useCallback(
    (path: string | undefined) => {
      store.getState().pick([]);
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
    if ((event.key === "Delete" || event.key === "Backspace") && !readOnly) {
      if (store.getState().picked.length > 0) {
        event.preventDefault();
        removePicked();
        refocus();
        return;
      }
      if (selected) {
        event.preventDefault();
        actions.remove(selected);
        refocus();
        return;
      }
    }
    if (event.key === "Escape" && store.getState().picked.length > 0) {
      event.preventDefault();
      store.getState().pick([]);
      return;
    }
    if (command && event.key.toLowerCase() === "a") {
      event.preventDefault();
      store.getState().pick(shown.nodes.filter((node) => node.type !== "placeholder").map((node) => node.id));
      store.getState().select(undefined);
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
      onPointerDownCapture={onPointerDownCapture}
      onContextMenu={(event) => {
        // The right button draws the selection rectangle on the canvas; notes keep their own menu.
        const target = event.target as Element;
        if (target.closest(".react-flow__pane") && !target.closest("textarea, input")) event.preventDefault();
      }}
    >
      <ReactFlow<FlowNode, FlowEdgeType>
        nodes={nodes}
        edges={shown.edges}
        nodeTypes={NODE_VIEWS}
        edgeTypes={EDGE_VIEWS}
        onNodesChange={onNodesChange}
        nodesConnectable={false}
        nodesDraggable={!readOnly && !locked}
        elementsSelectable={false}
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        // The left and middle buttons pan; the right one is for the selection rectangle.
        panOnDrag={[0, 1]}
        snapToGrid={snap}
        snapGrid={[GRID, GRID]}
        onlyRenderVisibleElements
        minZoom={0.15}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        onNodeDragStop={(_, __, dragged) => {
          commit(dragged.map((node) => ({ id: node.id, position: node.position })));
        }}
        onNodeClick={(event, node) => {
          if (node.type === "placeholder") return;
          const state = store.getState();
          if (event.shiftKey || event.ctrlKey || event.metaKey) {
            // Shift- or Ctrl-click adds a node to the selection, or takes it out.
            const base = state.picked.length === 0 && state.selected ? [state.selected] : state.picked;
            const without = base.filter((id) => id !== node.id);
            state.pick(without.length === base.length ? [...base, node.id] : without);
            return;
          }
          state.pick([]);
          // A click anywhere on a step selects it; its buttons and fields do what they do.
          const target = event.target as Element;
          if (isStep(node.id) && !target.closest("button, a, input, textarea, [role=button]")) {
            state.select(node.id);
          }
        }}
        onPaneClick={() => {
          store.getState().select(undefined);
          store.getState().pick([]);
        }}
      >
        <Background
          gap={GRID}
          size={snap ? 1.6 : 1.2}
          color={snap ? "var(--fg-faint)" : "var(--border-strong)"}
        />
        {picked.length > 0 && (
          <Panel position="top-center" className="!mt-3">
            <SelectionBar
              count={picked.length}
              movable={picked.length > 0 ? pickedBoxes().length : 0}
              readOnly={readOnly || locked}
              onAlign={(alignment) => {
                arrange((boxes) => align(boxes, alignment));
              }}
              onDistribute={(axis) => {
                arrange((boxes) => distribute(boxes, axis));
              }}
              onGrid={() => {
                arrange((boxes) => toGrid(boxes));
              }}
              onDelete={() => {
                removePicked();
                refocus();
              }}
              onClear={() => {
                store.getState().pick([]);
              }}
            />
          </Panel>
        )}
        <Panel position="bottom-left" className="!m-3 flex flex-col items-start gap-2">
          <PortLegend types={legend} />
          <CanvasControls
            locked={locked}
            onLock={() => {
              setLocked((current) => !current);
            }}
            snap={snap}
            onSnap={() => {
              setSnap((current) => {
                writeSnap(!current);
                return !current;
              });
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
      {marquee && (
        <div
          aria-hidden
          className="pointer-events-none absolute z-20 rounded-[3px] border border-accent bg-accent/10"
          style={{
            left: Math.min(marquee.from.x, marquee.to.x),
            top: Math.min(marquee.from.y, marquee.to.y),
            width: Math.abs(marquee.to.x - marquee.from.x),
            height: Math.abs(marquee.to.y - marquee.from.y),
          }}
        />
      )}
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
