// Workflow builder widgets, drawn the way flow editors such as Langflow draw components: a node with an icon header,
// a status badge and rows (a description, typed input and output ports, read-only fields, CEL previews), dashed
// group frames for Loop / Parallel / Steps, sticky notes, the port legend, branch labels, the "+" insert affordance
// and palette items. Presentational: the canvas maps the workflow tree to these props, does the layout and renders
// the ports' connection handles into the `port` slots.
import {
  AlertTriangle,
  Bot,
  Box,
  Check,
  CircleDashed,
  Code2,
  Columns3,
  Diamond,
  ListOrdered,
  LoaderCircle,
  Pause,
  Plus,
  Repeat,
  Split,
  Trash2,
  Users,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import { useId, type CSSProperties, type DragEvent, type ReactNode } from "react";

import { cn } from "../lib/cn";

export type WorkflowNodeType = "Step" | "Steps" | "Parallel" | "Condition" | "Loop" | "Router";
export type WorkflowNodeStatus = "idle" | "running" | "done" | "paused" | "failed" | "skipped";
export type ExecutorKind = "agent" | "team" | "workflow" | "function";

/** The colour of each primitive, as icon tiles, frames and palette tiles use it. */
export const NODE_COLORS: Record<WorkflowNodeType, string> = {
  Step: "var(--entity-agent)",
  Steps: "var(--entity-fn)",
  Parallel: "var(--entity-workflow)",
  Condition: "var(--node-condition)",
  Loop: "var(--node-loop)",
  Router: "var(--entity-team)",
};

export const NODE_ICONS: Record<WorkflowNodeType, LucideIcon> = {
  Step: Box,
  Steps: ListOrdered,
  Parallel: Columns3,
  Condition: Diamond,
  Loop: Repeat,
  Router: Split,
};

export const EXECUTOR_ICONS: Record<ExecutorKind, LucideIcon> = {
  agent: Bot,
  team: Users,
  workflow: Workflow,
  function: Code2,
};

export const EXECUTOR_COLORS: Record<ExecutorKind, string> = {
  agent: "var(--entity-agent)",
  team: "var(--entity-team)",
  workflow: "var(--entity-workflow)",
  function: "var(--entity-fn)",
};

export function tint(color: string, alpha: number): string {
  return `color-mix(in srgb, ${color} ${String(Math.round(alpha * 100))}%, transparent)`;
}

/** The icon tile of a primitive, or of the executor a Step runs. */
export function WorkflowGlyph({
  type,
  executor,
  size = 20,
}: {
  type: WorkflowNodeType;
  executor?: ExecutorKind | undefined;
  size?: number;
}) {
  const color = executor ? EXECUTOR_COLORS[executor] : NODE_COLORS[type];
  const Icon = executor ? EXECUTOR_ICONS[executor] : NODE_ICONS[type];
  return (
    <span
      aria-hidden
      data-slot="workflow-glyph"
      className="inline-flex shrink-0 items-center justify-center rounded-[7px]"
      style={{ width: size, height: size, color, backgroundColor: tint(color, 0.15) }}
    >
      <Icon className="shrink-0" style={{ width: Math.round(size * 0.6), height: Math.round(size * 0.6) }} />
    </span>
  );
}

// ---------------------------------------------------------------- ports

/** What travels along a connection: a step's message, structured data, or the branch a Router / Condition takes. */
export type PortType = "message" | "data" | "route";

export const PORT_TYPES: Record<PortType, { label: string; color: string }> = {
  message: { label: "Message", color: "var(--entity-agent)" },
  data: { label: "Data", color: "var(--entity-workflow)" },
  route: { label: "Route", color: "var(--accent)" },
};

/** The look of a port's dot; the canvas puts it on its connection handle. */
export function portDotStyle(type: PortType, connected: boolean): CSSProperties {
  const color = PORT_TYPES[type].color;
  return {
    width: 12,
    height: 12,
    minWidth: 12,
    minHeight: 12,
    borderRadius: 999,
    border: `2px solid ${color}`,
    background: connected ? color : "var(--surface-raised)",
  };
}

export function PortLegend({ types, className }: { types: readonly PortType[]; className?: string }) {
  if (types.length === 0) return null;
  return (
    <ul
      aria-label="Port types"
      className={cn(
        "m-0 flex list-none flex-wrap gap-2.5 rounded-button border border-border bg-canvas/90 px-2.5 py-1.5 text-[11px] text-fg-secondary",
        className,
      )}
    >
      {types.map((type) => (
        <li key={type} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-[9px] rounded-full"
            style={{ backgroundColor: PORT_TYPES[type].color }}
          />
          {PORT_TYPES[type].label}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- the component node

/** One row of a node. Port rows carry a handle in the `port` slot; the others are read-only previews. */
export type FlowRow =
  | { kind: "desc"; text: string }
  | { kind: "in" | "out"; id: string; label: string; port: PortType; note?: string | undefined }
  | { kind: "field"; label: string; value: string; mono?: boolean | undefined }
  | { kind: "area"; label: string; lines: readonly string[] }
  /** Small blocks in one line (an agent's tools); `tone` marks where each comes from. */
  | {
      kind: "chips";
      label: string;
      items: readonly { label: string; tone?: "org" | "team" | "custom" | undefined }[];
    }
  | { kind: "sep" };

/** Fixed row heights, so the layout knows a node's size before it renders. */
export const FLOW_ROW_HEIGHTS = {
  header: 44,
  desc: 28,
  in: 28,
  out: 28,
  field: 54,
  chips: 54,
  sep: 9,
  areaBase: 32,
  areaLine: 18,
  bottom: 8,
  border: 2,
} as const;

export const FLOW_NODE_WIDTH = 264;
/** A CEL preview shows at most this many lines on the node; the inspector has the rest. */
export const AREA_MAX_LINES = 4;

export function flowRowHeight(row: FlowRow): number {
  if (row.kind === "area") {
    return FLOW_ROW_HEIGHTS.areaBase + FLOW_ROW_HEIGHTS.areaLine * Math.min(row.lines.length, AREA_MAX_LINES);
  }
  return FLOW_ROW_HEIGHTS[row.kind];
}

export function flowNodeHeight(rows: readonly FlowRow[]): number {
  return (
    FLOW_ROW_HEIGHTS.border +
    FLOW_ROW_HEIGHTS.header +
    rows.reduce((sum, row) => sum + flowRowHeight(row), 0) +
    FLOW_ROW_HEIGHTS.bottom
  );
}

const STATUS_TEXT: Record<Exclude<WorkflowNodeStatus, "idle">, string> = {
  running: "running",
  done: "done",
  paused: "waiting for a person",
  failed: "failed",
  skipped: "skipped",
};

/** "✓ 1.1 s", "Running", "Waiting", "Failed", "Skipped", or the idle meta ("avg 1.1 s"). */
export function StatusBadge({
  status,
  time,
  meta,
}: {
  status: WorkflowNodeStatus;
  time?: string | undefined;
  meta?: string | undefined;
}) {
  const base = "inline-flex shrink-0 items-center gap-1 text-[11px]";
  switch (status) {
    case "done":
      return (
        <span aria-hidden className={cn(base, "font-mono text-accent")}>
          <Check className="size-3" />
          {time ?? "done"}
        </span>
      );
    case "running":
      return (
        <span aria-hidden className={cn(base, "text-info")}>
          <LoaderCircle className="size-3 animate-spin" />
          Running
        </span>
      );
    case "paused":
      return (
        <span aria-hidden className={cn(base, "text-warning")}>
          <Pause className="size-3" />
          Waiting
        </span>
      );
    case "failed":
      return (
        <span aria-hidden className={cn(base, "text-danger")}>
          <X className="size-3" />
          Failed
        </span>
      );
    case "skipped":
      return (
        <span aria-hidden className={cn(base, "text-fg-muted")}>
          <CircleDashed className="size-3" />
          Skipped
        </span>
      );
    case "idle":
      return meta ? (
        <span aria-hidden className={cn(base, "text-fg-muted")}>
          {meta}
        </span>
      ) : null;
  }
}

function Row({ row, port }: { row: FlowRow; port?: ReactNode }) {
  const style = { height: flowRowHeight(row) };
  switch (row.kind) {
    case "desc":
      return (
        <div style={style} className="flex items-center px-3 text-[11.5px] text-fg-muted">
          <span className="truncate">{row.text}</span>
        </div>
      );
    case "in":
      return (
        <div style={style} className="relative flex items-center gap-1.5 px-3 text-[12px]" data-port={row.id}>
          {port}
          <span>{row.label}</span>
          <span className="font-mono text-[10px]" style={{ color: PORT_TYPES[row.port].color }}>
            {PORT_TYPES[row.port].label}
          </span>
          {row.note && <span className="ml-auto truncate text-[11px] text-fg-muted">{row.note}</span>}
        </div>
      );
    case "out":
      return (
        <div
          style={style}
          className="relative flex items-center justify-end gap-1.5 px-3 text-[12px]"
          data-port={row.id}
        >
          <span className="font-mono text-[10px]" style={{ color: PORT_TYPES[row.port].color }}>
            {PORT_TYPES[row.port].label}
          </span>
          <span className="truncate">{row.label}</span>
          {port}
        </div>
      );
    case "field":
      return (
        <div style={style} className="flex flex-col gap-1 px-3 pt-1">
          <span className="text-[11.5px] text-fg-secondary">{row.label}</span>
          <span
            className={cn(
              "flex h-[28px] items-center rounded-[6px] border border-border-input bg-inset px-2 text-[11.5px] text-fg",
              row.mono !== false && "font-mono",
            )}
          >
            <span className="truncate">{row.value}</span>
          </span>
        </div>
      );
    case "chips":
      return (
        <div style={style} className="flex flex-col gap-1 px-3 pt-1">
          <span className="text-[11.5px] text-fg-secondary">{row.label}</span>
          <span className="flex h-[28px] items-center gap-1 overflow-hidden">
            {row.items.map((item) => (
              <span
                key={item.label}
                title={item.label}
                className={cn(
                  "inline-flex h-[22px] max-w-[140px] shrink-0 items-center rounded-[5px] border px-1.5 font-mono text-[10.5px]",
                  item.tone === "org" && "border-accent/40 bg-accent/10 text-accent",
                  item.tone === "team" && "border-info/40 bg-[var(--info-tint)] text-info",
                  item.tone === "custom" && "border-border-strong bg-inset text-fg-secondary",
                  !item.tone && "border-border-input bg-inset text-fg",
                )}
              >
                <span className="truncate">{item.label}</span>
              </span>
            ))}
          </span>
        </div>
      );
    case "area": {
      const shown = row.lines.slice(0, AREA_MAX_LINES);
      const more = row.lines.length > AREA_MAX_LINES;
      return (
        <div style={style} className="flex flex-col gap-1 px-3 pt-1">
          <span className="text-[11.5px] text-fg-secondary">{row.label}</span>
          <div className="overflow-hidden rounded-[6px] border border-border-input bg-inset px-2 py-[3px] font-mono text-[11px] leading-[18px] text-fg-prose">
            {shown.map((line, index) => (
              <div key={index} className="truncate whitespace-pre">
                {more && index === shown.length - 1 ? `${line} …` : line || " "}
              </div>
            ))}
          </div>
        </div>
      );
    }
    case "sep":
      return (
        <div style={style} className="flex items-center px-0">
          <div className="h-px flex-1 bg-border-subtle" />
        </div>
      );
  }
}

export type FlowNodeFrameProps = {
  type: WorkflowNodeType;
  /** A Step's icon follows what it runs. */
  executor?: ExecutorKind | undefined;
  title: string;
  rows: readonly FlowRow[];
  /** Read by assistive tech after the name: "agent · support-triage", a CEL preview… */
  chip?: string | undefined;
  /** Shown while idle: "avg 1.1 s", "3 choices". */
  meta?: string | undefined;
  status?: WorkflowNodeStatus;
  /** The last run's duration, shown with a done status. */
  time?: string | undefined;
  problems?: number;
  selected?: boolean;
  onSelect?: () => void;
  /** The connection handle of a port row. */
  renderPort?: (row: Extract<FlowRow, { kind: "in" | "out" }>) => ReactNode;
  /** Extra header buttons (inspect output…). */
  actions?: ReactNode;
  width?: number;
  className?: string;
};

/** A component on the canvas: icon header with its status, then its rows. The title selects it. */
export function FlowNodeFrame({
  type,
  executor,
  title,
  rows,
  chip,
  meta,
  status = "idle",
  time,
  problems = 0,
  selected = false,
  onSelect,
  renderPort,
  actions,
  width = FLOW_NODE_WIDTH,
  className,
}: FlowNodeFrameProps) {
  const descriptionId = useId();
  const details = [
    chip,
    status !== "idle" ? STATUS_TEXT[status] : undefined,
    problems ? `${String(problems)} problem${problems === 1 ? "" : "s"}` : undefined,
    meta,
  ].filter(Boolean);
  return (
    <div
      data-slot="node-card"
      data-status={status}
      className={cn(
        "rounded-card border bg-surface-raised shadow-[0_8px_22px_rgb(0_0_0/0.35)] transition-[border-color,box-shadow]",
        selected
          ? "border-accent shadow-[0_10px_28px_rgb(0_0_0/0.45)] outline-[2.5px] outline-offset-[-1.5px] outline-accent"
          : "border-border-input hover:border-border-dashed",
        status === "running" && !selected && "border-info shadow-[0_0_0_3px_rgb(125_166_255/0.25)]",
        status === "failed" && !selected && "border-danger",
        className,
      )}
      style={{ width }}
    >
      <div
        className="flex items-center gap-2 border-b border-border-subtle pr-2 pl-2.5"
        style={{ height: FLOW_ROW_HEIGHTS.header }}
      >
        <WorkflowGlyph type={type} executor={executor} size={24} />
        <button
          type="button"
          aria-label={`${type} ${title || "Untitled"}`}
          aria-pressed={selected}
          aria-describedby={details.length > 0 ? descriptionId : undefined}
          onClick={onSelect}
          className="min-w-0 flex-1 cursor-pointer truncate rounded-type border-0 bg-transparent p-0 text-left text-[13px] font-semibold text-fg focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none"
        >
          {title || "Untitled"}
        </button>
        {problems > 0 && (
          <span aria-hidden className="inline-flex items-center gap-1 text-[11px] text-danger">
            <AlertTriangle className="size-3" />
            {problems}
          </span>
        )}
        <StatusBadge status={status} time={time} meta={meta} />
        {actions}
      </div>
      {rows.map((row, index) => (
        <Row
          key={index}
          row={row}
          port={row.kind === "in" || row.kind === "out" ? renderPort?.(row) : undefined}
        />
      ))}
      <div style={{ height: FLOW_ROW_HEIGHTS.bottom }} />
      {details.length > 0 && (
        <span id={descriptionId} hidden>
          {details.join(", ")}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- groups, input / output, notes

export const GROUP_HEADER = 40;
export const GROUP_FOOTER = 30;

/** Loop, Parallel or Steps: a dashed frame holding its steps, with ports on its header. */
export function GroupFrame({
  type,
  title,
  label,
  footer,
  meta,
  status = "idle",
  problems = 0,
  selected = false,
  onSelect,
  inPort,
  outPort,
  children,
  width,
  height,
}: {
  type: WorkflowNodeType;
  title: string;
  /** "LOOP · MAX 3", "PARALLEL". */
  label: string;
  footer?: string | undefined;
  meta?: string | undefined;
  status?: WorkflowNodeStatus;
  problems?: number;
  selected?: boolean;
  onSelect?: () => void;
  inPort?: ReactNode;
  outPort?: ReactNode;
  children?: ReactNode;
  width: number;
  height: number;
}) {
  const color = NODE_COLORS[type];
  const descriptionId = useId();
  const details = [
    meta,
    status !== "idle" ? STATUS_TEXT[status] : undefined,
    problems ? `${String(problems)} problem${problems === 1 ? "" : "s"}` : undefined,
  ].filter(Boolean);
  return (
    <div
      data-slot="group-frame"
      data-status={status}
      className={cn(
        "relative rounded-panel border-[1.5px] transition-[border-color,box-shadow]",
        selected ? "border-solid outline-[2.5px] outline-offset-[-2px] outline-accent" : "border-dashed",
        status === "running" && !selected && "ring-[3px] ring-info/30",
      )}
      style={{
        width,
        height,
        borderColor: selected ? "var(--accent)" : tint(color, 0.7),
        backgroundColor: tint(color, selected ? 0.09 : 0.05),
      }}
    >
      <div className="relative flex items-center gap-2 px-3.5" style={{ height: GROUP_HEADER }}>
        {inPort}
        <WorkflowGlyph type={type} size={20} />
        <span className="font-mono text-[10.5px] font-semibold tracking-[0.06em]" style={{ color }}>
          {label}
        </span>
        <button
          type="button"
          aria-label={`${type} ${title || "Untitled"}`}
          aria-pressed={selected}
          aria-describedby={details.length > 0 ? descriptionId : undefined}
          onClick={onSelect}
          className="min-w-0 cursor-pointer truncate rounded-type border-0 bg-transparent p-0 text-left text-[13px] font-semibold text-fg focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none"
        >
          {title || "Untitled"}
        </button>
        <span className="flex-1" />
        {problems > 0 && (
          <span aria-hidden className="inline-flex items-center gap-1 text-[11px] text-danger">
            <AlertTriangle className="size-3" />
            {problems}
          </span>
        )}
        <StatusBadge status={status} meta={meta} />
        {outPort}
      </div>
      {footer && (
        <span
          className="absolute bottom-2 left-3.5 max-w-[calc(100%-56px)] truncate font-mono text-[10.5px]"
          style={{ color: tint(color, 0.95) }}
        >
          {footer}
        </span>
      )}
      {children}
      {details.length > 0 && (
        <span id={descriptionId} hidden>
          {details.join(", ")}
        </span>
      )}
    </div>
  );
}

export const IO_NODE = { width: 200, height: 2 + 44 + 34 } as const;

/** Where the run starts (the workflow's input) and where its last step's output comes out. */
export function FlowIoNode({
  kind,
  title,
  description,
  port,
}: {
  kind: "input" | "output";
  title: string;
  description: string;
  port?: ReactNode;
}) {
  return (
    <div
      data-slot="io-node"
      className="relative rounded-card border border-border-input bg-surface-raised shadow-[0_8px_22px_rgb(0_0_0/0.35)]"
      style={{ width: IO_NODE.width, height: IO_NODE.height }}
    >
      <div className="flex h-[44px] items-center gap-2 border-b border-border-subtle px-2.5">
        <span
          aria-hidden
          className="inline-flex size-6 items-center justify-center rounded-[7px] bg-[color-mix(in_srgb,var(--fg-secondary)_14%,transparent)] text-fg-secondary"
        >
          {kind === "input" ? <Plus className="size-3.5" /> : <Check className="size-3.5" />}
        </span>
        <span className="truncate text-[13px] font-semibold">{title}</span>
      </div>
      <div
        className={cn(
          "relative flex h-[34px] items-center gap-1.5 px-3 text-[11.5px] text-fg-muted",
          kind === "input" && "justify-end",
        )}
      >
        {kind === "output" && port}
        <span className="truncate">{description}</span>
        {kind === "input" && port}
      </div>
    </div>
  );
}

/** A sticky note on the canvas: free text for the people building the workflow; agno never sees it. */
export function StickyNote({
  text,
  onChange,
  onDelete,
  readOnly = false,
  width = 240,
}: {
  text: string;
  onChange: (text: string) => void;
  onDelete: () => void;
  readOnly?: boolean;
  width?: number;
}) {
  return (
    <div
      data-slot="sticky-note"
      className="flex flex-col gap-1 rounded-tile border border-note-border bg-note px-3 pt-2 pb-2.5 text-note-fg shadow-[0_8px_22px_rgb(0_0_0/0.3)]"
      style={{ width }}
    >
      <div className="flex items-center gap-2">
        <span className="flex-1 text-[11.5px] font-semibold">Note</span>
        {!readOnly && (
          <button
            type="button"
            aria-label="Delete note"
            onClick={onDelete}
            className="nodrag inline-flex size-5 cursor-pointer items-center justify-center rounded-type border-0 bg-transparent text-note-fg/80 hover:text-note-fg focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none"
          >
            <Trash2 aria-hidden className="size-3.5" />
          </button>
        )}
      </div>
      <textarea
        aria-label="Note"
        value={text}
        readOnly={readOnly}
        rows={Math.min(8, Math.max(2, text.split("\n").length))}
        placeholder="Write a note for the people working on this workflow"
        onChange={(event) => {
          onChange(event.target.value);
        }}
        className="nodrag nowheel resize-none border-0 bg-transparent p-0 text-[12px] leading-normal text-note-fg outline-none placeholder:text-note-fg/60"
      />
    </div>
  );
}

// ---------------------------------------------------------------- connectors and the palette

export type BranchTone = "choice" | "true" | "else";

/** The pill on a branch: a Router choice's name, or `true` / `else` under a Condition. */
export function BranchLabel({ tone, children }: { tone: BranchTone; children: ReactNode }) {
  const styles: Record<BranchTone, CSSProperties> = {
    choice: {
      color: "var(--entity-team-text)",
      backgroundColor: "var(--surface-raised)",
      borderColor: tint(NODE_COLORS.Router, 0.45),
    },
    true: {
      color: NODE_COLORS.Condition,
      backgroundColor: "var(--surface-raised)",
      borderColor: tint(NODE_COLORS.Condition, 0.45),
    },
    else: {
      color: "var(--fg-secondary)",
      backgroundColor: "var(--surface-raised)",
      borderColor: "var(--border)",
    },
  };
  return (
    <span
      data-slot="branch-label"
      className="inline-flex max-w-[180px] items-center truncate rounded-full border px-2 py-0.5 font-mono text-[11px]"
      style={styles[tone]}
    >
      {children}
    </span>
  );
}

/** The "+" on a connector or in an empty container: inserts there, and accepts palette items dropped on it. */
export function InsertButton({
  onInsert,
  onDropItem,
  label = "Insert step here",
  disabled = false,
}: {
  onInsert: () => void;
  onDropItem?: ((event: DragEvent<HTMLButtonElement>) => void) | undefined;
  label?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      data-slot="insert-button"
      aria-label={label}
      disabled={disabled}
      onClick={onInsert}
      onDragOver={(event) => {
        if (!onDropItem) return;
        event.preventDefault();
        event.currentTarget.dataset.over = "true";
      }}
      onDragLeave={(event) => {
        delete event.currentTarget.dataset.over;
      }}
      onDrop={(event) => {
        delete event.currentTarget.dataset.over;
        onDropItem?.(event);
      }}
      className={cn(
        "inline-flex size-[20px] cursor-pointer items-center justify-center rounded-full border border-border-strong bg-surface text-fg-muted shadow-[0_2px_8px_rgb(0_0_0/0.4)] transition-[transform,color,border-color]",
        "hover:scale-110 hover:border-accent hover:text-accent focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none",
        "data-[over=true]:scale-125 data-[over=true]:border-accent data-[over=true]:bg-accent/20 data-[over=true]:text-accent",
        "disabled:pointer-events-none disabled:opacity-40",
      )}
    >
      <Plus aria-hidden className="size-3" />
    </button>
  );
}

/** A palette entry: a primitive or an executor, with its icon tile. Click adds it; drag drops it on the canvas. */
export function PaletteItem({
  type,
  name,
  description,
  kind,
  executor,
  onAdd,
  onDragStart,
}: {
  type?: WorkflowNodeType | undefined;
  name: string;
  description?: string | undefined;
  /** For executors: "agent", "team", "workflow", "fn". */
  kind?: string | undefined;
  executor?: ExecutorKind | undefined;
  onAdd: () => void;
  onDragStart: (event: DragEvent<HTMLButtonElement>) => void;
}) {
  const descriptionId = useId();
  return (
    <button
      type="button"
      draggable
      data-slot="palette-item"
      aria-describedby={description ? descriptionId : undefined}
      onClick={onAdd}
      onDragStart={onDragStart}
      className="flex w-full cursor-grab items-center gap-2.5 rounded-control px-1.5 py-1 text-left hover:bg-surface-hover focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none active:cursor-grabbing"
    >
      <WorkflowGlyph type={type ?? "Step"} executor={executor} size={24} />
      <span className="sr-only">{kind ? `Add a step running ${kind}` : "Add a"}</span>{" "}
      <span className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn("truncate text-[12.5px] font-medium", kind && "font-mono text-[12px] font-normal")}
        >
          {name}
        </span>
        {description && (
          <span id={descriptionId} aria-hidden className="truncate text-[11px] text-fg-muted">
            {description}
          </span>
        )}
      </span>
    </button>
  );
}
