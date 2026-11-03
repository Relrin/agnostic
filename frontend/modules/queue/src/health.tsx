// Queue health: the stat cards (depth, slots, paused, failed), the workers with heartbeats and slots, and the
// read-only QueueConfig strip.
import type { QueueOverviewOut, QueueWorkerOut } from "@agnostic/api";
import { formatCount } from "@agnostic/core";
import { SlotBar, cn } from "@agnostic/ui";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { configNumber, formatAge, formatSeconds, secondsSince } from "./queue-api";

function StatCard({
  label,
  value,
  limit,
  bar,
  detail,
  danger = false,
}: {
  label: string;
  value: number | undefined;
  limit?: ReactNode;
  bar?: { share: number; className: string; label: string } | undefined;
  detail?: ReactNode;
  danger?: boolean;
}) {
  return (
    <section
      aria-label={label}
      className={cn(
        "flex min-w-0 flex-col gap-2 rounded-card border bg-surface px-4 py-3.5",
        danger ? "border-danger/35" : "border-border",
      )}
    >
      <h2 className="text-[12px] font-normal text-fg-muted">{label}</h2>
      <p className="flex items-baseline gap-1.5">
        <span
          className={cn(
            "text-[24px] leading-7 font-semibold tracking-tight tabular-nums",
            danger && "text-danger",
          )}
        >
          {formatCount(value)}
        </span>
        {limit && <span className="text-[13px] text-fg-muted tabular-nums">{limit}</span>}
      </p>
      {bar && (
        <div role="img" aria-label={bar.label} className="h-1.5 w-full rounded-bar bg-track">
          <div
            className={cn("h-full rounded-bar", bar.className)}
            style={{ width: `${String(Math.round(Math.min(Math.max(bar.share, 0), 1) * 100))}%` }}
          />
        </div>
      )}
      {detail && <div className="text-[12px] text-fg-muted">{detail}</div>}
    </section>
  );
}

function plural(count: number, one: string, many: string): string {
  return `${formatCount(count)} ${count === 1 ? one : many}`;
}

/** "max_concurrency 4 × 3 replicas" when every reporting replica runs the same cap. */
function concurrencyNote(workers: readonly QueueWorkerOut[], slots: number | null): string | undefined {
  const bridge = workers.filter((worker) => worker.source === "bridge" && worker.slots_total);
  const caps = new Set(bridge.map((worker) => worker.slots_total));
  const [cap] = [...caps];
  if (caps.size === 1 && cap)
    return `max_concurrency ${String(cap)} × ${plural(bridge.length, "replica", "replicas")}`;
  if (slots) return `${formatCount(slots)} slots across ${plural(bridge.length, "replica", "replicas")}`;
  return undefined;
}

export function StatCards({
  instance,
  counts,
  oldestQueued,
  overview,
}: {
  instance: string;
  counts: Record<string, number> | undefined;
  oldestQueued: number | null | undefined;
  /** Missing for people who see counts only (and while it loads). */
  overview: QueueOverviewOut | undefined;
}) {
  const config = overview?.config;
  const depth = configNumber(config, "max_queue_depth");
  const retention = configNumber(config, "retention_seconds");
  const slots = overview?.slots_total ?? null;
  const queued = counts?.queued;
  const running = counts?.running;
  const approvals = overview?.paused_approvals;
  const concurrency = overview ? concurrencyNote(overview.workers, slots) : undefined;
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-3">
      <StatCard
        label="Waiting to start"
        value={queued}
        limit={depth ? `/ ${formatCount(depth)}` : undefined}
        bar={
          depth && queued !== undefined
            ? {
                share: queued / depth,
                className: "bg-accent",
                label: `${formatCount(queued)} of ${formatCount(depth)} queue depth used`,
              }
            : undefined
        }
        detail={
          depth
            ? "max_queue_depth · 429 when full"
            : typeof oldestQueued === "number" && queued
              ? `oldest waiting ${formatAge(oldestQueued)}`
              : undefined
        }
      />
      <StatCard
        label="Running"
        value={running}
        limit={slots ? `/ ${formatCount(slots)} slots` : undefined}
        bar={
          slots && running !== undefined
            ? {
                share: running / slots,
                className: "bg-info",
                label: `${formatCount(running)} of ${formatCount(slots)} slots busy`,
              }
            : undefined
        }
        detail={concurrency}
      />
      <StatCard
        label="Paused"
        value={counts?.paused}
        detail={
          typeof approvals === "number" ? (
            <Link
              to={`/i/${encodeURIComponent(instance)}/approvals`}
              className="text-info hover:text-info-hover"
            >
              Waiting on {plural(approvals, "approval", "approvals")} →
            </Link>
          ) : (
            "waiting for human input"
          )
        }
      />
      <StatCard
        label="Failed jobs"
        value={counts?.failed}
        danger
        detail={
          retention ? `kept ${formatSeconds(retention)} · retention_seconds ${String(retention)}` : undefined
        }
      />
    </div>
  );
}

