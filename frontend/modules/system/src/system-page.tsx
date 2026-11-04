// `/org/system`: what the control plane itself is doing, for Owners (Administrators read it).
import {
  describeError,
  type CheckOut,
  type FailedJobOut,
  type InstancePollOut,
  type QueueOut,
  type StatusItemOut,
} from "@agnostic/api";
import { formatCount, formatDuration, formatPercent, formatRelative, PermissionGate } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  DataTable,
  ErrorState,
  LoadingRows,
  PageIntro,
  StatusPill,
  type Column,
} from "@agnostic/ui";
import type { ReactNode } from "react";

import { useChecks, useDiscardJob, useFailedJobs, useRetryJob, useSystemStatus } from "./system-api";

const STATE_TONE = { ok: "success", warning: "warning", error: "danger" } as const;

function Card({ title, action, children }: { title: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-card border border-border bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-[14.5px] font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(140px,max-content)_1fr] gap-x-6 gap-y-2 text-[13px]">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-fg-muted">{label}</dt>
          <dd className="min-w-0 font-mono text-[12.5px] break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const QUEUE_COLUMNS: readonly Column<QueueOut>[] = [
  { id: "queue", header: "Queue", cell: (row) => <span className="font-mono">{row.queue}</span> },
  { id: "waiting", header: "Waiting", align: "right", cell: (row) => formatCount(row.waiting) },
  { id: "running", header: "Running", align: "right", cell: (row) => formatCount(row.running) },
  {
    id: "failed",
    header: "Failed",
    align: "right",
    cell: (row) => (row.failed ? <Badge tone="danger">{formatCount(row.failed)}</Badge> : "0"),
  },
  {
    id: "lag",
    header: "Oldest waiting",
    align: "right",
    cell: (row) => (row.oldest_wait_seconds === null ? "—" : formatDuration(row.oldest_wait_seconds * 1000)),
  },
];

const INSTANCE_COLUMNS: readonly Column<InstancePollOut>[] = [
  { id: "name", header: "Instance", cell: (row) => row.display_name },
  { id: "status", header: "Status", cell: (row) => <StatusPill status={row.status} /> },
  {
    id: "seen",
    header: "Last seen",
    cell: (row) => (row.last_seen_at ? formatRelative(row.last_seen_at) : "never"),
  },
  {
    id: "latency",
    header: "Latency",
    align: "right",
    cell: (row) => (row.latency_ms === null ? "—" : `${String(row.latency_ms)} ms`),
  },
  {
    id: "network",
    header: "Browsers",
    cell: (row) => (row.network_mode === "direct" ? "Direct" : "Gateway"),
  },
];

const CHECK_COLUMNS: readonly Column<CheckOut>[] = [
  { id: "name", header: "Endpoint", cell: (row) => row.name },
  {
    id: "result",
    header: "Result",
    cell: (row) => <Badge tone={row.ok ? "success" : "danger"}>{row.ok ? "ok" : "failed"}</Badge>,
  },
  { id: "detail", header: "Detail", cell: (row) => <span className="break-words">{row.detail}</span> },
  {
    id: "facts",
    header: "Facts",
    cell: (row) => (
      <span className="font-mono text-[12px] text-fg-secondary">
        {Object.entries(row.facts)
          .map(([key, value]) => `${key}=${value}`)
          .join(" · ")}
      </span>
    ),
  },
];

function Backlogs({ items }: { items: readonly StatusItemOut[] }) {
  if (items.length === 0) return <p className="text-[13px] text-fg-secondary">Nothing to report.</p>;
  return (
    <ul className="flex flex-col divide-y divide-border">
      {items.map((item) => (
        <li
          key={`${item.group}/${item.name}`}
          className="flex items-start justify-between gap-4 py-2.5 text-[13px]"
        >
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="font-medium">
              <span className="text-fg-muted">{item.group} · </span>
              {item.name}
            </span>
            <span className="break-words text-fg-secondary">{item.detail}</span>
          </div>
          <Badge tone={STATE_TONE[item.state]}>{item.state}</Badge>
        </li>
      ))}
    </ul>
  );
}

