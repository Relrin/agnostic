// Data display patterns (04 §3.2): Card, KpiTile, AttentionCard, DataTable, FilterChip, KeyValueList, ApiHint,
// Provenance. Presentational only: pages pass formatted values.
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, CircleAlert, Clock, OctagonX } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "../lib/cn";
import { Button } from "../primitives/button";
import { Tooltip } from "../primitives/tooltip";

export function Card({
  title,
  meta,
  action,
  className,
  children,
  ...props
}: Omit<ComponentProps<"section">, "title"> & { title?: ReactNode; meta?: ReactNode; action?: ReactNode }) {
  return (
    <section
      data-slot="card"
      className={cn(
        "flex min-w-0 flex-col gap-3 rounded-card border border-border bg-surface p-4",
        className,
      )}
      {...props}
    >
      {(title ?? action) !== undefined && (
        <header className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-baseline gap-2">
            {title && <h2 className="text-[13.5px] font-semibold">{title}</h2>}
            {meta && <span className="text-[12px] text-fg-muted">{meta}</span>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export type KpiDelta = {
  /** "↑ 12%", "↑ 0.4 pt", "↓ 0.8 s". */
  label: string;
  direction: "up" | "down" | "flat";
  /** Colour follows good/bad, not the arrow (04 §3.2). */
  sentiment: "good" | "bad" | "neutral";
  /** " vs previous 7 days". */
  context?: string;
};

/** A key metric: label, big value, delta. `estimate` renders dashed (values derived from samples). */
export function KpiTile({
  label,
  value,
  delta,
  detail,
  estimate = false,
  loading = false,
}: {
  label: string;
  value: ReactNode;
  delta?: KpiDelta | undefined;
  detail?: ReactNode;
  estimate?: boolean;
  loading?: boolean;
}) {
  const Arrow = delta?.direction === "up" ? ArrowUp : delta?.direction === "down" ? ArrowDown : undefined;
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-1.5 rounded-tile border bg-surface px-4 py-3.5",
        estimate ? "border-dashed border-border-dashed" : "border-border",
      )}
    >
      <span className="text-[12px] text-fg-muted">{label}</span>
      {loading ? (
        <span aria-hidden className="h-7 w-24 animate-pulse rounded-control bg-surface-hover" />
      ) : (
        <span className="text-[24px] leading-7 font-semibold tracking-tight tabular-nums">{value}</span>
      )}
      {(delta ?? detail) !== undefined && !loading && (
        <span className="flex flex-wrap items-center gap-1 text-[12px] text-fg-muted">
          {delta && (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 font-medium",
                delta.sentiment === "good" && "text-accent",
                delta.sentiment === "bad" && "text-danger",
              )}
            >
              {Arrow && <Arrow className="size-3" aria-hidden />}
              {delta.label}
            </span>
          )}
          {delta?.context}
          {detail}
        </span>
      )}
    </div>
  );
}

const ATTENTION_ICON = {
  warning: { icon: Clock, className: "text-warning", border: "border-warning/30" },
  danger: { icon: OctagonX, className: "text-danger", border: "border-danger/30" },
  info: { icon: CircleAlert, className: "text-info", border: "border-border" },
} as const;

export function AttentionCard({
  severity,
  title,
  detail,
  action,
}: {
  severity: keyof typeof ATTENTION_ICON;
  title: ReactNode;
  detail: ReactNode;
  action?: ReactNode;
}) {
  const style = ATTENTION_ICON[severity];
  const Icon = style.icon;
  return (
    <article className={cn("flex gap-3 rounded-tile border bg-surface px-4 py-3.5", style.border)}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", style.className)} aria-hidden />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="text-[13.5px] font-semibold">{title}</h3>
        <p className="text-[12.5px] break-words text-fg-secondary">{detail}</p>
        {action && <div className="pt-1.5">{action}</div>}
      </div>
    </article>
  );
}

export type Column<T> = {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
};