function heartbeat(worker: QueueWorkerOut): string {
  if (worker.source === "jobs") return "known from running jobs";
  const seconds = secondsSince(worker.heartbeat_at);
  if (seconds === undefined) return "no heartbeat yet";
  return seconds < 120
    ? `heartbeat ${String(Math.round(seconds))} s ago`
    : `heartbeat ${formatAge(seconds)} ago`;
}

export function Workers({ overview }: { overview: QueueOverviewOut }) {
  const grace = configNumber(overview.config, "lock_grace_seconds");
  return (
    <section aria-labelledby="queue-workers" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="queue-workers" className="text-[15px] font-semibold">
          Workers
        </h2>
        {grace !== undefined && (
          <span className="text-[12px] text-fg-muted">
            abandoned after {String(grace)} s without a heartbeat ·{" "}
            <code className="font-mono">lock_grace_seconds</code>
          </span>
        )}
      </div>
      {overview.workers.length === 0 ? (
        <p className="rounded-card border border-dashed border-border-dashed px-4 py-5 text-[13px] text-fg-secondary">
          No worker has reported in. Workers show up once agnostic-bridge answers or they claim a job.
        </p>
      ) : (
        <ul aria-label="Workers" className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
          {overview.workers.map((worker) => {
            const total = worker.slots_total;
            return (
              <li
                key={worker.name}
                aria-label={worker.name}
                className="flex min-w-0 flex-col gap-2 rounded-card border border-border bg-surface px-4 py-3.5"
              >
                <span className="truncate font-mono text-[13px] font-medium">{worker.name}</span>
                <span className="flex items-center gap-1.5 text-[12px] text-fg-muted">
                  <span
                    aria-hidden
                    className={cn(
                      "size-1.5 rounded-full",
                      worker.source === "bridge" ? "bg-accent" : "bg-neutral-mark",
                    )}
                  />
                  {heartbeat(worker)}
                </span>
                <SlotBar
                  busy={worker.slots_busy}
                  total={total}
                  label={
                    total
                      ? `${String(worker.slots_busy)} of ${String(total)} slots busy`
                      : `${String(worker.slots_busy)} slots busy`
                  }
                />
                <span className="text-[12px] text-fg-secondary">
                  {total
                    ? `${String(worker.slots_busy)} of ${String(total)} running`
                    : `${String(worker.slots_busy)} running`}
                  {worker.deployment && (
                    <>
                      {" · deployment "}
                      <code className="font-mono">{worker.deployment}</code>
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

const CONFIG_KEYS = [
  "max_attempts",
  "retry_delay_seconds",
  "timeout_seconds",
  "lock_grace_seconds",
  "stop_timeout_seconds",
  "poll_interval",
] as const;

export function ConfigStrip({ config }: { config: Record<string, unknown> }) {
  const items = CONFIG_KEYS.flatMap((key) => {
    const value = configNumber(config, key);
    if (value === undefined) return [];
    return [
      { key, value: key === "poll_interval" && Number.isInteger(value) ? value.toFixed(1) : String(value) },
    ];
  });
  if (items.length === 0) return null;
  return (
    <div
      aria-label="Queue config"
      role="group"
      className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-tile border border-border px-4 py-2.5 font-mono text-[11.5px]"
    >
      {items.map((item) => (
        <span key={item.key}>
          <span className="text-fg-muted">{item.key}</span> {item.value}
        </span>
      ))}
      <span className="font-sans text-[12px] text-fg-muted">
        Read-only here: these must match on every replica.
      </span>
    </div>
  );
}
