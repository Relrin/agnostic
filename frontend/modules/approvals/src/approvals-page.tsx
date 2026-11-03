// The approvals inbox: runs paused on a tool marked @approval, by status, with filters kept in the URL and the
// selected approval in an aside.
import {
  approvalsApprovalCountsOptions,
  approvalsListApprovalsOptions,
  describeError,
  notificationsMyPreferencesOptions,
  notificationsMyPreferencesQueryKey,
  notificationsUpdateMyPreferencesMutation,
  type ApprovalOut,
  type PersonalChannelName,
  type StatusName,
} from "@agnostic/api";
import {
  STALE_TIME,
  formatCount,
  formatRelative,
  toDate,
  useDebouncedCallback,
  withQueryFn,
} from "@agnostic/core";
import {
  ApiHint,
  Button,
  Countdown,
  DataTable,
  EmptyState,
  EntitySquare,
  ErrorState,
  Input,
  LoadingRows,
  Pager,
  Switch,
  Tabs,
  TabsList,
  TabsTrigger,
  Tooltip,
  cn,
  formatCountdown,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { RefreshCw, Search } from "lucide-react";
import { useState } from "react";

import { ApprovalDetail } from "./approval-detail";
import {
  APPROVAL_TYPES,
  PAGE_SIZE,
  SOURCE_KINDS,
  STATUSES,
  STATUS_LABELS,
  formatAge,
  listQuery,
  readSearch,
  refreshApprovals,
  sourceName,
  toSearch,
  userLabel,
  type ApprovalSearch,
  type ApprovalType,
} from "./approvals-api";
import { FilterMenu, type FilterOption } from "./filter-menu";
import { RoutingSheet } from "./routing-sheet";

const EVENT = "approval.created";

/** "Notify me in Slack": the person's channels for new approvals, with or without Slack. */
function SlackToggle() {
  const client = useQueryClient();
  const preferences = useQuery({ ...withQueryFn(notificationsMyPreferencesOptions()), retry: false });
  const update = useMutation({
    ...notificationsUpdateMyPreferencesMutation(),
    onSuccess: (data) => {
      client.setQueryData(notificationsMyPreferencesQueryKey(), data);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  if (!preferences.isSuccess) return null;
  const data = preferences.data;
  const channels: PersonalChannelName[] = data.events.find((item) => item.event.name === EVENT)?.channels ?? [
    "in_app",
  ];
  const checked = channels.includes("slack");
  const toggle = (
    <div className="flex h-[34px] items-center rounded-button border border-border-strong px-3">
      <Switch
        label="Notify me in Slack"
        checked={checked}
        disabled={update.isPending || (!data.slack_available && !checked)}
        onCheckedChange={(next) => {
          const others = channels.filter((channel) => channel !== "slack");
          const base: PersonalChannelName[] = others.length ? others : ["in_app"];
          update.mutate({ body: { events: { [EVENT]: next ? [...base, "slack"] : base } } });
        }}
      />
    </div>
  );
  if (data.slack_available || checked) return toggle;
  return (
    <Tooltip content="Slack isn't connected for direct messages; an org admin adds it in Settings › Notifications.">
      <span className="inline-flex rounded-button">{toggle}</span>
    </Tooltip>
  );
}

function SourceCell({ row }: { row: ApprovalOut }) {
  const kind = row.source_kind ?? row.component_kind;
  return (
    <span className="flex items-center gap-2 text-fg-secondary">
      {kind === "agent" || kind === "team" || kind === "workflow" ? (
        <EntitySquare kind={kind} className="size-[7px]" />
      ) : (
        <span aria-hidden className="inline-block size-[7px] shrink-0 rounded-type bg-fg-muted" />
      )}
      <span className="truncate">
        {kind ?? "source"} · <code className="font-mono font-semibold text-fg">{sourceName(row)}</code>
      </span>
    </span>
  );
}

function lastColumn(status: StatusName): Column<ApprovalOut> {
  switch (status) {
    case "pending":
      return {
        id: "expires",
        header: "Expires",
        cell: (row) => {
          const date = toDate(row.expires_at);
          return date ? <Countdown target={date} /> : <span className="text-fg-muted">—</span>;
        },
      };
    case "approved":
    case "rejected":
      return {
        id: "resolved",
        header: "Resolved",
        cell: (row) => (
          <span className={status === "rejected" ? "text-danger" : "text-fg-secondary"}>
            {row.resolved_by_name ?? row.resolved_by ?? "—"} · {formatRelative(row.resolved_at)}
          </span>
        ),
      };
    case "expired":
      return {
        id: "expired",
        header: "Expired",
        cell: (row) => {
          const date = toDate(row.expires_at);
          return (
            <span className="text-fg-muted">{date ? `Expired ${formatCountdown(date)}` : "Expired"}</span>
          );
        },
      };
    case "cancelled":
      return {
        id: "cancelled",
        header: "Cancelled",
        cell: (row) => <span className="text-fg-muted">{formatRelative(row.resolved_at)}</span>,
      };
  }
}

function unique(values: readonly (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}

/** `/i/:instance/approvals?status=&tool=&type=&source=&user=&schedule=&q=&page=&approval=&intent=`. */
export function ApprovalsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const client = useQueryClient();
  const instance = params.instance ?? "";
  const state = readSearch(search);
  const go = (next: Partial<ApprovalSearch>) => {
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/approvals`,
      search: toSearch({ ...state, ...next }),
    });
  };
  /** A filter change starts over on page 1. */
  const filter = (next: Partial<ApprovalSearch>) => {
    go({ ...next, page: 1 });
  };

  const [query, setQuery] = useState(state.q ?? "");
  const searchLater = useDebouncedCallback((value: string) => {
    filter({ q: value.trim() || undefined });
  }, 300);

  const counts = useQuery({
    ...withQueryFn(approvalsApprovalCountsOptions({ path: { instance } })),
    enabled: Boolean(instance),
    staleTime: STALE_TIME.list,
  });
  const list = useQuery({
    ...withQueryFn(approvalsListApprovalsOptions({ path: { instance }, query: listQuery(state) })),
    enabled: Boolean(instance),
    staleTime: STALE_TIME.list,
    placeholderData: (previous) => previous,
  });
  const rows = list.data?.data ?? [];
  const total = list.data?.total ?? rows.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const sources: FilterOption[] = [
    ...SOURCE_KINDS.map((kind) => ({ value: kind, label: `Any ${kind}` })),
    ...unique(
      rows.map((row) => (row.source_kind && row.source_id ? `${row.source_kind}:${row.source_id}` : null)),
    ).map((value) => ({ value, label: value.replace(":", " · ") })),
  ];
  const users = unique(rows.map((row) => row.user_id)).map((value) => ({ value, label: value }));
  const schedules = unique(rows.map((row) => row.schedule_id)).map((value) => ({ value, label: value }));
  const hasFilters = Boolean(
    state.tool ?? state.type ?? state.source ?? state.user ?? state.schedule ?? state.q,
  );

  const columns: Column<ApprovalOut>[] = [
    {
      id: "tool",
      header: "Tool",
      cell: (row) => (
        <div className="flex flex-col gap-0.5">
          <button
            type="button"
            className="cursor-pointer self-start font-mono text-[13px] font-medium text-fg hover:underline"
            onClick={(event) => {
              event.stopPropagation();
              go({ approval: row.id, intent: undefined });
            }}
          >
            {row.tool_name ?? row.id}
          </button>
          <span className="font-mono text-[11.5px] text-fg-muted">
            {row.type} · {row.id}
          </span>
        </div>
      ),
    },
    { id: "source", header: "Source", cell: (row) => <SourceCell row={row} /> },
    {
      id: "user",
      header: "User",
      cell: (row) => <span className="font-mono text-[12.5px]">{userLabel(row)}</span>,
    },
    {
      id: "age",
      header: "Age",
      cell: (row) => <span className="tabular-nums">{formatAge(row.created_at)}</span>,
    },
    lastColumn(state.status),
  ];

  const footerText =
    state.status === "pending"
      ? `${formatCount(total)} waiting${list.data?.oldest_pending_at ? ` · oldest ${formatAge(list.data.oldest_pending_at)}` : ""}`
      : `Showing ${formatCount(rows.length)} of ${formatCount(total)}`;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto px-6 pt-5 pb-10">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex max-w-3xl flex-col gap-1">
            <h1 className="text-[22px] font-semibold tracking-tight">Approvals</h1>
            <p className="text-[13px] text-fg-secondary">
              Runs pause here when they call a tool marked <code className="font-mono">@approval</code>.
              Resolving needs <code className="font-mono">approvals:write</code>.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SlackToggle />
            <RoutingSheet instance={instance} />
            <Button
              variant="icon"
              size="34"
              aria-label="Refresh"
              className="border border-border-strong"
              onClick={() => {
                void refreshApprovals(client);
              }}
            >
              <RefreshCw aria-hidden className={cn(list.isFetching && "animate-spin")} />
            </Button>
          </div>
        </div>

        <Tabs
          value={state.status}
          onValueChange={(value) => {
            go({ status: value as StatusName, page: 1, approval: undefined, intent: undefined });
          }}
        >
          <TabsList>
            {STATUSES.map((status) => {
              const count = counts.data?.[status];
              return (
                <TabsTrigger
                  key={status}
                  value={status}
                  countTone={status === "pending" && count ? "warning" : "muted"}
                  {...(typeof count === "number" ? { count } : {})}
                >
                  {STATUS_LABELS[status]}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-[260px]">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-fg-muted"
            />
            <Input
              type="search"
              aria-label="Search tool, run or user"
              placeholder="Search tool, run or user"
              className="h-8 pl-8"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                searchLater(event.target.value);
              }}
            />
          </div>
          {state.tool && (
            <FilterMenu
              label="Tool"
              current={state.tool}
              options={[]}
              onSelect={(tool) => {
                filter({ tool });
              }}
            />
          )}
          <FilterMenu
            label="Type"
            current={state.type}
            options={APPROVAL_TYPES.map((type) => ({ value: type, label: type }))}
            onSelect={(type) => {
              filter({ type: type as ApprovalType | undefined });
            }}
          />
          <FilterMenu
            label="Source"
            current={state.source}
            options={sources}
            onSelect={(source) => {
              filter({ source });
            }}
          />
          <FilterMenu
            label="User"
            current={state.user}
            options={users}
            freeText={{ label: "user_id", placeholder: "Any user_id" }}
            onSelect={(user) => {
              filter({ user });
            }}
          />
          <FilterMenu
            label="Schedule"
            current={state.schedule}
            options={schedules}
            freeText={{ label: "schedule_id", placeholder: "Any schedule_id" }}
            onSelect={(schedule) => {
              filter({ schedule });
            }}
          />
          {hasFilters && (
            <Button
              variant="ghost"
              size="30"
              onClick={() => {
                setQuery("");
                go({
                  tool: undefined,
                  type: undefined,
                  source: undefined,
                  user: undefined,
                  schedule: undefined,
                  q: undefined,
                  page: 1,
                });
              }}
            >
              Clear filters
            </Button>
          )}
        </div>

        {list.isError ? (
          <ErrorState {...describeError(list.error)} onRetry={() => void list.refetch()} />
        ) : list.isPending ? (
          <LoadingRows label="Loading approvals" />
        ) : rows.length === 0 ? (
          <EmptyState
            title={
              hasFilters
                ? `No ${state.status} approvals match.`
                : state.status === "pending"
                  ? "Nothing is waiting for a decision."
                  : `No ${state.status} approvals.`
            }
          >
            {state.status === "pending"
              ? "Runs that call a tool marked @approval pause here until someone approves or rejects them."
              : "Resolved, rejected and expired requests stay here for the record."}
          </EmptyState>
        ) : (
          <div className="min-w-0 overflow-x-auto">
            <div className="min-w-[640px]">
              <DataTable
                label="Approvals"
                columns={columns}
                rows={rows}
                rowKey={(row) => row.id}
                selectedKey={state.approval ?? ""}
                onRowClick={(row) => {
                  go({ approval: row.id, intent: undefined });
                }}
                footer={
                  <>
                    <span className="mr-auto flex flex-wrap gap-x-2">
                      <span>{footerText}</span>
                      {list.data.truncated && (
                        <span className="text-warning">Only the newest approvals were searched.</span>
                      )}
                    </span>
                    {pages > 1 && (
                      <Pager
                        summary={`Page ${String(state.page)} of ${String(pages)}`}
                        onPrevious={
                          state.page > 1
                            ? () => {
                                go({ page: state.page - 1 });
                              }
                            : undefined
                        }
                        onNext={
                          state.page < pages
                            ? () => {
                                go({ page: state.page + 1 });
                              }
                            : undefined
                        }
                      />
                    )}
                    <ApiHint
                      call={`GET /instances/${instance}/approvals?status=${state.status}`}
                      scope="approvals:read"
                    >
                      <code className="font-mono text-[11.5px]">GET /approvals?status={state.status}</code>
                    </ApiHint>
                  </>
                }
              />
            </div>
          </div>
        )}
      </div>
      {state.approval && (
        <ApprovalDetail
          key={state.approval}
          instance={instance}
          approvalId={state.approval}
          intent={state.intent}
          onClose={() => {
            go({ approval: undefined, intent: undefined });
          }}
        />
      )}
    </div>
  );
}
