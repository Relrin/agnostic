import { describeError, problemCode, type QueueJobOut } from "@agnostic/api";
import { formatCount } from "@agnostic/core";
import {
  Button,
  Callout,
  DataTable,
  EmptyState,
  EntitySquare,
  ErrorState,
  LoadingRows,
  Pager,
  StatusPill,
  Tabs,
  TabsList,
  TabsTrigger,
  cn,
  type Column,
} from "@agnostic/ui";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { ConfigStrip, StatCards, Workers } from "./health";
import { JobDetail } from "./job-detail";
import {
  JOB_STATUSES,
  PAGE_SIZE,
  TAB_LABEL,
  configNumber,
  configText,
  formatAge,
  formatSeconds,
  invalidateQueue,
  kindOf,
  secondsSince,
  useQueueJobs,
  useQueueOverview,
  useQueueSummary,
  type JobStatus,
  type StatusTab,
} from "./queue-api";

type Filters = { status: StatusTab; job: string | undefined; page: number };

function readFilters(search: Record<string, unknown>): Filters {
  const text = (key: string) => (typeof search[key] === "string" && search[key] ? search[key] : undefined);
  const status = text("status");
  const page = typeof search.page === "number" ? search.page : Number(text("page") ?? 1);
  return {
    status: JOB_STATUSES.includes(status as JobStatus) ? (status as JobStatus) : "all",
    job: text("job"),
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

const TAB_TONE: Partial<Record<StatusTab, "warning" | "danger">> = { paused: "warning", failed: "danger" };

/** `/i/:instance/queue?status=&job=&page=`: durable-queue health, workers, jobs by state, failed-job recovery. */
export function QueuePage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const instance = params.instance ?? "";
  const filters = readFilters(search);
  const go = (next: Partial<Filters>) => {
    const merged = { ...filters, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/queue`,
      search: {
        ...(merged.status !== "all" ? { status: merged.status } : {}),
        ...(merged.job ? { job: merged.job } : {}),
        ...(merged.page > 1 ? { page: merged.page } : {}),
      },
    });
  };

  const summary = useQueueSummary(instance);
  const allowed = summary.data !== undefined && summary.data.access !== null;
  const overview = useQueueOverview(instance, allowed);
  const jobs = useQueueJobs(instance, filters.status, filters.page, allowed);
  const refused = [overview.error, jobs.error].find((error) => problemCode(error) === "queue_requires_admin");
  const countsOnly = summary.data?.access === null || refused !== undefined;
  const explanation =
    summary.data?.explanation ?? (refused === undefined ? undefined : describeError(refused).reason);
  const counts = overview.data?.summary.counts ?? summary.data?.counts;
  const oldestQueued =
    overview.data?.summary.oldest_queued_age_seconds ?? summary.data?.oldest_queued_age_seconds;
  const config = overview.data?.config;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col gap-6 overflow-y-auto px-6 pt-5 pb-10">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex max-w-3xl flex-col gap-1">
            <h1 className="text-[22px] font-semibold tracking-tight">Queue</h1>
            <p className="text-[13px] text-fg-secondary">
              Background runs accepted with <code className="font-mono">durable=True</code>. Jobs survive
              restarts; workers claim them under a heartbeat lease.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <QueueStorePill config={config} />
            <Button
              variant="icon"
              size="32"
              aria-label="Refresh"
              onClick={() => {
                void invalidateQueue(queryClient);
              }}
            >
              <RefreshCw aria-hidden />
            </Button>
          </div>
        </div>

        {summary.isError ? (
          <ErrorState {...describeError(summary.error)} onRetry={() => void summary.refetch()} />
        ) : summary.isPending ? (
          <LoadingRows rows={4} label="Loading the queue" />
        ) : (
          <>
            <StatCards
              instance={instance}
              counts={counts}
              oldestQueued={oldestQueued}
              overview={countsOnly ? undefined : overview.data}
            />
            {countsOnly ? (
              <CountsOnly counts={counts} explanation={explanation} />
            ) : (
              <>
                {overview.isError ? (
                  <ErrorState {...describeError(overview.error)} onRetry={() => void overview.refetch()} />
                ) : overview.data ? (
                  <Workers overview={overview.data} />
                ) : (
                  <LoadingRows rows={2} label="Loading workers" />
                )}
                <JobsSection
                  instance={instance}
                  filters={filters}
                  counts={counts}
                  oldestQueued={oldestQueued}
                  retention={configNumber(config, "retention_seconds")}
                  jobs={jobs}
                  go={go}
                />
                {config && <ConfigStrip config={config} />}
              </>
            )}
          </>
        )}
      </div>
      {filters.job && allowed && !countsOnly && (
        <JobDetail
          key={filters.job}
          instance={instance}
          jobId={filters.job}
          onClose={() => {
            go({ job: undefined });
          }}
        />
      )}
    </div>
  );
}

function QueueStorePill({ config }: { config: Record<string, unknown> | undefined }) {
  if (!config || typeof config.durable !== "boolean") return null;
  const parts = [configText(config, "db"), configText(config, "table")].filter(Boolean);
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px]",
        config.durable ? "border-border text-fg-secondary" : "border-warning/40 text-warning",
      )}
    >
      <span
        aria-hidden
        className={cn("size-1.5 rounded-full", config.durable ? "bg-accent" : "bg-warning")}
      />
      {config.durable ? ["Durable", ...parts].join(" · ") : "Not durable: jobs are lost on restart"}
    </span>
  );
}

function CountsOnly({
  counts,
  explanation,
}: {
  counts: Record<string, number> | undefined;
  explanation: string | undefined;
}) {
  return (
    <div className="flex flex-col gap-3">
      <p className="font-mono text-[12px] text-fg-muted">
        {JOB_STATUSES.map((status) => `${status} ${formatCount(counts?.[status] ?? 0)}`).join(" · ")}
      </p>
      <Callout tone="info" title="You see counts only">
        {explanation ??
          "The queue is admin-only in AgentOS. Operators reach it through the control plane with queue:operate."}
      </Callout>
    </div>
  );
}

function tabNote(
  status: StatusTab,
  oldestQueued: number | null | undefined,
  retention: number | undefined,
): ReactNode {
  switch (status) {
    case "all":
      return "Newest first";
    case "queued":
      return typeof oldestQueued === "number" ? `oldest waiting ${formatAge(oldestQueued)}` : undefined;
    case "paused":
      return "Paused for human input; not retried as failures";
    case "failed":
      return "Requeue grants one more attempt with the same run_id";
    case "completed":
      return retention ? `deleted after ${formatSeconds(retention)}` : undefined;
    default:
      return undefined;
  }
}

function JobsSection({
  instance,
  filters,
  counts,
  oldestQueued,
  retention,
  jobs,
  go,
}: {
  instance: string;
  filters: Filters;
  counts: Record<string, number> | undefined;
  oldestQueued: number | null | undefined;
  retention: number | undefined;
  jobs: ReturnType<typeof useQueueJobs>;
  go: (next: Partial<Filters>) => void;
}) {
  const rows = jobs.data?.data ?? [];
  const total = jobs.data?.total ?? null;
  const hasNext = total === null ? rows.length === PAGE_SIZE : filters.page * PAGE_SIZE < total;
  const encoded = encodeURIComponent(instance);
  const note = tabNote(filters.status, oldestQueued, retention);

  const columns: Column<QueueJobOut>[] = [
    {
      id: "run_id",
      header: "run_id",
      cell: (row) => (
        <Link
          to={`/i/${encoded}/queue`}
          search={{
            ...(filters.status !== "all" ? { status: filters.status } : {}),
            ...(filters.page > 1 ? { page: filters.page } : {}),
            job: row.id,
          }}
          onClick={(event) => {
            event.stopPropagation();
          }}
          className="font-mono text-[12.5px] text-info hover:text-info-hover"
        >
          {row.run_id}
        </Link>
      ),
    },
    {
      id: "component",
      header: "Component",
      cell: (row) => {
        const kind = kindOf(row.component_type);
        return (
          <span className="flex items-center gap-1.5 whitespace-nowrap">
            {kind && <EntitySquare kind={kind} />}
            {kind ?? row.component_type ?? "run"} ·{" "}
            <code className="font-mono text-[12.5px]">{row.component_id ?? "—"}</code>
          </span>
        );
      },
    },
    {
      id: "status",
      header: "Status",
      cell: (row) => (
        <span className="flex flex-col items-start gap-1">
          <StatusPill status={row.status} />
          {row.detail && <span className="text-[11.5px] text-fg-muted">{row.detail}</span>}
        </span>
      ),
    },
    {
      id: "attempt",
      header: "Attempt",
      cell: (row) => (
        <span className="whitespace-nowrap tabular-nums">
          {row.attempt} of {row.max_attempts}
        </span>
      ),
    },
    {
      id: "deployment",
      header: "Deployment",
      cell: (row) => <code className="font-mono text-[12px] text-fg-secondary">{row.deployment ?? "—"}</code>,
    },
    {
      id: "age",
      header: "Age",
      cell: (row) => {
        const seconds = secondsSince(row.created_at);
        return (
          <span className="whitespace-nowrap text-fg-secondary tabular-nums">
            {seconds === undefined ? "—" : formatAge(seconds)}
          </span>
        );
      },
    },
    {
      id: "key",
      header: "Idempotency-Key",
      cell: (row) => (
        <span
          title={row.idempotency_key ?? undefined}
          className="block max-w-[180px] truncate font-mono text-[12px] text-fg-secondary"
        >
          {row.idempotency_key ?? "—"}
        </span>
      ),
    },
  ];

  return (
    <section aria-labelledby="queue-jobs" className="flex flex-col gap-3">
      <h2 id="queue-jobs" className="sr-only">
        Jobs
      </h2>
      <Tabs
        value={filters.status}
        onValueChange={(value) => {
          go({ status: value as StatusTab, job: undefined, page: 1 });
        }}
      >
        <TabsList>
          {(["all", ...JOB_STATUSES] as const).map((status) => {
            const count = status === "all" ? undefined : counts?.[status];
            return (
              <TabsTrigger
                key={status}
                value={status}
                {...(typeof count === "number" ? { count } : {})}
                {...(TAB_TONE[status] && count ? { countTone: TAB_TONE[status] } : {})}
              >
                {TAB_LABEL[status]}
              </TabsTrigger>
            );
          })}
        </TabsList>
      </Tabs>
      {jobs.isError ? (
        <ErrorState {...describeError(jobs.error)} onRetry={() => void jobs.refetch()} />
      ) : jobs.isPending ? (
        <LoadingRows rows={5} label="Loading jobs" />
      ) : (
        <div className="overflow-x-auto">
          <div className="min-w-[820px]">
            <DataTable
              label="Jobs"
              columns={columns}
              rows={rows}
              rowKey={(row) => row.id}
              selectedKey={filters.job}
              onRowClick={(row) => {
                go({ job: row.id });
              }}
              empty={
                <EmptyState
                  title={
                    filters.status === "all"
                      ? "No jobs in the queue."
                      : `No ${TAB_LABEL[filters.status].toLowerCase()} jobs.`
                  }
                />
              }
              footer={
                <>
                  {note && <span className="mr-auto">{note}</span>}
                  <Pager
                    summary={`Showing ${formatCount(rows.length)} of ${formatCount(total ?? rows.length)}`}
                    onPrevious={
                      filters.page > 1
                        ? () => {
                            go({ page: filters.page - 1, job: undefined });
                          }
                        : undefined
                    }
                    onNext={
                      hasNext
                        ? () => {
                            go({ page: filters.page + 1, job: undefined });
                          }
                        : undefined
                    }
                  />
                </>
              }
            />
          </div>
        </div>
      )}
    </section>
  );
}
