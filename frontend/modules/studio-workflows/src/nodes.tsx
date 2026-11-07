// The canvas's node views: a component (Step, Router, Condition) with its ports as connection handles, a group
// frame (Steps, Loop, Parallel) holding its steps, the workflow's input and output, the drop zone of an empty lane,
// and sticky notes. The look comes from `@agnostic/ui`; this file wires it to React Flow and the builder.
import {
  FlowIoNode,
  FlowNodeFrame,
  GroupFrame,
  InsertButton,
  StickyNote,
  portDotStyle,
  type ExecutorKind,
  type FlowRow,
  type PortType,
  type WorkflowNodeStatus,
} from "@agnostic/ui";
import { Handle, NodeToolbar, Position, type Node, type NodeProps } from "@xyflow/react";
import { Eye, Plus, X } from "lucide-react";
import { memo, useCallback, useState, type CSSProperties, type DragEvent } from "react";

import { readDragItem, useBuilderContext } from "./context";
import { useBuilder } from "./history";
import type { Note } from "./notes";
import type { StepResult } from "./run-test";
import { children, nodeAt, type NodeType, type Slot } from "./tree";

export type ComponentData = {
  path: string;
  type: NodeType;
  executor?: ExecutorKind | undefined;
  title: string;
  rows: FlowRow[];
  chip?: string | undefined;
  meta?: string | undefined;
  status: WorkflowNodeStatus;
  time?: string | undefined;
  problems: number;
  /** Handles with a connection: their dots are filled. */
  connected: string[];
  result?: StepResult | undefined;
};
export type GroupData = {
  path: string;
  type: NodeType;
  title: string;
  label: string;
  footer?: string | undefined;
  meta?: string | undefined;
  status: WorkflowNodeStatus;
  problems: number;
  connected: string[];
};
export type IoData = { kind: "input" | "output"; title: string; description: string; connected: boolean };
export type PlaceholderData = { slot: Slot; label: string };
export type NoteData = { note: Note; onChange: (note: Note) => void; onDelete: (id: string) => void };

export type ComponentFlowNode = Node<ComponentData, "component">;
export type GroupFlowNode = Node<GroupData, "frame">;
export type IoFlowNode = Node<IoData, "io">;
export type PlaceholderFlowNode = Node<PlaceholderData, "placeholder">;
export type NoteFlowNode = Node<NoteData, "note">;
export type FlowNode = ComponentFlowNode | GroupFlowNode | IoFlowNode | PlaceholderFlowNode | NoteFlowNode;

function Port({
  id,
  side,
  type,
  connected,
  style,
}: {
  id: string;
  side: "in" | "out";
  type: PortType;
  connected: boolean;
  style?: CSSProperties;
}) {
  return (
    <Handle
      id={id}
      type={side === "in" ? "target" : "source"}
      position={side === "in" ? Position.Left : Position.Right}
      isConnectable={false}
      style={{ ...portDotStyle(type, connected), ...style }}
    />
  );
}

/** A quiet handle where a drop zone meets its connections. */
const HIDDEN = { width: 1, height: 1, minWidth: 1, minHeight: 1, border: 0, background: "transparent" };

function OutputPopover({
  title,
  result,
  onClose,
}: {
  title: string;
  result: StepResult;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-label={`Output of ${title}`}
      className="nodrag nowheel w-[300px] rounded-tile border border-border-dashed bg-surface-raised shadow-popover"
    >
      <div className="flex items-center gap-2 border-b border-border py-1.5 pr-1.5 pl-3">
        <span className="flex-1 truncate text-[12px] font-semibold">{`Output · ${title}`}</span>
        <button
          type="button"
          aria-label="Close output"
          onClick={onClose}
          className="inline-flex size-6 cursor-pointer items-center justify-center rounded-control border-0 bg-transparent text-fg-secondary hover:bg-surface-hover focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none"
        >
          <X aria-hidden className="size-3.5" />
        </button>
      </div>
      {result.error ? (
        <p className="m-0 px-3 py-2.5 font-mono text-[11.5px] text-danger">{result.error}</p>
      ) : (
        <pre className="m-0 max-h-56 overflow-auto px-3 py-2.5 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-fg-prose">
          {result.content || "No output yet."}
        </pre>
      )}
      {result.tools.length > 0 && (
        <p className="m-0 border-t border-border px-3 py-1.5 font-mono text-[11px] text-fg-muted">
          {`tools · ${result.tools.join(", ")}`}
        </p>
      )}
    </div>
  );
}

