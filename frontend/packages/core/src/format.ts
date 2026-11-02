// Formatting shared by operate pages: durations ("worked 3.1 s"), tokens, counts, relative times, AgentOS timestamps
// (epoch seconds, epoch milliseconds or ISO, depending on the endpoint).

/** Epoch seconds, epoch milliseconds or ISO → a Date (or undefined). */
export function toDate(value: string | number | null | undefined): Date | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  if (typeof value === "number") return new Date(value > 1e11 ? value : value * 1000);
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed;
}

/** 380 → "380 ms", 3120 → "3.1 s", 125000 → "2m 5s". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${String(Math.round(ms))} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return seconds ? `${String(minutes)}m ${String(seconds)}s` : `${String(minutes)}m`;
}

const NUMBER = new Intl.NumberFormat("en-US");

/** 2106 → "2,106". */
export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : NUMBER.format(value);
}

/** 0.018 → "1.8%". */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/** "2 min ago", "yesterday", "just now". */
export function formatRelative(
  value: Date | string | number | null | undefined,
  now: Date = new Date(),
): string {
  const date = value instanceof Date ? value : toDate(value);
  if (!date) return "—";
  const seconds = (date.getTime() - now.getTime()) / 1000;
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size)
      return RELATIVE.format(Math.round(seconds / size), unit).replace("minutes", "min");
  }
  return "just now";
}

/** "Today 10:42", "Yesterday 18:03", "Oct 28 09:15". */
export function formatWhen(value: Date | string | number | null | undefined, now: Date = new Date()): string {
  const date = value instanceof Date ? value : toDate(value);
  if (!date) return "—";
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = dayGroup(date, now);
  if (day === "Today" || day === "Yesterday") return `${day} ${time}`;
  return `${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })} ${time}`;
}

/** Session-list date groups: "Today", "Yesterday", "Previous 7 days", "Older". */
export function dayGroup(date: Date, now: Date = new Date()): string {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 24 * 3600 * 1000;
  const time = date.getTime();
  if (time >= start) return "Today";
  if (time >= start - day) return "Yesterday";
  if (time >= start - 7 * day) return "Previous 7 days";
  return "Older";
}

/** Bytes → "182 KB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${String(Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
