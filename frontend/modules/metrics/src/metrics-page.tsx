import {
  apiUrl,
  describeError,
  gatewayJson,
  observeMetricsSummaryOptions,
  observePutPriceTable,
  type AgentOS,
  type ComponentOut,
  type MetricsSummaryOut,
} from "@agnostic/api";
import {
  findInstance,
  formatCalendarDay,
  formatCount,
  formatMillions,
  formatPercent,
  formatRelative,
  formatUsd,
  summaryCost,
  useCan,
  useDebouncedCallback,
  useInstances,
  type Price,
} from "@agnostic/core";
import {
  ApiHint,
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  KpiTile,
  LoadingRows,
  SegmentedControl,
  ShareList,
  Skeleton,
  StackedBarChart,
  cn,
  toast,
  type Column,
} from "@agnostic/ui";
import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { CalendarDays, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

type Preset = "24h" | "7d" | "30d";
type Range = { from: string; to: string };

const CHART = { agent: "var(--chart-1)", team: "var(--chart-2)", workflow: "var(--chart-3)" } as const;
const DAYS: Record<Preset, number> = { "24h": 1, "7d": 7, "30d": 30 };

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function presetRange(preset: Preset, today: Date = new Date()): Range {
  const from = new Date(today.getTime() - (DAYS[preset] - 1) * 86_400_000);
  return { from: isoDay(from), to: isoDay(today) };
}

function shortDay(iso: string): string {
  return formatCalendarDay(iso);
}

function weekday(iso: string): string {
  return formatCalendarDay(iso, { weekday: true });
}

/** "Peak Thu 2.99 M · low Sun 2.00 M". */
export function peakLow(days: readonly { date: string; total: number }[]): string | undefined {
  if (days.length < 2) return undefined;
  const peak = days.reduce((best, day) => (day.total > best.total ? day : best));
  const low = days.reduce((best, day) => (day.total < best.total ? day : best));
  return `Peak ${weekday(peak.date)} ${formatMillions(peak.total, 2)} · low ${weekday(low.date)} ${formatMillions(low.total, 2)}`;
}

function toPrices(summary: MetricsSummaryOut | undefined): Price[] {
  const prices: Price[] = (summary?.prices ?? []).map((row) => ({
    model_id: row.model_id,
    provider: row.provider ?? null,
    input_per_1m: row.input_per_1m,
    output_per_1m: row.output_per_1m,
    cache_read_per_1m: row.cache_read_per_1m ?? null,
    reasoning_per_1m: row.reasoning_per_1m ?? null,
  }));
  const known = new Set(prices.map((price) => price.model_id.toLowerCase()));
  for (const model of summary?.model_usage ?? []) {
    if (known.has(model.model_id.toLowerCase())) continue;
    known.add(model.model_id.toLowerCase());
    prices.push({
      model_id: model.model_id,
      provider: model.provider ?? null,
      input_per_1m: 0,
      output_per_1m: 0,
    });
  }
  return prices;
}

function RefreshAggregates({
  instance,
  lastAggregated,
  range,
  onDone,
}: {
  instance: string;
  lastAggregated: string | null | undefined;
  range: Range;
  onDone: () => void;
}) {
  const can = useCan("metrics:write", instance);
  // Set when a refresh is accepted; cleared once the status reports a run that finished after it.
  const [since, setSince] = useState<number | undefined>(undefined);
  const polling = since !== undefined;
  useQuery({
    queryKey: [instance, "agentos", "metrics-refresh-status", since],
    queryFn:
      since !== undefined
        ? async () => {
            const body = await gatewayJson<AgentOS.MetricsRefreshStatusResponse>(
              instance,
              "metrics/refresh/status",
            );
            const finishedAt = body.finished_at ? Date.parse(body.finished_at) : undefined;
            if (body.status !== "running" && finishedAt !== undefined && finishedAt >= since - 5_000) {
              setSince(undefined);
              if (body.status === "failed") toast.error(`Refresh failed: ${body.error ?? "no detail"}`);
              else onDone();
            }
            return body;
          }
        : skipToken,
    refetchInterval: polling ? 2_000 : false,
  });
  const start = useMutation({
    mutationFn: () => gatewayJson(instance, "metrics/refresh?background=true", { method: "POST" }),
    onSuccess: () => {
      setSince(Date.now());
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const busy = start.isPending || polling;
  return (
    <div className="flex items-center gap-3">
      <span className={cn("text-[12.5px]", busy ? "text-warning" : "text-fg-muted")} aria-live="polite">
        {busy
          ? `Refresh queued · recomputing ${shortDay(range.from)}–${shortDay(range.to)}`
          : lastAggregated
            ? `Aggregated ${formatRelative(lastAggregated)}`
            : "Not aggregated yet"}
      </span>
      <ApiHint call="POST /metrics/refresh" scope="metrics:write">
        <Button
          variant="secondary"
          size="32"
          disabled={busy || can.allowed !== true}
          onClick={() => {
            start.mutate();
          }}
        >
          <RefreshCw className={busy ? "animate-spin" : undefined} aria-hidden />
          Refresh aggregates
        </Button>
      </ApiHint>
    </div>
  );
}

function componentColumns(costs: Record<string, number>): Column<ComponentOut>[] {
  return [
    {
      id: "component",
      header: "Component",
      cell: (row) => (
        <span className="inline-flex items-center gap-2 font-mono text-[12.5px]">
          <span aria-hidden className="size-2.5 rounded-type" style={{ background: CHART[row.type] }} />
          {row.id}
        </span>
      ),
    },
    {
      id: "model",
      header: "Primary model",
      cell: (row) =>
        row.models[0] ? (
          <span className="font-mono text-[12px]">
            {row.models[0].model_id}
            {row.extra_models > 0 && <span className="text-fg-muted"> +{row.extra_models}</span>}
          </span>
        ) : (
          <span className="text-fg-muted">—</span>
        ),
    },
    { id: "runs", header: "Runs", align: "right", cell: (row) => formatCount(row.runs) },
    { id: "sessions", header: "Sessions", align: "right", cell: (row) => formatCount(row.sessions) },
    { id: "in", header: "In tok", align: "right", cell: (row) => formatMillions(row.tokens.input) },
    { id: "out", header: "Out tok", align: "right", cell: (row) => formatMillions(row.tokens.output) },
    {
      id: "cost",
      header: "Est. cost*",
      align: "right",
      cell: (row) => `${row.approximate || row.extra_models > 0 ? "≈ " : ""}${formatUsd(costs[row.id])}`,
    },
  ];
}

function PriceTable({
  prices,
  editable,
  onChange,
}: {
  prices: readonly Price[];
  editable: boolean;
  onChange: (index: number, field: "input_per_1m" | "output_per_1m", value: number) => void;
}) {
  return (
    <table className="w-full text-[12.5px]" aria-label="Your price table">
      <thead>
        <tr className="font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
          <th scope="col" className="py-1 text-left font-normal">
            Model
          </th>
          <th scope="col" className="py-1 text-right font-normal">
            Input
          </th>
          <th scope="col" className="py-1 text-right font-normal">
            Output
          </th>
        </tr>
      </thead>
      <tbody>
        {prices.map((price, index) => (
          <tr key={`${price.model_id}:${price.provider ?? ""}`} className="border-t border-divider-row">
            <td className="py-1.5 pr-2 font-mono">{price.model_id}</td>
            {(["input_per_1m", "output_per_1m"] as const).map((field) => (
              <td key={field} className="py-1 pl-1 text-right">
                <Input
                  type="number"
                  min={0}
                  step={0.05}
                  aria-label={`${price.model_id} ${field === "input_per_1m" ? "input" : "output"} price`}
                  className="ml-auto h-[30px] w-20 text-right font-mono"
                  value={price[field]}
                  disabled={!editable}
                  onChange={(event) => {
                    const value = Number(event.target.value);
                    if (Number.isFinite(value) && value >= 0) onChange(index, field, value);
                  }}
                />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** `/i/:instance/metrics`: daily aggregates, cost from the customer's own price table, model usage. */
export function MetricsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const instanceRef = params.instance ?? "";
  const instances = useInstances();
  const instance = findInstance(instances.data, instanceRef);
  const queryClient = useQueryClient();
  const [preset, setPreset] = useState<Preset | "custom">("7d");
  const [range, setRange] = useState<Range>(() => presetRange("7d"));
  const canPrice = useCan("metrics:write", instanceRef).allowed === true;

  const options = observeMetricsSummaryOptions({ path: { instance: instanceRef }, query: range });
  const summary = useQuery({ ...options, queryFn: instanceRef ? (options.queryFn ?? skipToken) : skipToken });
  const data = summary.data;

  // Edits apply to the summary they were made on; a refetched summary brings the saved table back.
  const [edited, setEdited] = useState<{ source: MetricsSummaryOut; prices: Price[] } | undefined>(undefined);
  const prices = useMemo(
    () => (edited && edited.source === data ? edited.prices : toPrices(data)),
    [edited, data],
  );
  const costs = useMemo(() => (data ? summaryCost(data, prices) : undefined), [data, prices]);

  const save = useMutation({
    mutationFn: async (rows: Price[]) =>
      (
        await observePutPriceTable({
          path: { instance: instanceRef },
          body: { prices: rows.filter((row) => row.input_per_1m > 0 || row.output_per_1m > 0) },
          throwOnError: true,
        })
      ).data,
    onError: (error) => toast.error(`Couldn't save the price table: ${describeError(error).reason}`),
  });
  const persist = useDebouncedCallback((rows: Price[]) => {
    save.mutate(rows);
  }, 600);

  const totals = data?.totals;
  const days = data?.days ?? [];
  const tokenDays = days.map((day) => ({ date: day.date, total: day.tokens.total }));
  const loading = summary.isPending;

  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-tight">Metrics</h1>
          <p className="text-[13px] text-fg-secondary">
            Daily aggregates from <code className="font-mono">GET /metrics</code> for{" "}
            {instance?.display_name ?? instanceRef}.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RefreshAggregates
            instance={instanceRef}
            lastAggregated={data?.last_aggregated_at}
            range={range}
            onDone={() => {
              void queryClient.invalidateQueries({ queryKey: options.queryKey });
            }}
          />
          <SegmentedControl
            label="Date range"
            value={preset === "custom" ? "7d" : preset}
            onValueChange={(value) => {
              setPreset(value);
              setRange(presetRange(value));
            }}
            options={[
              { value: "24h", label: "24 h" },
              { value: "7d", label: "7 days" },
              { value: "30d", label: "30 days" },
            ]}
          />
          <div className="flex items-center gap-1.5 rounded-control border border-border-strong px-2 text-[12.5px]">
            <CalendarDays className="size-3.5 text-fg-muted" aria-hidden />
            <input
              type="date"
              aria-label="From"
              className="h-8 bg-transparent outline-none"
              value={range.from}
              max={range.to}
              onChange={(event) => {
                if (!event.target.value) return;
                setPreset("custom");
                setRange({ ...range, from: event.target.value });
              }}
            />
            –
            <input
              type="date"
              aria-label="To"
              className="h-8 bg-transparent outline-none"
              value={range.to}
              min={range.from}
              onChange={(event) => {
                if (!event.target.value) return;
                setPreset("custom");
                setRange({ ...range, to: event.target.value });
              }}
            />
          </div>
        </div>
      </div>

      {summary.isError ? (
        <ErrorState
          {...describeError(summary.error)}
          onRetry={() => {
            void summary.refetch();
          }}
        />
      ) : (
        <>
          <section aria-label="Totals" className="grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3">
            <KpiTile
              label="Runs"
              loading={loading}
              value={formatCount(totals?.runs.total)}
              detail={
                totals &&
                `${formatCount(totals.runs.agent)} agent · ${formatCount(totals.runs.team)} team · ${formatCount(totals.runs.workflow)} workflow`
              }
            />
            <KpiTile
              label="Sessions"
              loading={loading}
              value={formatCount(totals?.sessions)}
              detail={
                totals?.runs_per_session !== null && totals?.runs_per_session !== undefined
                  ? `${totals.runs_per_session.toFixed(1)} runs per session`
                  : undefined
              }
            />
            <KpiTile
              label="Active users"
              loading={loading}
              value={formatCount(totals?.active_users)}
              detail={
                <>
                  distinct <code className="font-mono">user_id</code> values
                </>
              }
            />
            <KpiTile
              label="Tokens"
              loading={loading}
              value={formatMillions(totals?.tokens.total)}
              detail={
                totals &&
                `${formatMillions(totals.tokens.input)} input (${formatMillions(totals.tokens.cache_read)} cache read) · ${formatMillions(totals.tokens.output)} output · ${formatMillions(totals.tokens.reasoning)} reasoning`
              }
            />
            <KpiTile
              label="Estimated cost"
              loading={loading}
              estimate
              value={`${costs?.approximate ? "≈ " : ""}${formatUsd(costs?.total)}`}
              detail="from your price table, not a bill"
            />
          </section>
          {data?.sampled && (
            <p className="-mt-3 text-[12px] text-fg-muted">
              Per-component numbers come from the newest sessions and traces only: this range has more than
              one summary reads.
            </p>
          )}

          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <Card title="Runs per day by component type">
              {loading ? (
                <Skeleton className="h-52" />
              ) : (
                <StackedBarChart
                  label={`Runs per day by component type, ${shortDay(range.from)} to ${shortDay(range.to)}`}
                  categoryKey="date"
                  formatCategory={weekday}
                  formatValue={(value) => formatCount(value)}
                  endLabels
                  data={days.map((day) => ({
                    date: day.date,
                    agent: day.runs.agent,
                    team: day.runs.team,
                    workflow: day.runs.workflow,
                  }))}
                  series={[
                    { key: "agent", label: "Agent", color: CHART.agent },
                    { key: "team", label: "Team", color: CHART.team },
                    { key: "workflow", label: "Workflow", color: CHART.workflow },
                  ]}
                />
              )}
            </Card>
            <Card title="Tokens per day">
              {loading ? (
                <Skeleton className="h-52" />
              ) : (
                <>
                  <StackedBarChart
                    label={`Tokens per day, ${shortDay(range.from)} to ${shortDay(range.to)}`}
                    categoryKey="date"
                    formatCategory={weekday}
                    formatValue={(value) => formatMillions(value, 2)}
                    data={tokenDays.map((day) => ({ date: day.date, tokens: day.total }))}
                    series={[{ key: "tokens", label: "Tokens", color: "var(--accent)" }]}
                  />
                  {peakLow(tokenDays) && <p className="text-[12px] text-fg-muted">{peakLow(tokenDays)}</p>}
                </>
              )}
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <Card
              title="By component"
              action={
                <a
                  href={apiUrl(
                    `/api/v1/instances/${encodeURIComponent(instanceRef)}/metrics/export.csv?from=${range.from}&to=${range.to}`,
                  )}
                  className="text-[12.5px] text-info hover:text-info-hover"
                  download
                >
                  Export CSV
                </a>
              }
            >
              {loading ? (
                <LoadingRows rows={5} label="Loading components" />
              ) : data?.unavailable.components ? (
                <p className="text-[12.5px] text-fg-muted">{data.unavailable.components}</p>
              ) : (
                <DataTable
                  label="By component"
                  columns={componentColumns(costs?.byComponent ?? {})}
                  rows={data?.components ?? []}
                  rowKey={(row) => `${row.type}:${row.id}`}
                  empty={<EmptyState title="No sessions in this range" />}
                />
              )}
              <p className="text-[11.5px] text-fg-muted">
                * Estimated from token counts and your price table, per model where sessions record it,
                otherwise at the primary model&apos;s rate. Rows marked ≈ mix several models, so their figure
                is approximate.
                {costs && costs.unpriced.length > 0 && ` No price yet for ${costs.unpriced.join(", ")}.`}
              </p>
            </Card>
            <div className="flex flex-col gap-4">
              <Card title="Model usage">
                {loading ? (
                  <LoadingRows rows={3} label="Loading model usage" />
                ) : data && data.model_usage.length > 0 ? (
                  <ShareList
                    items={data.model_usage.map((model) => ({
                      key: `${model.model_id}:${model.provider ?? ""}`,
                      label: model.provider ? `${model.model_id} · ${model.provider}` : model.model_id,
                      value: `${formatCount(model.runs)} · ${formatPercent(model.share, 0)}`,
                      share: model.share,
                    }))}
                  />
                ) : (
                  <p className="text-[12.5px] text-fg-muted">No model calls in this range.</p>
                )}
              </Card>
              <Card title="Your price table" meta={save.isPending ? "Saving…" : undefined}>
                <p className="text-[12px] text-fg-muted">
                  USD per 1 M tokens. Enter your contracted rates; estimates update as you type.
                  {!canPrice && " Changing them needs metrics:write."}
                </p>
                {prices.length > 0 ? (
                  <PriceTable
                    prices={prices}
                    editable={canPrice}
                    onChange={(index, field, value) => {
                      const next = prices.map((row, i) => (i === index ? { ...row, [field]: value } : row));
                      if (data) setEdited({ source: data, prices: next });
                      persist(next);
                    }}
                  />
                ) : (
                  <p className="text-[12.5px] text-fg-muted">Models appear here once they have runs.</p>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