export const ComponentView = memo(function ComponentView({ data }: NodeProps<ComponentFlowNode>) {
  const { store } = useBuilderContext();
  const selected = useBuilder(
    store,
    (state) => state.selected === data.path || state.picked.includes(data.path),
  );
  const [inspecting, setInspecting] = useState(false);
  const result = data.result;
  const inspectable = Boolean(result && (result.content || result.error));
  const renderPort = useCallback(
    (row: Extract<FlowRow, { kind: "in" | "out" }>) => (
      <Port id={row.id} side={row.kind} type={row.port} connected={data.connected.includes(row.id)} />
    ),
    [data.connected],
  );
  return (
    <div className="group/node relative" data-path={data.path}>
      <FlowNodeFrame
        type={data.type}
        executor={data.executor}
        title={data.title}
        rows={data.rows}
        chip={data.chip}
        meta={data.meta}
        status={data.status}
        time={data.time}
        problems={data.problems}
        selected={selected}
        onSelect={() => {
          store.getState().select(data.path);
        }}
        renderPort={renderPort}
        actions={
          inspectable ? (
            <button
              type="button"
              aria-label={`Inspect the output of ${data.title}`}
              aria-pressed={inspecting}
              onClick={() => {
                setInspecting((open) => !open);
              }}
              className="nodrag inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-[6px] border border-border-strong bg-transparent text-fg-secondary hover:text-fg focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none aria-pressed:bg-segment-active"
            >
              <Eye aria-hidden className="size-3.5" />
            </button>
          ) : undefined
        }
      />
      {result && (
        <NodeToolbar
          isVisible={inspecting && inspectable}
          position={Position.Bottom}
          align="start"
          offset={8}
        >
          <OutputPopover
            title={data.title}
            result={result}
            onClose={() => {
              setInspecting(false);
            }}
          />
        </NodeToolbar>
      )}
    </div>
  );
});

export const GroupView = memo(function GroupView({ data, width, height }: NodeProps<GroupFlowNode>) {
  const { store, actions, readOnly, doc } = useBuilderContext();
  const selected = useBuilder(
    store,
    (state) => state.selected === data.path || state.picked.includes(data.path),
  );
  return (
    <div className="group/node relative" data-path={data.path}>
      <GroupFrame
        type={data.type}
        title={data.title}
        label={data.label}
        footer={data.footer}
        meta={data.meta}
        status={data.status}
        problems={data.problems}
        selected={selected}
        onSelect={() => {
          store.getState().select(data.path);
        }}
        width={width ?? 0}
        height={height ?? 0}
        inPort={<Port id="in" side="in" type="message" connected={data.connected.includes("in")} />}
        outPort={<Port id="out" side="out" type="message" connected={data.connected.includes("out")} />}
      >
        {!readOnly && (
          <button
            type="button"
            aria-label={`Add a step at the end of ${data.title || data.type}`}
            className="nodrag absolute right-2.5 bottom-2 inline-flex size-[22px] cursor-pointer items-center justify-center rounded-full border border-border bg-surface text-fg-secondary hover:border-accent hover:text-accent focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none"
            onClick={() => {
              const node = nodeAt(doc.config, data.path);
              actions.add(
                { parent: data.path, lane: "steps", index: children(node, "steps").length },
                "Step",
              );
            }}
          >
            <Plus aria-hidden className="size-3.5" />
          </button>
        )}
      </GroupFrame>
    </div>
  );
});

export const IoView = memo(function IoView({ data }: NodeProps<IoFlowNode>) {
  return (
    <FlowIoNode
      kind={data.kind}
      title={data.title}
      description={data.description}
      port={
        <Port
          id={data.kind === "input" ? "out" : "in"}
          side={data.kind === "input" ? "out" : "in"}
          type="message"
          connected={data.connected}
        />
      }
    />
  );
});

export function useDropOn(slot: Slot | undefined) {
  const { actions } = useBuilderContext();
  return useCallback(
    (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      // The canvas appends what's dropped on its empty space; a drop here is handled here.
      event.stopPropagation();
      const item = readDragItem(event.dataTransfer);
      if (item && slot) actions.drop(slot, item);
    },
    [actions, slot],
  );
}

export const PlaceholderView = memo(function PlaceholderView({
  data,
  width,
  height,
}: NodeProps<PlaceholderFlowNode>) {
  const { actions, readOnly } = useBuilderContext();
  const drop = useDropOn(data.slot);
  return (
    <div
      className="flex items-center justify-center gap-2 rounded-tile border border-dashed border-border-dashed bg-canvas/60 text-[12px] text-fg-muted"
      style={{ width, height }}
      onDragOver={(event) => {
        event.preventDefault();
      }}
      onDrop={drop}
    >
      <Handle id="in" type="target" position={Position.Left} isConnectable={false} style={HIDDEN} />
      <InsertButton
        label={data.label}
        disabled={readOnly}
        onInsert={() => {
          actions.add(data.slot, "Step");
        }}
        onDropItem={drop}
      />
      Drop a step here
      <Handle id="out" type="source" position={Position.Right} isConnectable={false} style={HIDDEN} />
    </div>
  );
});

export const NoteView = memo(function NoteView({ data }: NodeProps<NoteFlowNode>) {
  const { readOnly } = useBuilderContext();
  return (
    <StickyNote
      text={data.note.text}
      width={data.note.width}
      readOnly={readOnly}
      onChange={(text) => {
        data.onChange({ ...data.note, text });
      }}
      onDelete={() => {
        data.onDelete(data.note.id);
      }}
    />
  );
});

export const NODE_VIEWS = {
  component: ComponentView,
  // Not "group": React Flow styles a node of that type itself.
  frame: GroupView,
  io: IoView,
  placeholder: PlaceholderView,
  note: NoteView,
};
