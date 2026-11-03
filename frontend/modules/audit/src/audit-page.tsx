// The audit log: every action and access decision, with saved views, filters kept in the URL, the selected event in
// an aside (`?event=`), export, and the SIEM streaming status.
import {
  auditGetPolicyOptions,
  auditListActionsOptions,
  auditListActorsOptions,
  auditListEventsInfiniteOptions,
  auditListViewsOptions,
  describeError,
  type AuditEventOut,
  type InstanceOut,
} from "@agnostic/api";
import {
  STALE_TIME,
  formatCount,
  useCan,
  useDebouncedCallback,
  useInstances,
  withQueryFn,
} from "@agnostic/core";
import {
  Avatar,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  PageIntro,
  cn,
  type Column,
} from "@agnostic/ui";
import { skipToken, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Download, Search } from "lucide-react";
import { useState } from "react";

import {
  ACTOR_KINDS,
  ACTOR_KIND_LABELS,
  DECISIONS,
  DECISION_LABELS,
  DEFAULT_RETENTION_DAYS,
  PAGE_SIZE,
  RANGE_PRESETS,
  SOURCES,
  SOURCE_LABELS,
  avatarKind,
  describeRange,
  eventsQuery,
  filterSummary,
  filtersOf,
  fromLocalInput,
  hasFilters,
  isMachine,
  readSearch,
  scopeLine,
  toLocalInput,
  toSearch,
  utcDay,
  utcTime,
  type ActorKind,
  type AuditFilters,
  type AuditSearch,
} from "./audit-api";
import { EventDetail } from "./event-detail";
import { ExportDialog } from "./export-dialog";
import { FilterMenu, type FilterOption } from "./filter-menu";
import { OverflowMenu, SIEM_SETTINGS, SiemPill } from "./header-actions";
import { SavedViewsBar, activeView } from "./saved-views";

const PATH = "/access/audit";
const KIND_PREFIX = "kind:";

const ENV_TEXT: Record<InstanceOut["env_tag"], string> = {
  production: "text-warning",
  staging: "text-info",
  development: "text-fg-secondary",
};
const ENV_DOT: Record<InstanceOut["env_tag"], string> = {
  production: "bg-warning",
  staging: "bg-info",
  development: "bg-fg-muted",
};

function DecisionCell({ event }: { event: AuditEventOut }) {
  const line = scopeLine(event);
  return (
    <span className="flex flex-col items-start gap-1">
      {event.decision === "allowed" ? (
        <span className="rounded-type bg-accent/12 px-1.5 py-px font-mono text-[10.5px] font-semibold tracking-[0.06em] text-accent">
          ALLOWED
        </span>
      ) : event.decision === "denied" ? (
        <span className="rounded-type bg-danger/12 px-1.5 py-px font-mono text-[10.5px] font-semibold tracking-[0.06em] text-danger">
          DENIED
        </span>
      ) : (
        <span className="text-fg-muted">—</span>
      )}
      {line && <span className="font-mono text-[11px] break-all text-fg-muted">{line}</span>}
    </span>
  );
}

function DateRangeForm({
  since,
  until,
  onApply,
}: {
  since: string | undefined;
  until: string | undefined;
  onApply: (since: string | undefined, until: string | undefined) => void;
}) {
  const [from, setFrom] = useState(toLocalInput(since));
  const [to, setTo] = useState(toLocalInput(until));
  return (
    <form
      className="flex flex-col gap-2 border-t border-border-subtle p-1 pt-2"
      onSubmit={(event) => {
        event.preventDefault();
        onApply(fromLocalInput(from), fromLocalInput(to));
      }}
    >
      <span className="text-[11.5px] text-fg-muted">Custom range (UTC)</span>
      <Input
        type="datetime-local"
        aria-label="From (UTC)"
        className="h-8"
        value={from}
        onChange={(event) => {
          setFrom(event.target.value);
        }}
      />
      <Input
        type="datetime-local"
        aria-label="To (UTC)"
        className="h-8"
        value={to}
        onChange={(event) => {
          setTo(event.target.value);
        }}
      />
      <Button type="submit" size="28" disabled={!from && !to}>
        Apply range
      </Button>
    </form>
  );
}

