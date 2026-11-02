// Charts: Recharts with the chart tokens, and always a "View as table" alternative.
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn } from "../lib/cn";

export type BarSeries = { key: string; label: string; color: string };

/** Stacked bars per category (e.g. completed/failed runs per day). */
export function StackedBarChart({
  data,
  series,
  categoryKey,
  label,
  height = 200,
  formatCategory = (value) => value,
  formatValue = (value) => String(value),
  endLabels = false,
}: {
  data: readonly Record<string, string | number>[];
  series: readonly BarSeries[];
  categoryKey: string;
  /** Accessible name: "Runs per day, Oct 25 to Oct 31". */
  label: string;
  height?: number;
  formatCategory?: (value: string) => string;
  formatValue?: (value: number) => string;
  /** Show each series' value for the last category next to the legend ("Workflow 237"). */
  endLabels?: boolean;
}) {
  const [asTable, setAsTable] = useState(false);
  const last = data.at(-1);
  return (
    <figure className="flex flex-col gap-2" aria-label={label}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-3 text-[12px] text-fg-muted">
          {series.map((item) => (
            <span key={item.key} className="inline-flex items-center gap-1.5">
              <span aria-hidden className="size-2.5 rounded-type" style={{ background: item.color }} />
              {item.label}
              {endLabels && last && (
                <span className="font-medium text-fg tabular-nums">
                  {formatValue(Number(last[item.key] ?? 0))}
                </span>
              )}
            </span>
          ))}
        </div>
        <button
          type="button"
          className="cursor-pointer text-[12px] text-info hover:text-info-hover"
          aria-pressed={asTable}
          onClick={() => {
            setAsTable(!asTable);
          }}
        >
          {asTable ? "View as chart" : "View as table"}
        </button>
      </div>
      {asTable ? (
        <table className="w-full text-[12.5px]" aria-label={label}>
          <thead>
            <tr className="text-left text-fg-muted">
              <th scope="col" className="py-1 font-medium">
                {categoryKey}
              </th>
              {series.map((item) => (
                <th key={item.key} scope="col" className="py-1 text-right font-medium">
                  {item.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={String(row[categoryKey])} className="border-t border-divider-row">
                <td className="py-1">{formatCategory(String(row[categoryKey]))}</td>
                {series.map((item) => (
                  <td key={item.key} className="py-1 text-right tabular-nums">
                    {formatValue(Number(row[item.key] ?? 0))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className={cn("w-full")} style={{ height }} role="img" aria-label={label}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={[...data]} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
              <CartesianGrid vertical={false} stroke="var(--divider-row)" />
              <XAxis
                dataKey={categoryKey}
                tickFormatter={(value: string) => formatCategory(value)}
                tick={{ fill: "var(--fg-muted)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tickFormatter={(value: number) => formatValue(value)}
                tick={{ fill: "var(--fg-muted)", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                allowDecimals={false}
              />
              <ChartTooltip
                cursor={{ fill: "var(--surface-hover)" }}
                contentStyle={{
                  background: "var(--surface-raised)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                labelFormatter={(value) =>
                  formatCategory(typeof value === "string" || typeof value === "number" ? String(value) : "")
                }
              />
              {series.map((item, index) => (
                <Bar
                  key={item.key}
                  dataKey={item.key}
                  name={item.label}
                  stackId="stack"
                  fill={item.color}
                  radius={index === series.length - 1 ? [3, 3, 0, 0] : 0}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}

/** Horizontal share bars ("Model usage by runs"). */
export function ShareList({
  items,
}: {
  items: readonly { key: string; label: string; value: string; share: number }[];
}) {
  return (
    <ul className="flex flex-col gap-2.5">
      {items.map((item) => (
        <li key={item.key} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
            <span className="truncate font-mono">{item.label}</span>
            <span className="shrink-0 text-fg-muted tabular-nums">{item.value}</span>
          </div>
          <div className="h-1.5 rounded-bar bg-track">
            <div
              className="h-full rounded-bar bg-chart-1"
              style={{ width: `${String(Math.round(item.share * 100))}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** A thin relative bar (4px) for ranked lists such as "Slowest span types". */
export function ThinBar({ share, label }: { share: number; label?: string }) {
  return (
    <div className="h-1 w-full rounded-bar bg-track" role={label ? "img" : undefined} aria-label={label}>
      <div
        className="h-full rounded-bar bg-neutral-mark"
        style={{ width: `${String(Math.round(Math.min(Math.max(share, 0), 1) * 100))}%` }}
      />
    </div>
  );
}
