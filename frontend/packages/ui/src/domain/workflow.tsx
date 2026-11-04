// Workflow builder widgets: the node card (glyph, kind, title, executor chip or CEL preview, stats, status), branch
// labels for Router choices and Condition lanes, the "+" insert affordance and palette items. Presentational: the
// canvas maps the workflow tree to these props and does the layout.
import { AlertTriangle, Check, CircleDashed, LoaderCircle, Pause, Plus, X } from "lucide-react";
import { useId, type CSSProperties, type DragEvent, type ReactNode } from "react";

import { cn } from "../lib/cn";

export type WorkflowNodeType = "Step" | "Steps" | "Parallel" | "Condition" | "Loop" | "Router";
export type WorkflowNodeStatus = "idle" | "running" | "done" | "paused" | "failed" | "skipped";

/** The colour of each primitive, as glyph tiles, borders and palette squares use it. */
export const NODE_COLORS: Record<WorkflowNodeType, string> = {
  Step: "var(--entity-agent)",
  Steps: "var(--entity-fn)",
  Parallel: "var(--entity-workflow)",
  Condition: "var(--node-condition)",
  Loop: "var(--node-loop)",
  Router: "var(--entity-team)",
};

const GLYPHS: Record<WorkflowNodeType, string> = {
  Step: "S",
  Steps: "≡",
  Parallel: "P",
  Condition: "C",
  Loop: "L",
  Router: "R",
};

function tint(color: string, alpha: number): string {
  return `color-mix(in srgb, ${color} ${String(Math.round(alpha * 100))}%, transparent)`;
}

export function WorkflowGlyph({ type, size = 20 }: { type: WorkflowNodeType; size?: number }) {
  const color = NODE_COLORS[type];
  return (
    <span
      aria-hidden
      data-slot="workflow-glyph"
      className="inline-flex shrink-0 items-center justify-center rounded-type font-mono text-[11px] font-semibold"
      style={{ width: size, height: size, color, backgroundColor: tint(color, 0.15) }}
    >
      {GLYPHS[type]}
    </span>
  );
}

const STATUS_ICON: Record<Exclude<WorkflowNodeStatus, "idle">, ReactNode> = {
  running: <LoaderCircle aria-hidden className="size-3.5 animate-spin text-info" />,
  done: <Check aria-hidden className="size-3.5 text-accent" />,
  paused: <Pause aria-hidden className="size-3.5 text-warning" />,
  failed: <X aria-hidden className="size-3.5 text-danger" />,
  skipped: <CircleDashed aria-hidden className="size-3.5 text-fg-muted" />,
};

const STATUS_TEXT: Record<Exclude<WorkflowNodeStatus, "idle">, string> = {
  running: "running",
  done: "done",
  paused: "waiting for a person",
  failed: "failed",
  skipped: "skipped",
};

export type NodeCardProps = {
  type: WorkflowNodeType;
  title: string;
  /** Right of the kind label: "avg 1.1 s", "3 choices", "max 3". */
  meta?: string | undefined;
  /** "agent · support-triage", or a CEL preview "cel · input.contains(…)". */
  chip?: string | undefined;
  selected?: boolean;
  status?: WorkflowNodeStatus;
  /** Problems the validation found on this node. */
  problems?: number;
  onSelect?: () => void;
  className?: string;
  style?: CSSProperties;
};

