import {
  describeError,
  observeOverview,
  observeOverviewOptions,
  type ActivityOut,
  type AttentionOut,
  type KpiOut,
  type OverviewOut,
  type PrimitiveOut,
} from "@agnostic/api";
import {
  formatCalendarDay,
  formatCount,
  formatDuration,
  formatPercent,
  formatRelative,
  useInstances,
  findInstance,
} from "@agnostic/core";
import {
  AttentionCard,
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  EntitySquare,
  ErrorState,
  KpiTile,
  LoadingRows,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  ShareList,
  Skeleton,
  StackedBarChart,
  cn,
  type Column,
  type KpiDelta,
} from "@agnostic/ui";
import { AnswerView, AskBox, suggestionsFor, useAnswer, useAssistant } from "@agnostic/assistant";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { GetStarted } from "./get-started";

type Range = "24h" | "7d" | "30d";

const RANGE_LABEL: Record<Range, string> = {
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
};
const PREVIOUS: Record<Range, string> = {
  "24h": " vs previous 24 hours",
  "7d": " vs previous 7 days",
  "30d": " vs previous 30 days",
};
const TYPE_LABEL = { agent: "Agent", team: "Team", workflow: "Workflow" } as const;

function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count === 1 ? one : many}`;
}

/** Delta label and sentiment: for runs and sessions up is good, for errors and latency up is bad. */
export function kpiDelta(
  kpi: KpiOut | null | undefined,
  kind: "count" | "rate" | "latency",
  context: string,
): KpiDelta | undefined {
  if (kpi?.delta === null || kpi?.delta === undefined || kpi.previous === null) return undefined;
  const direction = kpi.delta > 0 ? "up" : kpi.delta < 0 ? "down" : "flat";
  const magnitude = Math.abs(kpi.delta);
  const label =
    kind === "rate"
      ? `${(magnitude * 100).toFixed(1)} pt`
      : kind === "latency"
        ? formatDuration(magnitude)
        : kpi.delta_pct === null
          ? formatCount(magnitude)
          : `${String(Math.abs(Math.round(kpi.delta_pct)))}%`;
  const goodWhenUp = kind === "count";
  const sentiment = direction === "flat" ? "neutral" : (direction === "up") === goodWhenUp ? "good" : "bad";
  return { label, direction, sentiment, context };
}

function scoped(instance: string, target: string): string {
  return `/i/${encodeURIComponent(instance)}/${target}`;
}

function AttentionSection({
  items,
  instance,
  loading,
}: {
  items: readonly AttentionOut[];
  instance: string;
  loading: boolean;
}) {
  return (
    <section aria-labelledby="attention-heading" className="flex flex-col gap-3">
      <h2 id="attention-heading" className="flex items-center gap-2 text-[14px] font-semibold">
        Needs attention
        {!loading && <Badge tone={items.length ? "warning" : "muted"}>{String(items.length)}</Badge>}
      </h2>
      {loading ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : items.length === 0 ? (
        <p className="text-[13px] text-fg-secondary">
          Nothing needs you right now: no pending approvals, failing schedules or error spikes.
        </p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
          {items.map((item) => (
            <AttentionCard
              key={item.key}
              severity={item.severity}
              title={item.title}
              detail={item.detail}
              action={
                item.action && (
                  <Button asChild size="28" variant="outline">
                    <Link to={scoped(instance, item.action.target)}>{item.action.label}</Link>
                  </Button>
                )
              }
            />
          ))}
        </div>
      )}
    </section>
  );
}

function Kpis({ overview, range }: { overview: OverviewOut | undefined; range: Range }) {
  const kpis = overview?.kpis;
  const loading = overview === undefined;
  const context = PREVIOUS[range];
  const failed = kpis?.failed_runs?.value;
  return (
    <section
      aria-label={`Key metrics, ${RANGE_LABEL[range].toLowerCase()}`}
      className="grid grid-cols-2 gap-3 lg:grid-cols-4"
    >
      <KpiTile
        label="Runs"
        loading={loading}
        value={formatCount(kpis?.runs?.value)}
        delta={kpiDelta(kpis?.runs, "count", context)}
      />
      <KpiTile
        label="Sessions"
        loading={loading}
        value={formatCount(kpis?.sessions?.value)}
        delta={kpiDelta(kpis?.sessions, "count", context)}
      />
      <KpiTile
        label="Error rate"
        loading={loading}
        value={formatPercent(kpis?.error_rate?.value)}
        delta={kpiDelta(kpis?.error_rate, "rate", "")}
        detail={failed !== undefined && failed !== null ? ` · ${formatCount(failed)} failed runs` : undefined}
        estimate={overview?.sampled ?? false}
      />
      <KpiTile
        label="p95 run latency"
        loading={loading}
        value={formatDuration(kpis?.p95_latency_ms?.value)}
        delta={kpiDelta(kpis?.p95_latency_ms, "latency", "")}
        estimate={overview?.sampled ?? false}
      />
    </section>
  );
}

function shortDay(iso: string): string {
  return formatCalendarDay(iso);
}

function Unavailable({ reason }: { reason: string | undefined }) {
  return <p className="text-[12.5px] text-fg-muted">{reason ?? "Not available on this instance."}</p>;
}

function primitiveColumns(instance: string): Column<PrimitiveOut>[] {
  return [
    {
      id: "name",
      header: "Name",
      cell: (row) => (
        <Link
          to={scoped(instance, `chat/${row.type}s/${encodeURIComponent(row.id)}`)}
          className="inline-flex items-center gap-2 font-mono text-[12.5px] hover:underline"
        >
          <EntitySquare kind={row.type} />
          {row.id}
        </Link>
      ),
    },
    { id: "type", header: "Type", cell: (row) => TYPE_LABEL[row.type] },
    {
      id: "serving",
      header: "Serving",
      cell: (row) =>
        row.live_version === null ? (
          <span className="text-fg-muted">code</span>
        ) : (
          <span className="font-mono text-[12.5px]">
            v{row.live_version}
            {row.draft_version !== null && (
              <span className="text-fg-muted"> + v{row.draft_version} draft</span>
            )}
          </span>
        ),
    },
    { id: "runs", header: "Runs 7d", align: "right", cell: (row) => formatCount(row.runs) },
    {
      id: "errors",
      header: "Errors",
      align: "right",
      cell: (row) => (
        <span className={row.error_rate !== null && row.error_rate >= 0.05 ? "text-danger" : undefined}>
          {formatCount(row.errors)}
        </span>
      ),
    },
    {
      id: "last",
      header: "Last run",
      cell: (row) => <span className="text-fg-muted">{formatRelative(row.last_run_at)}</span>,
    },
  ];
}

function Activity({ items }: { items: readonly ActivityOut[] }) {
  if (items.length === 0)
    return <p className="text-[12.5px] text-fg-muted">No activity on this instance yet.</p>;
  return (
    <ul className="flex flex-col divide-y divide-divider-row">
      {items.map((item) => (
        <li key={item.id} className="flex flex-col gap-0.5 py-2">
          <span className="text-[13px]">{item.summary}</span>
          <span className="text-[11.5px] text-fg-muted">
            {formatRelative(item.occurred_at)}
            {item.resource_display ? ` · ${item.resource_display}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Components named by failing attention items ("daily-brief failed twice" → "daily-brief"). */