function EndpointChecks() {
  const checks = useChecks();
  return (
    <Card
      title="Endpoints"
      action={
        <Button
          size="30"
          variant="primary"
          disabled={checks.isPending}
          onClick={() => {
            checks.mutate({});
          }}
        >
          {checks.isPending ? "Checking…" : checks.data ? "Check again" : "Check endpoints"}
        </Button>
      }
    >
      {checks.error && <Callout tone="danger">{describeError(checks.error).reason}</Callout>}
      {checks.data ? (
        <DataTable
          label="Endpoint checks"
          columns={CHECK_COLUMNS}
          rows={checks.data}
          rowKey={(row) => row.name}
        />
      ) : (
        <p className="text-[13px] text-fg-secondary">
          Probes the database, cache, master key, mail server, sign-in providers, the audit archive and every
          runtime, the same as <span className="font-mono">agnostic config check --connect</span>.
        </p>
      )}
    </Card>
  );
}

function FailedJobs() {
  const jobs = useFailedJobs();
  const retry = useRetryJob();
  const discard = useDiscardJob();
  const columns: Column<FailedJobOut>[] = [
    { id: "task", header: "Job", cell: (row) => <span className="font-mono">{row.task}</span> },
    { id: "queue", header: "Queue", cell: (row) => row.queue },
    { id: "attempts", header: "Attempts", align: "right", cell: (row) => String(row.attempts) },
    { id: "failed", header: "Failed", cell: (row) => (row.failed_at ? formatRelative(row.failed_at) : "—") },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <PermissionGate scope="org:system:manage">
          <div className="flex justify-end gap-1.5">
            <Button
              size="28"
              variant="secondary"
              disabled={retry.isPending}
              aria-label={`Retry ${row.task} #${String(row.id)}`}
              onClick={() => {
                retry.mutate({ path: { job_id: row.id } });
              }}
            >
              Retry
            </Button>
            <Button
              size="28"
              variant="ghost"
              disabled={discard.isPending}
              aria-label={`Discard ${row.task} #${String(row.id)}`}
              onClick={() => {
                discard.mutate({ path: { job_id: row.id } });
              }}
            >
              Discard
            </Button>
          </div>
        </PermissionGate>
      ),
    },
  ];
  return (
    <Card title="Failed jobs">
      {(retry.error ?? discard.error) && (
        <Callout tone="danger">{describeError(retry.error ?? discard.error).reason}</Callout>
      )}
      {jobs.isPending ? (
        <LoadingRows rows={3} />
      ) : jobs.error ? (
        <ErrorState reason={describeError(jobs.error).reason} onRetry={() => void jobs.refetch()} />
      ) : jobs.data.length === 0 ? (
        <p className="text-[13px] text-fg-secondary">No failed jobs.</p>
      ) : (
        <DataTable label="Failed jobs" columns={columns} rows={jobs.data} rowKey={(row) => String(row.id)} />
      )}
    </Card>
  );
}

export function SystemPage() {
  const status = useSystemStatus();
  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-5 px-8 pt-6 pb-10">
      <PageIntro title="System">
        The control plane itself: what is running, whether its endpoints answer, and whether background work
        keeps up.
      </PageIntro>
      {status.isPending ? (
        <LoadingRows rows={6} label="Loading the system status" />
      ) : status.error ? (
        <ErrorState reason={describeError(status.error).reason} onRetry={() => void status.refetch()} />
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title="Versions">
              <Facts
                rows={[
                  ["Agnostic", status.data.versions.server],
                  ["Environment", status.data.environment],
                  ["Python", status.data.versions.python],
                  ["Database", status.data.versions.database],
                  ["Cache", status.data.versions.cache],
                  [
                    "Modules",
                    Object.entries(status.data.versions.modules)
                      .map(([name, version]) => `${name} ${version}`)
                      .join(", "),
                  ],
                ]}
              />
            </Card>
            <Card title="Background work">
              <Backlogs items={status.data.items} />
            </Card>
          </div>
          <Card title="Job queues">
            <DataTable
              label="Job queues"
              columns={QUEUE_COLUMNS}
              rows={status.data.queues}
              rowKey={(row) => row.queue}
              empty="No jobs queued yet."
            />
            <p className="text-[12.5px] text-fg-muted">
              Cache ({status.data.cache.backend}):{" "}
              {status.data.cache.hit_ratio === null
                ? "no lookups yet"
                : `${formatPercent(status.data.cache.hit_ratio)} hits since this API process started`}
            </p>
          </Card>
          <FailedJobs />
          <Card title="Instance polling">
            <DataTable
              label="Instance polling"
              columns={INSTANCE_COLUMNS}
              rows={status.data.instances}
              rowKey={(row) => row.id}
              empty="No instances connected yet."
            />
          </Card>
          <EndpointChecks />
        </>
      )}
    </div>
  );
}
