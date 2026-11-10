import {
  describeError,
  gatewayJson,
  jsonBody,
  observeSpanStatsOptions,
  observeTraceComparisonOptions,
  type AgentOS,
  type ComparisonRowOut,
  type TraceComparisonOut,
} from "@agnostic/api";
import {
  findInstance,
  formatCount,
  formatDuration,
  formatWhen,
  useCan,
  useComponents,
  useInstances,
} from "@agnostic/core";
import {
  Button,
  Callout,
  Card,
  EmptyState,
  EntitySquare,
  ErrorState,
  Input,
  KpiTile,
  LoadingRows,
  Pager,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SpanAttributes,
  SpanTree,
  SpanWaterfall,
  StatusPill,
  ThinBar,
  cn,
  toast,
  type GhostBar,
} from "@agnostic/ui";
import { GeneratedText, useAssistant } from "@agnostic/assistant";
import { keepPreviousData, skipToken, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { GitCompareArrows, Link2, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { buildTraceFilter, type TraceFilters, type TraceRange } from "./build-filter";
import { flattenTrace, modelRollup, traceDurationMs, traceTokens, type FlatSpan } from "./spans";

const PAGE_SIZE = 20;
const SLOW_MS = 30_000;
const RANGE_LABEL: Record<TraceRange, string> = {
  "1h": "Last hour",
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
};
const STATS_WINDOW: Record<TraceRange, "24h" | "7d" | "30d"> = {
  "1h": "24h",
  "24h": "24h",
  "7d": "7d",
  "30d": "30d",
};
const ANY = "any";

type SearchItem = AgentOS.TraceSummary & { tree?: AgentOS.TraceNode[] | null };
type SearchPage = { data: SearchItem[]; meta?: { total_count?: number | null } | null };
type Search = TraceFilters & { page: number; compare: boolean };

function readSearch(raw: Record<string, unknown>): Search {
  const text = (key: string) => (typeof raw[key] === "string" && raw[key] ? raw[key] : undefined);
  const status = text("status");
  const range = text("range");
  return {
    q: text("q"),
    status: status === "OK" || status === "ERROR" ? status : undefined,
    component: text("component"),
    user: text("user"),
    session: text("session"),
    runId: text("run_id"),
    range: range === "1h" || range === "7d" || range === "30d" ? range : "24h",
    page: typeof raw.page === "number" && raw.page > 1 ? raw.page : 1,
    compare: raw.compare === true || raw.compare === "true",
  };
}

function kindOf(trace: AgentOS.TraceSummary): "agent" | "team" | "workflow" | undefined {
  if (trace.workflow_id) return "workflow";
  if (trace.team_id) return "team";
  if (trace.agent_id) return "agent";
  return undefined;
}

function dayLabel(value: string | null | undefined): string {
  return formatWhen(value).split(" ")[0] ?? "";
}

function TraceRow({
  trace,
  selected,
  onSelect,
}: {
  trace: SearchItem;
  selected: boolean;
  onSelect: () => void;
}) {
  const kind = kindOf(trace);
  const duration = traceDurationMs(trace);
  const tokens = traceTokens(trace);
  return (
    <tr
      aria-selected={selected}
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter") onSelect();
      }}
      className={cn(
        "cursor-pointer border-b border-divider-row last:border-0 hover:bg-surface-hover",
        selected && "bg-row-selected shadow-[inset_2px_0_0_var(--accent)]",
      )}
    >
      <td className="px-3 py-2 align-top">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-[12.5px]">{trace.name}</span>
          <StatusPill status={trace.status} />
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-fg-muted">
          {kind && <EntitySquare kind={kind} />}
          {kind ?? "run"} · {trace.user_id ?? "anonymous"} · {formatWhen(trace.start_time)}
        </div>
      </td>
      <td className={cn("px-2 py-2 text-right align-top tabular-nums", duration > SLOW_MS && "text-warning")}>
        {formatDuration(duration)}
      </td>
      <td className="px-2 py-2 text-right align-top tabular-nums">
        {trace.total_spans}
        {trace.error_count > 0 && <span className="text-danger"> · {trace.error_count}</span>}
      </td>
      <td className="px-3 py-2 text-right align-top tabular-nums">{tokens ? formatCount(tokens) : "—"}</td>
    </tr>
  );
}