function failingComponents(attention: readonly AttentionOut[]): string[] {
  return attention
    .filter((item) => item.kind === "schedule_failing" || item.kind === "error_spike")
    .map((item) => item.title.split(" ")[0] ?? "")
    .filter((name) => name.length > 0);
}

/** Ask your OS on Home: the question, then its answer streaming in below with a link to the conversation. */
function AskCard({
  instance,
  attention,
  notice,
}: {
  instance: string;
  attention: readonly AttentionOut[];
  notice: string | null | undefined;
}) {
  const { available } = useAssistant();
  const [asked, setAsked] = useState<{ messageId: string; conversationId: string | null }>();
  const answer = useAnswer(instance, asked?.messageId);
  if (!available) return null;
  return (
    <Card
      id="ask"
      title="Ask your OS"
      action={
        asked?.conversationId ? (
          <Link
            to="/i/$instance/ask"
            params={{ instance }}
            search={{ conversation: asked.conversationId }}
            className="text-[12.5px] text-info hover:text-info-hover"
          >
            Open conversation
          </Link>
        ) : undefined
      }
    >
      <AskBox
        instance={instance}
        context="page:home"
        notice={notice}
        suggestions={suggestionsFor("home", failingComponents(attention))}
        onAsked={(accepted) => {
          setAsked({ messageId: accepted.message_id, conversationId: accepted.conversation_id });
        }}
      />
      {asked && <AnswerView state={answer.state} onStop={() => void answer.stop()} />}
    </Card>
  );
}

