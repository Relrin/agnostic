// Control patterns: Timeline, SlotBar, ArgsDiff, CronFields, Countdown. Presentational only: pages
// pass formatted text; Countdown re-renders itself so "in 21h 46m" stays current.
import { useEffect, useId, useState, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { Input } from "../primitives/input";

export type TimelineState = "done" | "now" | "end" | "error";

export type TimelineItem = {
  key?: string;
  text: ReactNode;
  /** Muted second line: when it happened, or a detail. */
  meta?: ReactNode;
  state: TimelineState;
};

const DOT: Record<TimelineState, string> = {
  done: "bg-fg-muted",
  now: "bg-warning",
  end: "bg-accent",
  error: "bg-danger",
};

/** A vertical narrative: 9px dots joined by a line; amber marks "now", lime the end, coral an error. */
export function Timeline({
  items,
  label,
  className,
}: {
  items: TimelineItem[];
  label: string;
  className?: string;
}) {
  return (
    <ol aria-label={label} className={cn("flex flex-col", className)}>
      {items.map((item, index) => (
        <li key={item.key ?? index} className="relative flex gap-3 pb-3 last:pb-0">
          {index < items.length - 1 && (
            <span aria-hidden className="absolute top-3 bottom-0 left-[4px] w-0.5 bg-border-strong" />
          )}
          <span
            aria-hidden
            data-state={item.state}
            className={cn("relative mt-1 size-[9px] shrink-0 rounded-full", DOT[item.state])}
          />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[13px]">{item.text}</span>
            {item.meta && <span className="text-[12px] text-fg-muted">{item.meta}</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Busy and free slots of a worker: one cell per slot (unknown totals show the busy count only). */
export function SlotBar({
  busy,
  total,
  label,
}: {
  busy: number;
  total: number | null | undefined;
  label: string;
}) {
  const cells = Math.max(total ?? busy, busy, 1);
  return (
    <div role="img" aria-label={label} className="flex gap-1">
      {Array.from({ length: cells }, (_, index) => (
        <span
          key={index}
          className={cn("h-2 flex-1 rounded-full", index < busy ? "bg-info" : "bg-surface-hover")}
        />
      ))}
    </div>
  );
}

function show(value: unknown): string {
  if (value === undefined) return "—";
  return typeof value === "string" ? `"${value}"` : JSON.stringify(value);
}

/** Before → after for every argument that changed (what the audit log will record). */
export function ArgsDiff({
  before,
  after,
}: {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}) {
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(
    (key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]),
  );
  if (keys.length === 0) return <p className="text-[12px] text-fg-muted">No argument changes.</p>;
  return (
    <dl
      aria-label="Changed arguments"
      className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 font-mono text-[12px]"
    >
      {keys.map((key) => (
        <div key={key} className="contents">
          <dt className="text-fg-muted">{key}</dt>
          <dd>
            <span className="text-danger line-through">{show(before[key])}</span>{" "}
            <span className="text-accent">{show(after[key])}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

export const CRON_FIELDS = ["Minute", "Hour", "Day", "Month", "Weekday"] as const;

/** The five cron fields as labelled mono inputs; `value` is the whole expression. */
export function CronFields({
  value,
  onChange,
  invalid = [],
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Lower-case field names the server rejected ("minute"). */
  invalid?: readonly string[];
  disabled?: boolean;
}) {
  const prefix = useId();
  const parts = value.trim().split(/\s+/);
  const fields = CRON_FIELDS.map((_, index) => parts[index] ?? "*");
  return (
    <div className="grid grid-cols-5 gap-2">
      {CRON_FIELDS.map((name, index) => {
        const id = `${prefix}-${name.toLowerCase()}`;
        const bad = invalid.includes(name.toLowerCase());
        return (
          <label key={name} htmlFor={id} className="flex flex-col gap-1 text-[11.5px] text-fg-muted">
            {name}
            <Input
              id={id}
              mono
              disabled={disabled}
              aria-invalid={bad || undefined}
              className={cn("text-center", bad && "border-danger")}
              value={fields[index]}
              onChange={(event) => {
                const next = [...fields];
                next[index] = event.target.value.replace(/\s+/g, "") || "*";
                onChange(next.join(" "));
              }}
            />
          </label>
        );
      })}
    </div>
  );
}

/** "in 21h 46m", "in 5m", "3d ago": compact, for expiry columns. */
export function formatCountdown(target: Date, now: Date = new Date()): string {
  const seconds = Math.round((target.getTime() - now.getTime()) / 1000);
  const abs = Math.abs(seconds);
  const days = Math.floor(abs / 86_400);
  const hours = Math.floor((abs % 86_400) / 3600);
  const minutes = Math.floor((abs % 3600) / 60);
  const text =
    days > 0
      ? `${String(days)}d${hours ? ` ${String(hours)}h` : ""}`
      : hours > 0
        ? `${String(hours)}h ${String(minutes).padStart(2, "0")}m`
        : `${String(Math.max(minutes, abs > 0 ? 1 : 0))}m`;
  return seconds >= 0 ? `in ${text}` : `${text} ago`;
}

/** A live countdown to `target` (amber while pending), refreshed every 30 s. */
export function Countdown({ target, className }: { target: Date; className?: string }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date());
    }, 30_000);
    return () => {
      clearInterval(timer);
    };
  }, []);
  const past = target.getTime() <= now.getTime();
  return (
    <time
      dateTime={target.toISOString()}
      title={target.toUTCString()}
      className={cn("tabular-nums", past ? "text-fg-muted" : "text-warning", className)}
    >
      {past ? `Expired ${formatCountdown(target, now)}` : formatCountdown(target, now)}
    </time>
  );
}