/** One node of the canvas: a button that selects it. */
export function NodeCard({
  type,
  title,
  meta,
  chip,
  selected = false,
  status = "idle",
  problems = 0,
  onSelect,
  className,
  style,
}: NodeCardProps) {
  const color = NODE_COLORS[type];
  // The name is the visible type and title ("Step Classify ticket"); the rest, some of it only icons, describes it.
  const descriptionId = useId();
  const details = [
    chip,
    status !== "idle" ? STATUS_TEXT[status] : undefined,
    problems ? `${String(problems)} problem${problems === 1 ? "" : "s"}` : undefined,
    meta,
  ].filter(Boolean);
  return (
    <button
      type="button"
      data-slot="node-card"
      data-status={status}
      aria-pressed={selected}
      aria-describedby={details.length > 0 ? descriptionId : undefined}
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col gap-1.5 rounded-card border bg-surface px-3 py-2.5 text-left transition-colors",
        "focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none",
        selected
          ? "border-accent bg-surface-selected ring-[3px] ring-accent/16"
          : "border-border hover:border-border-strong",
        status === "running" && "ring-[3px] ring-info/30",
        status === "failed" && "border-danger",
        className,
      )}
      style={style}
    >
      <span className="flex items-center gap-2">
        <WorkflowGlyph type={type} />
        <span className="font-mono text-[10.5px] tracking-wide uppercase" style={{ color }}>
          {type}
        </span>
        <span className="flex-1" />
        {problems > 0 && (
          <span aria-hidden className="inline-flex items-center gap-1 text-[11px] text-danger">
            <AlertTriangle aria-hidden className="size-3" />
            {problems}
          </span>
        )}
        {meta && (
          <span aria-hidden className="text-[11px] text-fg-muted">
            {meta}
          </span>
        )}
        {status !== "idle" && STATUS_ICON[status]}
      </span>{" "}
      <span className="truncate text-[13.5px] font-medium text-fg">{title || "Untitled"}</span>
      {chip && (
        <span
          aria-hidden
          className="max-w-full self-start truncate rounded-type border border-border px-1.5 py-0.5 font-mono text-[11.5px] text-fg-secondary"
        >
          {chip}
        </span>
      )}
      {details.length > 0 && (
        <span id={descriptionId} hidden>
          {details.join(", ")}
        </span>
      )}
    </button>
  );
}

export type BranchTone = "choice" | "true" | "else";

/** The pill on a branch: a Router choice's name, or `true` / `else` under a Condition. */
export function BranchLabel({ tone, children }: { tone: BranchTone; children: ReactNode }) {
  const styles: Record<BranchTone, CSSProperties> = {
    choice: {
      color: "var(--entity-team-text)",
      backgroundColor: tint(NODE_COLORS.Router, 0.12),
      borderColor: tint(NODE_COLORS.Router, 0.35),
    },
    true: {
      color: NODE_COLORS.Condition,
      backgroundColor: tint(NODE_COLORS.Condition, 0.12),
      borderColor: tint(NODE_COLORS.Condition, 0.35),
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
        "inline-flex size-[22px] items-center justify-center rounded-full border border-border bg-surface text-fg-secondary",
        "hover:border-accent hover:text-accent focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none",
        "data-[over=true]:border-accent data-[over=true]:bg-accent/20 data-[over=true]:text-accent",
        "disabled:pointer-events-none disabled:opacity-40",
      )}
    >
      <Plus aria-hidden className="size-3.5" />
    </button>
  );
}

/** A palette entry: a primitive (glyph tile) or an executor (coloured square, mono name, kind). */
export function PaletteItem({
  type,
  name,
  description,
  kind,
  color,
  onAdd,
  onDragStart,
}: {
  type?: WorkflowNodeType | undefined;
  name: string;
  description?: string | undefined;
  /** For executors: "agent", "team", "workflow", "fn". */
  kind?: string | undefined;
  color?: string | undefined;
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
      className="flex w-full cursor-grab items-center gap-2.5 rounded-control px-2 py-1.5 text-left hover:bg-surface-hover focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none active:cursor-grabbing"
    >
      {type ? (
        <WorkflowGlyph type={type} size={26} />
      ) : (
        <span aria-hidden className="size-[7px] shrink-0 rounded-[2px]" style={{ backgroundColor: color }} />
      )}
      <span className="sr-only">{kind ? `Add a step running ${kind}` : "Add a"}</span>{" "}
      <span className="flex min-w-0 flex-1 flex-col">
        <span
          className={cn("truncate text-[13px] font-medium", kind && "font-mono text-[12.5px] font-normal")}
        >
          {name}
        </span>
        {description && (
          <span id={descriptionId} aria-hidden className="truncate text-[11.5px] text-fg-muted">
            {description}
          </span>
        )}
      </span>
      {kind && (
        <span aria-hidden className="text-[11px] text-fg-muted">
          {kind}
        </span>
      )}
    </button>
  );
}
