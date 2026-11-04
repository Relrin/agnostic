// Studio widgets: LineLinkBadge (a form field's line in the generated code) and GateResultList (how the eval gates
// would judge a version). Presentational: pages map their data to these props.
import { Ban, CircleCheck, CircleDashed, CircleOff } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";

/** `L8`: the line a field maps to. A button when it jumps somewhere (`onClick`), plain text otherwise. */
export function LineLinkBadge({
  line,
  onClick,
  active = false,
  className,
}: {
  line: number;
  onClick?: () => void;
  /** The code view currently focuses this line. */
  active?: boolean;
  className?: string;
}) {
  const classes = cn(
    "inline-flex h-[18px] items-center rounded-type px-1 font-mono text-[11px] leading-none text-accent",
    active ? "bg-accent/16" : "bg-accent/8",
    className,
  );
  const text = `L${String(line)}`;
  if (!onClick) {
    return (
      <span
        data-slot="line-link-badge"
        className={classes}
        title={`Line ${String(line)} of the generated code`}
      >
        {text}
      </span>
    );
  }
  return (
    <button
      type="button"
      data-slot="line-link-badge"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        classes,
        "cursor-pointer hover:bg-accent/20 focus-visible:ring-1 focus-visible:ring-accent focus-visible:outline-none",
      )}
    >
      {text}
      <span className="sr-only">: show line {line} in the code</span>
    </button>
  );
}

export type GateState = "off" | "no_result" | "would_block" | "passes";

export type GateResultRow = {
  id: string;
  dataset: string;
  /** The eval type (accuracy, reliability, performance, agent_as_judge, …). */
  evalType: string;
  /** Minimum average score the gate requires. */
  minAverage: number;
  /** The latest average for this version, when there is one. */
  value?: number | undefined;
  state: GateState;
  /** What the state means for publishing: "Publishing is blocked until accuracy ≥ 0.80." */
  consequence: ReactNode;
};

const GATE_STATE: Record<GateState, { label: string; icon: typeof Ban; className: string }> = {
  off: { label: "Off", icon: CircleOff, className: "bg-surface-hover text-fg-secondary" },
  no_result: { label: "No result", icon: CircleDashed, className: "bg-warning/13 text-warning" },
  would_block: { label: "Would block", icon: Ban, className: "bg-danger/12 text-danger" },
  passes: { label: "Passes", icon: CircleCheck, className: "bg-accent/12 text-accent" },
};

function score(value: number): string {
  return value.toFixed(2);
}

/** One row per gate: dataset · eval type · min average · value · state, with the consequence underneath. */
export function GateResultList({
  rows,
  formatValue = score,
  empty = "No eval gates are configured for this component.",
  className,
  "aria-label": ariaLabel = "Eval gates",
}: {
  rows: readonly GateResultRow[];
  formatValue?: (value: number) => string;
  empty?: ReactNode;
  className?: string;
  "aria-label"?: string;
}) {
  if (rows.length === 0) {
    return <p className={cn("text-[12.5px] text-fg-muted", className)}>{empty}</p>;
  }
  return (
    <ul
      aria-label={ariaLabel}
      data-slot="gate-result-list"
      className={cn(
        "flex flex-col divide-y divide-divider-row rounded-tile border border-border bg-surface",
        className,
      )}
    >
      {rows.map((row) => {
        const state = GATE_STATE[row.state];
        const Icon = state.icon;
        return (
          <li key={row.id} data-state={row.state} className="flex flex-col gap-1 px-3 py-2.5">
            <div className="flex min-w-0 items-center gap-2 text-[13px]">
              <span className="min-w-0 truncate font-medium text-fg">{row.dataset}</span>
              <span className="shrink-0 font-mono text-[11.5px] text-fg-muted">{row.evalType}</span>
              <span className="ml-auto shrink-0 font-mono text-[12px] text-fg-secondary">
                <span className="sr-only">Minimum average </span>≥ {formatValue(row.minAverage)}
              </span>
              <span className="w-12 shrink-0 text-right font-mono text-[12px] text-fg">
                {row.value === undefined ? (
                  <>
                    <span className="text-fg-muted" aria-hidden>
                      —
                    </span>
                    <span className="sr-only">No average yet</span>
                  </>
                ) : (
                  <>
                    <span className="sr-only">Average </span>
                    {formatValue(row.value)}
                  </>
                )}
              </span>
              <span
                className={cn(
                  "inline-flex w-[92px] shrink-0 items-center justify-center gap-1 rounded-badge px-1.5 py-0.5 text-[11px] font-medium",
                  state.className,
                )}
              >
                <Icon className="size-3" aria-hidden />
                {state.label}
              </span>
            </div>
            <p className="text-[12px] text-fg-secondary">{row.consequence}</p>
          </li>
        );
      })}
    </ul>
  );
}