function SlowestSpans({ instance, range }: { instance: string; range: TraceRange }) {
  const options = observeSpanStatsOptions({ path: { instance }, query: { window: STATS_WINDOW[range] } });
  const stats = useQuery({ ...options, queryFn: instance ? (options.queryFn ?? skipToken) : skipToken });
  const slowest = stats.data?.stats[0]?.avg_duration_ms ?? 0;
  return (
    <Card
      title="Slowest span types"
      meta={`avg duration_ms · ${STATS_WINDOW[range] === "24h" ? "24 hours" : STATS_WINDOW[range] === "7d" ? "7 days" : "30 days"}`}
    >
      {stats.isPending ? (
        <LoadingRows rows={4} label="Loading span statistics" />
      ) : stats.isError ? (
        <p className="text-[12.5px] text-fg-muted">{describeError(stats.error).reason}</p>
      ) : stats.data.stats.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">No spans in this window yet.</p>
      ) : (
        <ul className="flex flex-col gap-2.5">
          {stats.data.stats.slice(0, 5).map((item) => (
            <li key={item.name} className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
                <span className="truncate font-mono">{item.name}</span>
                <span className="shrink-0 text-fg-muted tabular-nums">
                  {formatCount(Math.round(item.avg_duration_ms))} ms ×{formatCount(item.count)}
                </span>
              </div>
              <ThinBar share={slowest ? item.avg_duration_ms / slowest : 0} />
            </li>
          ))}
        </ul>
      )}
      {stats.data?.sampled && (
        <p className="text-[11.5px] text-fg-muted">From the newest {stats.data.traces_scanned} traces.</p>
      )}
    </Card>
  );
}

function groupText(group: ComparisonRowOut["current"]): string {
  if (!group) return "not run";
  return `${formatDuration(group.mean_ms)}${group.count > 1 ? ` ×${String(group.count)}` : ""}`;
}

/** Leaf spans and the top-most spans that didn't run: what the comparison table shows. */
export function comparisonRows(rows: readonly ComparisonRowOut[]): ComparisonRowOut[] {
  const parents = new Set(
    rows.filter((row) => row.depth > 0).map((row) => row.path.slice(0, -1).join("\u0000")),
  );
  const notRun = new Set(rows.filter((row) => row.state === "not_run").map((row) => row.path.join("\u0000")));
  const seen = new Set<string>();
  return rows.filter((row) => {
    const parentNotRun = notRun.has(row.path.slice(0, -1).join("\u0000"));
    const leaf = !parents.has(row.path.join("\u0000"));
    const keep = row.state === "not_run" ? !parentNotRun : leaf;
    if (!keep || seen.has(row.name)) return false;
    seen.add(row.name);
    return true;
  });
}

/** "Why?" follow-ups go to Ask your OS with this trace as the context. */
function AskWhy({ instance, traceId }: { instance: string; traceId: string }) {
  const { available } = useAssistant();
  if (!available) return null;
  return (
    <Link
      to="/i/$instance/ask"
      params={{ instance }}
      search={{
        context: `trace:${traceId}`,
        q: "Why did this run behave differently from the last successful one?",
      }}
      className="self-start text-[12.5px] text-info hover:text-info-hover"
    >
      Ask why
    </Link>
  );
}