/** `/i/:instance/home`: what needs attention, how the instance is doing, and what changed (design spec A §1). */
export function HomePage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const instanceRef = params.instance ?? "";
  const instances = useInstances();
  const instance = findInstance(instances.data, instanceRef);
  const [range, setRange] = useState<Range>("7d");
  const queryClient = useQueryClient();

  const options = observeOverviewOptions({ path: { instance: instanceRef }, query: { range } });
  const overview = useQuery({
    ...options,
    queryFn: instanceRef ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: 60_000,
  });
  // Refresh skips the 60-second server cache and puts the fresh overview where the page reads it.
  const refresh = useMutation({
    mutationFn: async () =>
      (
        await observeOverview({
          path: { instance: instanceRef },
          query: { range, refresh: true },
          throwOnError: true,
        })
      ).data,
    onSuccess: (fresh) => {
      queryClient.setQueryData(options.queryKey, fresh);
    },
  });
  const assistant = useAssistant();
  const data = overview.data;
  const counts = data?.counts;
  const unavailable = data?.unavailable ?? {};

  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-tight">Overview</h1>
          <p className="text-[13px] text-fg-secondary">
            {counts
              ? `${plural(counts.agents ?? 0, "agent", "agents")} · ${plural(counts.teams ?? 0, "agent team", "agent teams")} · ${plural(counts.workflows ?? 0, "workflow", "workflows")} on ${instance?.display_name ?? instanceRef}`
              : (instance?.display_name ?? instanceRef)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={range}
            onValueChange={(value) => {
              setRange(value as Range);
            }}
          >
            <SelectTrigger aria-label="Time range" className="h-8 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(RANGE_LABEL) as Range[]).map((value) => (
                <SelectItem key={value} value={value}>
                  {RANGE_LABEL[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="icon"
            size="32"
            aria-label="Refresh"
            disabled={overview.isFetching || refresh.isPending}
            onClick={() => {
              refresh.mutate();
            }}
          >
            <RefreshCw
              className={overview.isFetching || refresh.isPending ? "animate-spin" : undefined}
              aria-hidden
            />
          </Button>
          <Button asChild variant="outline" size="32">
            <Link to={scoped(instanceRef, "studio/agents")}>Open Studio</Link>
          </Button>
          <Button asChild variant="primary" size="32">
            <Link to={scoped(instanceRef, "studio/agents")}>New agent</Link>
          </Button>
        </div>
      </div>

      <GetStarted instance={instanceRef} />

      {overview.isError ? (
        <ErrorState
          {...describeError(overview.error)}
          onRetry={() => {
            void overview.refetch();
          }}
        />
      ) : (
        <>
          <AttentionSection
            items={data?.attention ?? []}
            instance={instanceRef}
            loading={overview.isPending}
          />
          <Kpis overview={data} range={range} />
          {data?.sampled && (
            <p className="-mt-3 text-[12px] text-fg-muted">
              Error rate and latency come from the newest traces only (dashed tiles): this instance has more
              runs than one overview scans.
            </p>
          )}

          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <Card title="Runs per day">
              {overview.isPending ? (
                <Skeleton className="h-48" />
              ) : data?.runs_per_day ? (
                <StackedBarChart
                  label={`Runs per day, ${shortDay(data.runs_per_day[0]?.date ?? "")} to ${shortDay(data.runs_per_day.at(-1)?.date ?? "")}`}
                  categoryKey="date"
                  formatCategory={shortDay}
                  data={data.runs_per_day.map((day) => ({
                    date: day.date,
                    completed: day.completed,
                    failed: day.failed,
                  }))}
                  series={[
                    { key: "completed", label: "Completed", color: "var(--accent)" },
                    { key: "failed", label: "Failed", color: "var(--danger)" },
                  ]}
                />
              ) : (
                <Unavailable reason={unavailable.kpis ?? unavailable.metrics} />
              )}
            </Card>
            <Card
              title="Model usage by runs"
              meta={data?.model_usage ? plural(data.model_usage.length, "model", "models") : undefined}
            >
              {overview.isPending ? (
                <LoadingRows rows={3} label="Loading model usage" />
              ) : data?.model_usage && data.model_usage.length > 0 ? (
                <ShareList
                  items={data.model_usage.map((model) => ({
                    key: model.model_id,
                    label: model.model_id,
                    value: `${formatCount(model.runs)} · ${formatPercent(model.share, 0)}`,
                    share: model.share,
                  }))}
                />
              ) : (
                <Unavailable
                  reason={
                    unavailable.model_usage ?? unavailable.metrics ?? "No model calls in this range yet."
                  }
                />
              )}
              <Link
                to={scoped(instanceRef, "metrics")}
                className="mt-auto text-[12.5px] text-info hover:text-info-hover"
              >
                Open Metrics →
              </Link>
            </Card>
          </div>

          <Card
            title="Primitives"
            action={
              data?.primitives ? (
                <Link
                  to={scoped(instanceRef, "studio/agents")}
                  className="text-[12.5px] text-info hover:text-info-hover"
                >
                  View all {data.primitives.length}
                </Link>
              ) : undefined
            }
          >
            {overview.isPending ? (
              <LoadingRows rows={5} label="Loading primitives" />
            ) : data?.primitives ? (
              <DataTable
                label="Primitives"
                columns={primitiveColumns(instanceRef)}
                rows={data.primitives.slice(0, 8)}
                rowKey={(row) => `${row.type}:${row.id}`}
                empty={
                  <EmptyState title="No agents, teams or workflows on this instance yet">
                    Register one in the runtime&apos;s code, or build one in Studio.
                  </EmptyState>
                }
              />
            ) : (
              <Unavailable reason={unavailable.primitives} />
            )}
          </Card>

          <div className={cn("grid gap-4", assistant.available && "lg:grid-cols-[1fr_1fr]")}>
            <Card
              title="Recent activity"
              action={
                <Link to="/access/audit" className="text-[12.5px] text-info hover:text-info-hover">
                  Audit log
                </Link>
              }
            >
              {overview.isPending ? (
                <LoadingRows rows={4} label="Loading activity" />
              ) : data?.activity ? (
                <Activity items={data.activity} />
              ) : (
                <Unavailable reason={unavailable.activity} />
              )}
            </Card>
            <AskCard
              instance={instanceRef}
              attention={data?.attention ?? []}
              notice={assistant.status?.data_notice}
            />
          </div>
        </>
      )}
    </div>
  );
}
