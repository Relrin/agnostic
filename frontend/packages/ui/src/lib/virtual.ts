// Fixed-height row windowing for long lists (trace waterfalls with thousands of spans) and time-axis ticks.

/** Rows `[start, end)` to render for a scroll position, with `overscan` extra rows on each side. */
export function visibleRange(
  scrollTop: number,
  viewportHeight: number,
  rowHeight: number,
  count: number,
  overscan = 8,
): [number, number] {
  if (count === 0) return [0, 0];
  const first = Math.floor(Math.max(scrollTop, 0) / rowHeight);
  const last = Math.ceil((Math.max(scrollTop, 0) + viewportHeight) / rowHeight);
  return [Math.max(first - overscan, 0), Math.min(last + overscan, count)];
}

const STEPS_MS = [
  1, 2, 5, 10, 20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 15_000, 30_000, 60_000, 120_000, 300_000,
  600_000, 1_800_000, 3_600_000,
];

/** Round tick positions from 0 to `totalMs` (at most `maxTicks` intervals): 64 s → 0, 15, 30, 45, 60 s. */
export function niceTicks(totalMs: number, maxTicks = 5): number[] {
  if (!(totalMs > 0)) return [0];
  const step = STEPS_MS.find((candidate) => totalMs / candidate <= maxTicks) ?? totalMs / maxTicks;
  const ticks: number[] = [];
  for (let at = 0; at <= totalMs + 1e-9; at += step) ticks.push(at);
  return ticks;
}

/** Tick label: "0 s", "15 s", "250 ms", "2 min". */
export function tickLabel(ms: number): string {
  if (ms === 0) return "0 s";
  if (ms < 1_000) return `${String(Math.round(ms))} ms`;
  if (ms < 60_000) return `${String(Number((ms / 1_000).toFixed(1)))} s`;
  return `${String(Number((ms / 60_000).toFixed(1)))} min`;
}
