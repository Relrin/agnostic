// Trace views: a virtualized waterfall with ticks, depth indent, error bars and ghost
// bars from a comparison run; a tree with glyph tiles; and the span attribute table (OpenInference keys).
import { useState, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { niceTicks, tickLabel, visibleRange } from "../lib/virtual";

export type SpanKindName = "workflow" | "step" | "agent" | "team" | "model" | "tool" | "other";

export type SpanRowView = {
  id: string;
  name: string;
  kind: SpanKindName;
  depth: number;
  startMs: number;
  durationMs: number;
  failed: boolean;
};

export type GhostBar = { startMs: number; durationMs: number };

const ROW = 36;
const TREE_ROW = 34;
const GLYPH: Record<SpanKindName, string> = {
  workflow: "W",
  step: "S",
  agent: "A",
  team: "T",
  model: "M",
  tool: "T",
  other: "·",
};

function ms(value: number): string {
  return value < 1_000 ? `${String(Math.round(value))} ms` : `${(value / 1_000).toFixed(1)} s`;
}

function pct(value: number, total: number): string {
  return `${String(total > 0 ? Math.min(Math.max((value / total) * 100, 0), 100) : 0)}%`;
}

/** Scrollable fixed-height rows that render only what is in view (2 000+ spans stay smooth). */
function VirtualRows<T>({
  rows,
  rowHeight,
  height,
  render,
  label,
}: {
  rows: readonly T[];
  rowHeight: number;
  height: number;
  render: (row: T, index: number) => ReactNode;
  label: string;
}) {
  const [scrollTop, setScrollTop] = useState(0);
  const viewport = Math.min(height, rows.length * rowHeight);
  const [start, end] = visibleRange(scrollTop, viewport, rowHeight, rows.length);
  return (
    <div
      role="rowgroup"
      aria-label={label}
      className="relative overflow-y-auto"
      style={{ height: viewport }}
      onScroll={(event) => {
        setScrollTop(event.currentTarget.scrollTop);
      }}
    >
      <div style={{ height: rows.length * rowHeight, position: "relative" }}>
        {rows.slice(start, end).map((row, offset) => (
          <div
            key={start + offset}
            className="absolute inset-x-0"
            style={{ top: (start + offset) * rowHeight, height: rowHeight }}
          >
            {render(row, start + offset)}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SpanWaterfall({
  spans,
  totalMs,
  selectedId,
  onSelect,
  ghosts,
  height = ROW * 14,
  label = "Span waterfall",
}: {
  spans: readonly SpanRowView[];
  totalMs: number;
  selectedId?: string | undefined;
  onSelect?: (id: string) => void;
  /** Baseline timings drawn under the matching spans (dashed). */
  ghosts?: Readonly<Record<string, GhostBar>> | undefined;
  height?: number;
  label?: string;
}) {
  const scale = Math.max(
    totalMs,
    ...Object.values(ghosts ?? {}).map((ghost) => ghost.startMs + ghost.durationMs),
  );
  const ticks = niceTicks(scale);
  return (
    <div role="table" aria-label={label} aria-rowcount={spans.length} className="min-w-[560px] text-[12.5px]">
      <div
        role="row"
        className="grid grid-cols-[210px_1fr_64px] border-b border-border-subtle font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase"
      >
        <span role="columnheader" className="px-3 py-2">
          Span
        </span>
        <span role="columnheader" className="relative py-2" aria-label="Timeline">
          {ticks.map((tick) => (
            <span
              key={tick}
              aria-hidden
              className="absolute -translate-x-1/2 normal-case first:translate-x-0"
              style={{ left: pct(tick, scale) }}
            >
              {tickLabel(tick)}
            </span>
          ))}
        </span>
        <span role="columnheader" className="px-2 py-2 text-right">
          ms
        </span>
      </div>
      <VirtualRows
        rows={spans}
        rowHeight={ROW}
        height={height}
        label={label}
        render={(span) => {
          const ghost = ghosts?.[span.id];
          const selected = span.id === selectedId;
          return (
            <div
              role="row"
              aria-selected={selected}
              tabIndex={0}
              onClick={() => onSelect?.(span.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect?.(span.id);
                }
              }}
              className={cn(
                "grid h-full cursor-pointer grid-cols-[210px_1fr_64px] items-center border-b border-divider-row hover:bg-surface-hover",
                selected && "bg-accent/6",
              )}
            >
              <span
                role="cell"
                className="flex min-w-0 items-baseline gap-1.5 pr-2"
                style={{ paddingLeft: 12 + span.depth * 14 }}
              >
                <span className="truncate font-mono">{span.name}</span>
                <span className="shrink-0 text-[11px] text-fg-muted">{span.kind}</span>
              </span>
              <span role="cell" className="relative h-full">
                {ticks.map((tick) => (
                  <span
                    key={tick}
                    aria-hidden
                    className="absolute inset-y-0 w-px bg-track"
                    style={{ left: pct(tick, scale) }}
                  />
                ))}
                <span
                  title={`${span.name}: starts +${ms(span.startMs)}, ${ms(span.durationMs)}, ${span.failed ? "ERROR" : "OK"}`}
                  className={cn(
                    "absolute h-2.5 min-w-0.5 rounded-bar",
                    span.failed ? "bg-danger" : "bg-neutral-mark",
                    ghost ? "top-[7px]" : "top-1/2 -translate-y-1/2",
                    selected && "shadow-[0_0_0_2px_var(--accent)]",
                  )}
                  style={{ left: pct(span.startMs, scale), width: pct(span.durationMs, scale) }}
                />
                {ghost && (
                  <span
                    aria-hidden
                    data-ghost
                    className="absolute top-[21px] h-1.5 min-w-0.5 rounded-bar border-[1.5px] border-dashed border-fg-secondary"
                    style={{ left: pct(ghost.startMs, scale), width: pct(ghost.durationMs, scale) }}
                  />
                )}
              </span>
              <span
                role="cell"
                className={cn("px-2 text-right font-mono tabular-nums", span.failed && "text-danger")}
              >
                {Math.round(span.durationMs).toLocaleString("en-US")}
              </span>
            </div>
          );
        }}
      />
    </div>
  );
}

export function SpanTree({
  spans,
  selectedId,
  onSelect,
  height = TREE_ROW * 14,
}: {
  spans: readonly SpanRowView[];
  selectedId?: string | undefined;
  onSelect?: (id: string) => void;
  height?: number;
}) {
  return (
    <div role="tree" aria-label="Span tree" className="text-[12.5px]">
      <VirtualRows
        rows={spans}
        rowHeight={TREE_ROW}
        height={height}
        label="Spans"
        render={(span) => {
          const selected = span.id === selectedId;
          return (
            <div
              role="treeitem"
              aria-selected={selected}
              aria-level={span.depth + 1}
              tabIndex={0}
              onClick={() => onSelect?.(span.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect?.(span.id);
                }
              }}
              className={cn(
                "flex h-full cursor-pointer items-center gap-2 border-b border-divider-row pr-3 hover:bg-surface-hover",
                selected && "bg-accent/6",
              )}
              style={{ paddingLeft: 14 + span.depth * 20 }}
            >
              <span
                aria-hidden
                className={cn(
                  "inline-flex size-[18px] shrink-0 items-center justify-center rounded-badge font-mono text-[10.5px] font-semibold",
                  span.failed ? "bg-danger/14 text-danger" : "bg-surface-hover text-fg-secondary",
                )}
              >
                {GLYPH[span.kind]}
              </span>
              <span className="truncate font-mono">{span.name}</span>
              <span className="text-[11.5px] text-fg-muted">{span.kind}</span>
              <span className="flex-1" />
              <span
                className={cn(
                  "font-mono text-[11px] font-semibold",
                  span.failed ? "text-danger" : "text-fg-muted",
                )}
              >
                {span.failed ? "ERROR" : "OK"}
              </span>
              <span className="w-16 text-right font-mono tabular-nums">
                {Math.round(span.durationMs).toLocaleString("en-US")}
              </span>
            </div>
          );
        }}
      />
    </div>
  );
}

function attributeValue(key: string, value: unknown): ReactNode {
  if (value === null || value === undefined || value === "None")
    return <span className="text-fg-muted">null</span>;
  if (key === "status" || key.startsWith("exception.")) {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return <span className={cn(text === "OK" ? "text-accent" : "text-danger")}>{text}</span>;
  }
  if (typeof value === "number") return <span className="text-[var(--syntax-number)]">{value}</span>;
  if (typeof value === "string") {
    const looksJson = value.startsWith("{") || value.startsWith("[");
    return <span className={looksJson ? "text-[var(--syntax-string)]" : "text-fg-prose"}>{value}</span>;
  }
  return <span className="text-[var(--syntax-string)]">{JSON.stringify(value)}</span>;
}

const ATTRIBUTE_ORDER = [
  "openinference.span.kind",
  "tool.name",
  "llm.model_name",
  "input.value",
  "output.value",
  "status",
  "exception.type",
  "exception.message",
];

/** Key/value table of a span's attributes, OpenInference keys first. */
export function SpanAttributes({ attributes }: { attributes: Readonly<Record<string, unknown>> }) {
  const keys = Object.keys(attributes).sort((a, b) => {
    const rank = (key: string) => (ATTRIBUTE_ORDER.includes(key) ? ATTRIBUTE_ORDER.indexOf(key) : 100);
    return rank(a) - rank(b) || a.localeCompare(b);
  });
  return (
    <table className="w-full border-collapse font-mono text-[12px]" aria-label="Span attributes">
      <tbody>
        {keys.map((key) => (
          <tr key={key} className="border-b border-divider-row last:border-0">
            <th scope="row" className="w-[40%] py-1.5 pr-3 text-left align-top font-normal text-fg-muted">
              {key}
            </th>
            <td className="py-1.5 align-top break-all">{attributeValue(key, attributes[key])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