/** A plain data table with an optional pager footer ("8 of 1,284 ‹ ›"). Rows can be selected. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  label,
  onRowClick,
  selectedKey,
  footer,
  empty,
}: {
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  label: string;
  onRowClick?: (row: T) => void;
  selectedKey?: string | undefined;
  footer?: ReactNode;
  empty?: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-card border border-border bg-surface">
      <table className="w-full border-collapse text-[13px]" aria-label={label}>
        <thead>
          <tr className="border-b border-border-subtle text-left text-[12px] text-fg-muted">
            {columns.map((column) => (
              <th
                key={column.id}
                scope="col"
                className={cn(
                  "px-4 py-2.5 font-medium",
                  column.align === "right" && "text-right",
                  column.className,
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = rowKey(row);
            return (
              <tr
                key={key}
                aria-selected={selectedKey === undefined ? undefined : selectedKey === key}
                className={cn(
                  "border-b border-divider-row last:border-0",
                  onRowClick && "cursor-pointer hover:bg-surface-hover",
                  selectedKey === key && "bg-row-selected",
                )}
                onClick={
                  onRowClick
                    ? () => {
                        onRowClick(row);
                      }
                    : undefined
                }
              >
                {columns.map((column) => (
                  <td
                    key={column.id}
                    className={cn(
                      "px-4 py-2.5 align-top",
                      column.align === "right" && "text-right tabular-nums",
                      column.className,
                    )}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {rows.length === 0 && empty && <div className="p-4">{empty}</div>}
      {footer && (
        <div className="flex items-center justify-end gap-2 border-t border-border-subtle px-4 py-2 text-[12px] text-fg-muted">
          {footer}
        </div>
      )}
    </div>
  );
}

/** "8 of 1,284 ‹ ›". */
export function Pager({
  summary,
  onPrevious,
  onNext,
}: {
  summary: ReactNode;
  onPrevious?: (() => void) | undefined;
  onNext?: (() => void) | undefined;
}) {
  return (
    <>
      <span>{summary}</span>
      <Button variant="icon" size="28" aria-label="Previous page" disabled={!onPrevious} onClick={onPrevious}>
        <ChevronLeft aria-hidden />
      </Button>
      <Button variant="icon" size="28" aria-label="Next page" disabled={!onNext} onClick={onNext}>
        <ChevronRight aria-hidden />
      </Button>
    </>
  );
}

/** "Component: **Any**" filter button. */
export function FilterChip({
  label,
  value,
  ...props
}: ComponentProps<"button"> & { label: string; value: ReactNode }) {
  return (
    <button
      type="button"
      className="inline-flex h-8 cursor-pointer items-center gap-1 rounded-control border border-border-strong px-2.5 text-[12.5px] text-fg-secondary hover:bg-surface-hover"
      {...props}
    >
      {label}: <span className="font-medium text-fg">{value}</span>
    </button>
  );
}

export function KeyValueList({
  items,
  className,
}: {
  items: readonly { key: string; label: ReactNode; value: ReactNode; mono?: boolean }[];
  className?: string;
}) {
  return (
    <dl className={cn("grid grid-cols-[minmax(84px,auto)_1fr] gap-x-4 gap-y-2 text-[12.5px]", className)}>
      {items.map((item) => (
        <div key={item.key} className="contents">
          <dt className="text-fg-muted">{item.label}</dt>
          <dd className={cn("min-w-0 break-all text-fg", item.mono && "font-mono text-[12px]")}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Wraps an action with the API call and scope it needs, as a tooltip ("POST /sessions/…/rename · needs sessions:write"). */
export function ApiHint({ call, scope, children }: { call: string; scope: string; children: ReactNode }) {
  return (
    <Tooltip
      content={
        <span className="font-mono text-[11.5px]">
          {call} · needs {scope}
        </span>
      }
    >
      <span className="inline-flex">{children}</span>
    </Tooltip>
  );
}

/** "Written by the session summary manager after run 3." */
export function Provenance({ children }: { children: ReactNode }) {
  return <p className="text-[12px] text-fg-muted italic">{children}</p>;
}