function ComparisonCard({
  instance,
  traceId,
  comparison,
  loading,
  error,
  traceStart,
  active,
}: {
  instance: string;
  traceId: string;
  comparison: TraceComparisonOut | undefined;
  loading: boolean;
  error: unknown;
  traceStart: string;
  active: boolean;
}) {
  if (loading) return <LoadingRows rows={3} label="Comparing with the last successful run" />;
  if (error) return <p className="text-[12.5px] text-fg-muted">{describeError(error).reason}</p>;
  if (!comparison) return null;
  const baseline = comparison.baseline;
  if (!baseline) return <p className="text-[12.5px] text-fg-muted">{comparison.reason}</p>;
  const rows = comparisonRows(comparison.rows ?? []);
  return (
    <div className={cn("flex flex-col gap-3", active && "rounded-tile")}>
      <p className="text-[12px] text-fg-muted">
        {formatWhen(baseline.start_time)} · <span className="font-mono">{baseline.trace_id}</span> ·{" "}
        {formatDuration(baseline.duration_ms)}
        {comparison.same_version === true &&
          baseline.version !== null &&
          ` · same version v${String(baseline.version)}`}
      </p>
      <table className="w-full text-[12.5px]" aria-label="Span timings compared with the last successful run">
        <thead>
          <tr className="font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
            <th scope="col" className="py-1 text-left font-normal">
              Span
            </th>
            <th scope="col" className="py-1 text-right font-normal">
              {dayLabel(baseline.start_time)}
            </th>
            <th scope="col" className="py-1 text-right font-normal">
              {dayLabel(traceStart)}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.path.join("/")} className="border-t border-divider-row">
              <td className="py-1.5 font-mono">{row.name}</td>
              <td className="py-1.5 text-right tabular-nums">{groupText(row.baseline)}</td>
              <td
                className={cn(
                  "py-1.5 text-right tabular-nums",
                  (row.state === "error" || row.state === "slower") && "font-semibold text-danger",
                  row.state === "faster" && "text-accent",
                  row.state === "not_run" && "text-fg-muted",
                )}
              >
                {groupText(row.current)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {comparison.diagnosis && (
        <GeneratedText
          instance={instance}
          request={{ kind: "trace.diagnosis", subject: { trace_id: traceId } }}
          label="Generated diagnosis"
        >
          <p className="text-[13px] text-fg-prose">{comparison.diagnosis}</p>
        </GeneratedText>
      )}
      <AskWhy instance={instance} traceId={traceId} />
    </div>
  );
}