/** `/access/audit?q=&actor=&actor_kind=&action=&decision=&instance=&resource=&source=&since=&until=&event=`. */
export function AuditPage() {
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const state = readSearch(search);
  const filters = filtersOf(state);
  const go = (next: AuditSearch) => {
    void navigate({ to: PATH, search: toSearch(next) });
  };
  const patch = (changes: Partial<AuditFilters>) => {
    go({ ...state, ...changes });
  };

  const [query, setQuery] = useState(state.q ?? "");
  const searchLater = useDebouncedCallback((value: string) => {
    patch({ q: value.trim() || undefined });
  }, 300);
  /** A saved view (or "All events") replaces every filter. */
  const apply = (next: AuditFilters) => {
    setQuery(next.q ?? "");
    go({ ...next, event: state.event });
  };
  const [exporting, setExporting] = useState(false);

  const instances = useInstances();
  const canExport = useCan("audit:export").allowed === true;
  const canSettings = useCan("settings:write").allowed === true;
  const canOrgWrite = useCan("org:write").allowed === true;

  const options = auditListEventsInfiniteOptions({ query: { limit: PAGE_SIZE, ...eventsQuery(filters) } });
  const events = useInfiniteQuery({
    ...options,
    queryFn: options.queryFn ?? skipToken,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: STALE_TIME.list,
  });
  const views = useQuery({
    ...withQueryFn(auditListViewsOptions()),
    retry: false,
    staleTime: STALE_TIME.list,
  });
  const actors = useQuery({
    ...withQueryFn(auditListActorsOptions({ query: { limit: 100 } })),
    retry: false,
    staleTime: STALE_TIME.config,
  });
  const actions = useQuery({
    ...withQueryFn(auditListActionsOptions()),
    retry: false,
    staleTime: STALE_TIME.config,
  });
  const policy = useQuery({
    ...withQueryFn(auditGetPolicyOptions()),
    retry: false,
    staleTime: STALE_TIME.config,
  });
  const retention = policy.data?.hot_retention_days ?? DEFAULT_RETENTION_DAYS;

  const rows = events.data?.pages.flatMap((page) => page.data) ?? [];
  const instanceOf = (id: string | null) => (id ? instances.data?.find((item) => item.id === id) : undefined);
  const actorName = (id: string) => actors.data?.find((actor) => actor.id === id)?.display ?? id;
  const instanceName = (id: string) => instanceOf(id)?.slug ?? id;
  const summary = filterSummary(filters, { actor: actorName, instance: instanceName });
  const filtered = hasFilters(filters);
  const savedViews = views.data ?? [];
  const current = activeView(savedViews, filters);
  const allCount = !filtered && events.isSuccess && !events.hasNextPage ? rows.length : undefined;
  const open = (id: string) => {
    go({ ...state, event: id });
  };

  const actorOptions: FilterOption[] = [
    ...ACTOR_KINDS.filter((kind) => kind !== "anonymous").map((kind) => ({
      value: `${KIND_PREFIX}${kind}`,
      label: ACTOR_KIND_LABELS[kind],
    })),
    ...(actors.data ?? []).map((actor) => ({
      value: actor.id,
      label: actor.display,
      mono: isMachine(actor.kind),
      meta: formatCount(actor.count),
      icon: <Avatar id={actor.id} name={actor.display} kind={avatarKind(actor.kind)} size={18} />,
    })),
  ];
  const actorCurrent = state.actor ?? (state.actor_kind ? `${KIND_PREFIX}${state.actor_kind}` : undefined);
  const actorShown = state.actor
    ? actorName(state.actor)
    : state.actor_kind
      ? ACTOR_KIND_LABELS[state.actor_kind as ActorKind]
      : undefined;

  const vocabulary = (actions.data ?? []).map((item) => item.action);
  const prefixes = [...new Set(vocabulary.map((action) => action.split(".")[0]).filter(Boolean))].map(
    (prefix) => `${String(prefix)}.*`,
  );
  const actionOptions: FilterOption[] = [
    ...prefixes.map((value) => ({ value, label: value, mono: true, meta: "any" })),
    ...vocabulary.map((value) => ({ value, label: value, mono: true })),
  ];

  const columns: Column<AuditEventOut>[] = [
    {
      id: "time",
      header: "UTC",
      className: "w-[92px]",
      cell: (row) => (
        <span className="flex flex-col font-mono whitespace-nowrap">
          <span className="text-[12.5px]">{utcTime(row.occurred_at)}</span>
          <span className="text-[11px] text-fg-muted">{utcDay(row.occurred_at)}</span>
        </span>
      ),
    },
    {
      id: "actor",
      header: "Actor",
      cell: (row) => (
        <span className="flex min-w-0 items-center gap-2">
          <Avatar id={row.actor.id} name={row.actor.display} kind={avatarKind(row.actor.kind)} size={22} />
          <span className={cn("truncate", isMachine(row.actor.kind) && "font-mono text-[12px]")}>
            {row.actor.display}
          </span>
        </span>
      ),
    },
    {
      id: "action",
      header: "Action",
      cell: (row) => (
        <span className="flex max-w-[320px] min-w-0 flex-col items-start gap-0.5">
          <button
            type="button"
            className="cursor-pointer font-mono text-[12.5px] font-medium text-fg hover:underline"
            onClick={(click) => {
              click.stopPropagation();
              open(row.id);
            }}
          >
            {row.action}
          </button>
          <span className="line-clamp-1 text-[12px] text-fg-muted" title={row.summary}>
            {row.summary}
          </span>
        </span>
      ),
    },
    {
      id: "resource",
      header: "Resource",
      cell: (row) => {
        const resource = row.resource_display ?? row.resource_id ?? "—";
        return (
          <span className="block max-w-[220px] truncate font-mono text-[12px]" title={resource}>
            {resource}
          </span>
        );
      },
    },
    {
      id: "where",
      header: "Where",
      cell: (row) => {
        const instance = instanceOf(row.instance_id);
        if (!row.instance_id) return <span className="font-mono text-[12px] text-fg-muted">org</span>;
        return (
          <span
            className={cn(
              "font-mono text-[12px]",
              instance ? ENV_TEXT[instance.env_tag] : "text-fg-secondary",
            )}
          >
            {instance?.slug ?? row.instance_id}
          </span>
        );
      },
    },
    { id: "decision", header: "Decision", cell: (row) => <DecisionCell event={row} /> },
  ];

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto px-7 pt-5 pb-10">
        <PageIntro
          title="Audit log"
          actions={
            <div className="flex flex-wrap items-center justify-end gap-2">
              <SiemPill />
              {canExport && (
                <Button
                  variant="outline"
                  size="34"
                  onClick={() => {
                    setExporting(true);
                  }}
                >
                  <Download aria-hidden />
                  Export view
                </Button>
              )}
              {canSettings && (
                <Button asChild variant="secondary" size="34">
                  <Link to={SIEM_SETTINGS}>SIEM settings</Link>
                </Button>
              )}
              {rows.some((row) => row.hash) && (
                <OverflowMenu since={filters.since} until={filters.until} onOpenEvent={open} />
              )}
            </div>
          }
        >
          Every action and access decision across the control plane and your AgentOS instances: who did what,
          to which resource, and which scope decided it.
        </PageIntro>

        <SavedViewsBar
          views={savedViews}
          filters={filters}
          allCount={allCount}
          summary={summary}
          canShare={canExport || canOrgWrite}
          onApply={apply}
        />

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-[280px]">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-fg-muted"
            />
            <Input
              type="search"
              aria-label="Search resource, request id or IP"
              placeholder="Search resource, request id or IP"
              className="h-8 pl-8"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                searchLater(event.target.value);
              }}
            />
          </div>
          <FilterMenu
            label="Actor"
            current={actorCurrent}
            shown={actorShown}
            options={actorOptions}
            searchable
            onSelect={(value) => {
              if (value?.startsWith(KIND_PREFIX))
                patch({ actor: undefined, actor_kind: value.slice(KIND_PREFIX.length) });
              else patch({ actor: value, actor_kind: undefined });
            }}
          />
          <FilterMenu
            label="Action"
            current={state.action}
            options={actionOptions}
            freeText={{ label: "Action or prefix", placeholder: "members.update or gateway.*" }}
            onSelect={(action) => {
              patch({ action });
            }}
          />
          <FilterMenu
            label="Decision"
            current={state.decision}
            options={DECISIONS.map((value) => ({ value, label: DECISION_LABELS[value] }))}
            onSelect={(decision) => {
              patch({ decision });
            }}
          />
          <FilterMenu
            label="Instance"
            current={state.instance}
            shown={state.instance ? instanceName(state.instance) : undefined}
            options={(instances.data ?? []).map((instance) => ({
              value: instance.id,
              label: instance.slug,
              mono: true,
              icon: (
                <span
                  aria-hidden
                  className={cn("size-1.5 shrink-0 rounded-full", ENV_DOT[instance.env_tag])}
                />
              ),
            }))}
            onSelect={(instance) => {
              patch({ instance });
            }}
          />
          <FilterMenu
            label="Date"
            current={state.since || state.until ? "range" : undefined}
            shown={describeRange(state.since, state.until)}
            listCurrent={false}
            options={RANGE_PRESETS.map((preset) => ({ value: preset.id, label: preset.label }))}
            onSelect={(id) => {
              const preset = RANGE_PRESETS.find((item) => item.id === id);
              patch({ since: preset?.since(new Date()).toISOString(), until: undefined });
            }}
          >
            {(close) => (
              <DateRangeForm
                since={state.since}
                until={state.until}
                onApply={(since, until) => {
                  patch({ since, until });
                  close();
                }}
              />
            )}
          </FilterMenu>
          <FilterMenu
            label="Source"
            current={state.source}
            options={SOURCES.map((value) => ({ value, label: SOURCE_LABELS[value] }))}
            onSelect={(source) => {
              patch({ source });
            }}
          />
          {state.resource && (
            <FilterMenu
              label="Resource"
              current={state.resource}
              options={[]}
              onSelect={(resource) => {
                patch({ resource });
              }}
            />
          )}
          {filtered && (
            <Button
              variant="ghost"
              size="30"
              onClick={() => {
                apply({});
              }}
            >
              Clear filters
            </Button>
          )}
        </div>

        {events.isError ? (
          <ErrorState {...describeError(events.error)} onRetry={() => void events.refetch()} />
        ) : events.isPending ? (
          <LoadingRows rows={8} label="Loading events" />
        ) : rows.length === 0 ? (
          <EmptyState title="No events match">
            {filtered ? "Try a broader filter or another saved view." : "Nothing has been recorded yet."}
          </EmptyState>
        ) : (
          <div className="min-w-0 overflow-x-auto">
            <div className="min-w-[820px] text-[12.5px]">
              <DataTable
                label="Audit events"
                columns={columns}
                rows={rows}
                rowKey={(row) => row.id}
                selectedKey={state.event ?? ""}
                onRowClick={(row) => {
                  open(row.id);
                }}
                footer={
                  <>
                    <span className="mr-auto">
                      {formatCount(rows.length)}
                      {events.hasNextPage ? "+" : ""} events ·{" "}
                      {current?.name ?? (filtered ? "Filtered" : "All events")}
                    </span>
                    {events.hasNextPage && (
                      <Button
                        variant="ghost"
                        size="28"
                        disabled={events.isFetchingNextPage}
                        onClick={() => void events.fetchNextPage()}
                      >
                        {events.isFetchingNextPage ? "Loading…" : "Load more"}
                      </Button>
                    )}
                    <span>Kept {formatCount(retention)} days · append-only</span>
                  </>
                }
              />
            </div>
          </div>
        )}
      </div>
      {state.event && (
        <EventDetail
          key={state.event}
          eventId={state.event}
          loaded={rows.find((row) => row.id === state.event)}
          listSettled={!events.isPending}
          instances={instances.data}
          onClose={() => {
            go({ ...state, event: undefined });
          }}
        />
      )}
      <ExportDialog open={exporting} onOpenChange={setExporting} filters={filters} summary={summary} />
    </div>
  );
}