function TraceDetail({
  instance,
  traceId,
  compare,
  onCompare,
}: {
  instance: string;
  traceId: string;
  compare: boolean;
  onCompare: (on: boolean) => void;
}) {
  const detail = useQuery({
    queryKey: [instance, "agentos", "trace", traceId],
    queryFn: () => gatewayJson<AgentOS.TraceDetail>(instance, `traces/${encodeURIComponent(traceId)}`),
  });
  const options = observeTraceComparisonOptions({ path: { instance, trace_id: traceId } });
  const comparison = useQuery({ ...options, queryFn: compare ? (options.queryFn ?? skipToken) : skipToken });
  const [view, setView] = useState<"waterfall" | "tree">("waterfall");
  const [selected, setSelected] = useState<string | undefined>(undefined);
  const spans = useMemo(() => (detail.data ? flattenTrace(detail.data) : []), [detail.data]);
  const ghosts = useMemo(() => {
    if (!compare || !comparison.data) return undefined;
    const map: Record<string, GhostBar> = {};
    for (const ghost of comparison.data.ghosts ?? [])
      map[ghost.span_id] = { startMs: ghost.start_ms, durationMs: ghost.duration_ms };
    return map;
  }, [compare, comparison.data]);

  if (detail.isPending) return <LoadingRows rows={6} label="Loading trace" />;
  if (detail.isError)
    return (
      <ErrorState
        {...describeError(detail.error)}
        onRetry={() => {
          void detail.refetch();
        }}
      />
    );
  const trace = detail.data;
  const current: FlatSpan | undefined =
    spans.find((span) => span.id === selected) ??
    spans.find((span) => span.failed && (span.kind === "tool" || span.kind === "model")) ??
    spans.find((span) => span.failed && span.depth > 0) ??
    spans[0];
  const totalMs = traceDurationMs(trace);
  const failed = spans.filter(
    (span) => span.failed && (span.kind === "tool" || span.kind === "model"),
  ).length;
  const tokens = traceTokens(trace);
  const rollup = modelRollup(spans);
  const index = current ? spans.indexOf(current) + 1 : 0;
  const scoped = `/i/${encodeURIComponent(instance)}`;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 className="flex items-center gap-2 font-mono text-[19px] font-semibold">
            {trace.name} <StatusPill status={trace.status} />
          </h1>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-fg-muted">
            <span>
              trace <code className="font-mono">{trace.trace_id}</code>
            </span>
            {trace.run_id && (
              <span>
                run <code className="font-mono">{trace.run_id}</code>
              </span>
            )}
            {trace.session_id && (
              <Link
                to={`${scoped}/sessions/${encodeURIComponent(trace.session_id)}`}
                className="text-info hover:text-info-hover"
              >
                session {trace.session_id}
              </Link>
            )}
            <span>
              {trace.user_id ?? "anonymous"} · {formatWhen(trace.start_time)}
            </span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="32"
            aria-pressed={compare}
            className={cn(compare && "border-accent bg-accent/10")}
            onClick={() => {
              onCompare(!compare);
            }}
          >
            <GitCompareArrows aria-hidden />
            Compare with last successful run
          </Button>
          <Button
            variant="icon"
            size="32"
            aria-label="Copy trace link"
            onClick={() => {
              void navigator.clipboard
                .writeText(window.location.href)
                .then(() => toast.success("Trace link copied"));
            }}
          >
            <Link2 aria-hidden />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-2">
        <KpiTile label="Duration" value={formatDuration(totalMs)} />
        <KpiTile label="Spans" value={formatCount(trace.total_spans)} />
        <KpiTile
          label="Failed calls"
          value={<span className={failed ? "text-danger" : undefined}>{failed}</span>}
        />
        <KpiTile label="Tokens" value={tokens ? formatCount(tokens) : "—"} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          label="Trace view"
          value={view}
          onValueChange={setView}
          options={[
            { value: "tree", label: "Tree" },
            { value: "waterfall", label: "Waterfall" },
          ]}
        />
        <div className="flex items-center gap-3 text-[12px] text-fg-muted">
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="size-2.5 rounded-type bg-neutral-mark" /> OK
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span aria-hidden className="size-2.5 rounded-type bg-danger" /> Error
          </span>
          {compare && comparison.data?.baseline && (
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden className="h-2 w-3 rounded-bar border border-dashed border-fg-secondary" />
              {formatWhen(comparison.data.baseline.start_time)} (
              {formatDuration(comparison.data.baseline.duration_ms)})
            </span>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-card border border-border bg-surface">
        {view === "waterfall" ? (
          <SpanWaterfall
            spans={spans}
            totalMs={totalMs}
            selectedId={current?.id}
            onSelect={setSelected}
            ghosts={ghosts}
          />
        ) : (
          <SpanTree spans={spans} selectedId={current?.id} onSelect={setSelected} />
        )}
      </div>

      <div className="flex flex-wrap gap-4">
        {current && (
          <Card
            className="min-w-[320px] flex-[3]"
            title={<span className="font-mono">{current.name}</span>}
            meta={`span ${String(index)} of ${String(spans.length)} · ${current.kind}`}
            action={
              <span
                className={cn("font-mono text-[11.5px]", current.failed ? "text-danger" : "text-fg-muted")}
              >
                {current.failed ? "ERROR" : "OK"} · duration_ms {Math.round(current.durationMs)} · +
                {formatDuration(current.startMs)}
              </span>
            }
          >
            <SpanAttributes attributes={current.attributes} />
            {rollup.length > 0 && (
              <p className="border-t border-divider-row pt-2 font-mono text-[11.5px] text-fg-muted">
                Model calls in this trace:{" "}
                {rollup
                  .map(
                    (model) =>
                      `llm.model_name ${model.model} · llm.token_count.prompt ${formatCount(model.prompt)} · llm.token_count.completion ${formatCount(model.completion)}`,
                  )
                  .join("; ")}
              </p>
            )}
            {current.kind === "tool" && (
              <Link
                to={`${scoped}/studio/registry?q=${encodeURIComponent(current.name)}`}
                className="text-[12.5px] text-info hover:text-info-hover"
              >
                Tool in Registry
              </Link>
            )}
          </Card>
        )}
        <Card
          className={cn("min-w-[280px] flex-[2]", compare && "border-accent")}
          title="vs last successful run"
          action={
            trace.user_id === "sa:scheduler" ? (
              <Link to={`${scoped}/scheduler`} className="text-[12.5px] text-info hover:text-info-hover">
                Open schedule
              </Link>
            ) : undefined
          }
        >
          {compare ? (
            <ComparisonCard
              instance={instance}
              traceId={traceId}
              comparison={comparison.data}
              loading={comparison.isPending}
              error={comparison.error}
              traceStart={trace.start_time}
              active={compare}
            />
          ) : (
            <p className="text-[12.5px] text-fg-muted">
              Turn on the comparison to line up every span with the last successful run of this component.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

/** `/i/:instance/traces[/:traceId]`: search traces, read a waterfall, and compare with the last good run. */
export function TracesPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const raw = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instanceRef = params.instance ?? "";
  const traceId = params.traceId;
  const search = readSearch(raw);
  const instances = useInstances();
  const instance = findInstance(instances.data, instanceRef);
  const canRead = useCan("traces:read", instanceRef);
  const [text, setText] = useState(search.q ?? "");

  const agents = useComponents(instanceRef, "agents");
  const teams = useComponents(instanceRef, "teams");
  const workflows = useComponents(instanceRef, "workflows");
  const components = [
    ...(agents.data ?? []).map((item) => ({
      value: `agent:${item.id}`,
      label: item.id,
      kind: "agent" as const,
    })),
    ...(teams.data ?? []).map((item) => ({
      value: `team:${item.id}`,
      label: item.id,
      kind: "team" as const,
    })),
    ...(workflows.data ?? []).map((item) => ({
      value: `workflow:${item.id}`,
      label: item.id,
      kind: "workflow" as const,
    })),
  ];

  const go = (next: Partial<Search>, trace: string | undefined = traceId) => {
    const merged = { ...search, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instanceRef)}/traces${trace ? `/${encodeURIComponent(trace)}` : ""}`,
      search: {
        ...(merged.q ? { q: merged.q } : {}),
        ...(merged.status ? { status: merged.status } : {}),
        ...(merged.component ? { component: merged.component } : {}),
        ...(merged.user ? { user: merged.user } : {}),
        ...(merged.session ? { session: merged.session } : {}),
        ...(merged.runId ? { run_id: merged.runId } : {}),
        ...(merged.range !== "24h" ? { range: merged.range } : {}),
        ...(merged.page > 1 ? { page: merged.page } : {}),
        ...(merged.compare ? { compare: true } : {}),
      },
    });
  };

  const schema = useQuery({
    queryKey: [instanceRef, "agentos", "traces-filter-schema"],
    queryFn: instanceRef
      ? () => gatewayJson<AgentOS.FilterSchemaResponse>(instanceRef, "traces/filter-schema")
      : skipToken,
    staleTime: 3_600_000,
    retry: false,
  });
  const filter = buildTraceFilter(search, schema.data);
  const list = useQuery({
    queryKey: [instanceRef, "agentos", "traces-search", filter, search.page],
    queryFn:
      instanceRef && !schema.isPending
        ? () =>
            gatewayJson<SearchPage>(instanceRef, "traces/search", {
              method: "POST",
              ...jsonBody({ filter, group_by: "run", page: search.page, limit: PAGE_SIZE }),
            })
        : skipToken,
    placeholderData: keepPreviousData,
  });

  // Links from Chat and Sessions carry a run id: open that run's trace.
  const firstForRun = search.runId && !traceId ? list.data?.data[0]?.trace_id : undefined;
  useEffect(() => {
    if (firstForRun) go({}, firstForRun);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [firstForRun]);

  const rows = list.data?.data ?? [];
  const total = list.data?.meta?.total_count ?? rows.length;
  const active = [search.status, search.component, search.user, search.session, search.runId, search.q].some(
    Boolean,
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle px-6 py-3">
        <form
          className="flex min-w-[240px] flex-1 items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            go({ q: text.trim() || undefined, page: 1 });
          }}
        >
          <div className="relative flex-1">
            <Search
              className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-fg-muted"
              aria-hidden
            />
            <Input
              aria-label="Search span attributes"
              placeholder="Search names, ids, users…"
              className="h-8 pl-8"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
          </div>
        </form>
        <Select
          value={search.status ?? ANY}
          onValueChange={(value) => {
            go({ status: value === ANY ? undefined : (value as "OK" | "ERROR"), page: 1 });
          }}
        >
          <SelectTrigger aria-label="Status" className={cn("h-8 w-36", search.status && "bg-surface-hover")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Status: Any</SelectItem>
            <SelectItem value="ERROR">Status: ERROR</SelectItem>
            <SelectItem value="OK">Status: OK</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={search.component ?? ANY}
          onValueChange={(value) => {
            go({ component: value === ANY ? undefined : value, page: 1 });
          }}
        >
          <SelectTrigger
            aria-label="Component"
            className={cn("h-8 w-48", search.component && "bg-surface-hover")}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Component: Any</SelectItem>
            {components.map((item) => (
              <SelectItem key={item.value} value={item.value} title={item.label}>
                <span className="flex min-w-0 items-center gap-1.5">
                  <EntitySquare kind={item.kind} />
                  <span className="truncate">{item.label}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          aria-label="User"
          placeholder="User: Any"
          className="h-8 w-36"
          defaultValue={search.user ?? ""}
          onBlur={(event) => {
            const value = event.target.value.trim() || undefined;
            if (value !== search.user) go({ user: value, page: 1 });
          }}
        />
        <Input
          aria-label="Session"
          placeholder="Session: Any"
          className="h-8 w-36"
          defaultValue={search.session ?? ""}
          onBlur={(event) => {
            const value = event.target.value.trim() || undefined;
            if (value !== search.session) go({ session: value, page: 1 });
          }}
        />
        <Select
          value={search.range}
          onValueChange={(value) => {
            go({ range: value as TraceRange, page: 1 });
          }}
        >
          <SelectTrigger aria-label="Time range" className="h-8 w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(RANGE_LABEL) as TraceRange[]).map((value) => (
              <SelectItem key={value} value={value}>
                {RANGE_LABEL[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {active && (
          <Button
            variant="link"
            size="28"
            onClick={() => {
              setText("");
              void navigate({ to: `/i/${encodeURIComponent(instanceRef)}/traces`, search: {} });
            }}
          >
            Clear
          </Button>
        )}
      </div>

      {canRead.allowed === false ? (
        <div className="p-6">
          <Callout tone="info" title="Traces need traces:read">
            {canRead.reason} Traces can contain prompts and tool arguments, so they are granted separately.
          </Callout>
        </div>
      ) : (
        <div className="flex flex-1 flex-wrap gap-6 px-6 py-5">
          <div className="flex min-w-[320px] flex-[2_1_420px] flex-col gap-4">
            <div className="overflow-hidden rounded-card border border-border bg-surface">
              <table className="w-full border-collapse text-[13px]" aria-label="Traces">
                <thead>
                  <tr className="border-b border-border-subtle text-left font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
                    <th scope="col" className="px-3 py-2 font-normal">
                      Trace
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-normal">
                      Time
                    </th>
                    <th scope="col" className="px-2 py-2 text-right font-normal">
                      Spans
                    </th>
                    <th scope="col" className="px-3 py-2 text-right font-normal">
                      Tokens
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((trace) => (
                    <TraceRow
                      key={trace.trace_id}
                      trace={trace}
                      selected={trace.trace_id === traceId}
                      onSelect={() => {
                        go({}, trace.trace_id);
                      }}
                    />
                  ))}
                </tbody>
              </table>
              {list.isPending && (
                <div className="p-3">
                  <LoadingRows rows={6} label="Loading traces" />
                </div>
              )}
              {list.isError && (
                <div className="p-3">
                  <ErrorState
                    {...describeError(list.error)}
                    onRetry={() => {
                      void list.refetch();
                    }}
                  />
                </div>
              )}
              {list.isSuccess && rows.length === 0 && (
                <div className="p-4">
                  <EmptyState
                    title={`No traces ${active ? "match these filters" : `in the ${RANGE_LABEL[search.range].toLowerCase()}`}`}
                  />
                </div>
              )}
              {rows.length > 0 && (
                <div className="flex items-center justify-end gap-2 border-t border-border-subtle px-3 py-2 text-[12px] text-fg-muted">
                  <Pager
                    summary={`${formatCount((search.page - 1) * PAGE_SIZE + rows.length)} of ${formatCount(total)}`}
                    onPrevious={
                      search.page > 1
                        ? () => {
                            go({ page: search.page - 1 });
                          }
                        : undefined
                    }
                    onNext={
                      search.page * PAGE_SIZE < total
                        ? () => {
                            go({ page: search.page + 1 });
                          }
                        : undefined
                    }
                  />
                </div>
              )}
            </div>
            <SlowestSpans instance={instanceRef} range={search.range} />
          </div>
          <div className="flex min-w-[360px] flex-[3_1_600px] flex-col">
            {traceId ? (
              <TraceDetail
                key={traceId}
                instance={instanceRef}
                traceId={traceId}
                compare={search.compare}
                onCompare={(on) => {
                  go({ compare: on });
                }}
              />
            ) : (
              <EmptyState title="Pick a trace">
                Traces of {instance?.display_name ?? instanceRef}: every run with its model calls, tool calls
                and steps.
              </EmptyState>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
