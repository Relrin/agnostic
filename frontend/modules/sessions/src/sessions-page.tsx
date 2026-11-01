import { describeError, AgentOSHttpError, gatewayJson, type AgentOS } from "@agnostic/api";
import {
  findInstance,
  formatCount,
  formatRelative,
  useCan,
  useComponents,
  useInstances,
  useMe,
  useSessions,
  ORG_ROLE_LABELS,
  type SessionsQuery,
} from "@agnostic/core";
import {
  Button,
  Callout,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  Pager,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  type Column,
} from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Lock, RefreshCw, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { SessionDetailPanel, TABS, type Tab } from "./session-detail";

type TypeFilter = "all" | "agent" | "team" | "workflow";
type Sort = "updated" | "created" | "created_asc";
type Row = AgentOS.SessionSchema;

const TYPES: readonly { value: TypeFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "agent", label: "Agent" },
  { value: "team", label: "Team" },
  { value: "workflow", label: "Workflow" },
];
const SORTS: Record<Sort, { label: string; by: string; order: "asc" | "desc" }> = {
  updated: { label: "Updated, newest", by: "updated_at", order: "desc" },
  created: { label: "Created, newest", by: "created_at", order: "desc" },
  created_asc: { label: "Created, oldest", by: "created_at", order: "asc" },
};
const PAGE_SIZE = 20;
/** AgentOS session ids are UUIDs; a pasted one is looked up directly. */
const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$|^ses_[\w-]+$/i;

type Filters = {
  type: TypeFilter;
  component?: string | undefined;
  user?: string | undefined;
  q?: string | undefined;
  sort: Sort;
  tab: Tab;
  page: number;
};

function readFilters(search: Record<string, unknown>): Filters {
  const text = (key: string) => (typeof search[key] === "string" && search[key] ? search[key] : undefined);
  const type = text("type");
  const sort = text("sort");
  const tab = text("tab");
  const page = typeof search.page === "number" ? search.page : Number(text("page") ?? 1);
  return {
    type: TYPES.some((item) => item.value === type) ? (type as TypeFilter) : "all",
    component: text("component"),
    user: text("user"),
    q: text("q"),
    sort: sort && sort in SORTS ? (sort as Sort) : "updated",
    tab: TABS.some((item) => item.id === tab) ? (tab as Tab) : "chat",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

function componentOf(row: Row): string {
  return row.workflow_id ?? row.team_id ?? row.agent_id ?? "—";
}

function flag(row: Row): string | undefined {
  const state = row.session_state as { status?: unknown } | null | undefined;
  return typeof state?.status === "string" ? state.status : undefined;
}

function columns(): Column<Row>[] {
  return [
    {
      id: "session",
      header: "Session",
      cell: (row) => (
        <div className="flex min-w-0 flex-col">
          <span className="truncate">{row.session_name || row.session_id}</span>
          <span className="flex items-center gap-1.5 font-mono text-[11.5px] text-fg-muted">
            {row.session_id}
            {flag(row) === "paused" && <span className="text-warning">paused</span>}
            {flag(row) === "error" && <span className="text-danger">error</span>}
          </span>
        </div>
      ),
    },
    {
      id: "component",
      header: "Component",
      cell: (row) => <span className="font-mono text-[12.5px]">{componentOf(row)}</span>,
    },
    {
      id: "user",
      header: "user_id",
      cell: (row) => <span className="font-mono text-[12.5px]">{row.user_id ?? "—"}</span>,
    },
    {
      id: "tokens",
      header: "Tokens",
      align: "right",
      cell: (row) => formatCount(typeof row.total_tokens === "number" ? row.total_tokens : undefined),
    },
    {
      id: "updated",
      header: "Updated",
      cell: (row) => (
        <span className="text-fg-muted">{formatRelative(row.updated_at ?? row.created_at)}</span>
      ),
    },
  ];
}

/** `/i/:instance/sessions/:sessionId?` with `?type=&component=&user=&q=&sort=&tab=&page=` (design spec A §8). */
export function SessionsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instanceRef = params.instance ?? "";
  const sessionId = params.sessionId;
  const filters = readFilters(search);
  const [query, setQuery] = useState(filters.q ?? "");
  const deferredQuery = useDeferredValue(query.trim());
  const instances = useInstances();
  const instance = findInstance(instances.data, instanceRef);
  const me = useMe();
  const isAdmin = useCan("agent_os:admin", instanceRef).allowed === true;

  const agents = useComponents(instanceRef, "agents");
  const teams = useComponents(instanceRef, "teams");
  const workflows = useComponents(instanceRef, "workflows");
  const componentOptions = [
    ...(filters.type === "all" || filters.type === "agent" ? (agents.data ?? []) : []),
    ...(filters.type === "all" || filters.type === "team" ? (teams.data ?? []) : []),
    ...(filters.type === "all" || filters.type === "workflow" ? (workflows.data ?? []) : []),
  ];

  const go = (next: Partial<Filters>, session: string | undefined = sessionId) => {
    const merged = { ...filters, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instanceRef)}/sessions${session ? `/${encodeURIComponent(session)}` : ""}`,
      search: {
        ...(merged.type !== "all" ? { type: merged.type } : {}),
        ...(merged.component ? { component: merged.component } : {}),
        ...(merged.user ? { user: merged.user } : {}),
        ...(merged.q ? { q: merged.q } : {}),
        ...(merged.sort !== "updated" ? { sort: merged.sort } : {}),
        ...(merged.tab !== "chat" ? { tab: merged.tab } : {}),
        ...(merged.page > 1 ? { page: merged.page } : {}),
      },
    });
  };

  const looksLikeId = SESSION_ID.test(deferredQuery);
  const sessionsQuery: SessionsQuery = {
    type: filters.type === "all" ? undefined : filters.type,
    componentId: filters.component,
    userId: filters.user,
    name: looksLikeId ? undefined : deferredQuery || undefined,
    page: filters.page,
    limit: PAGE_SIZE,
    sortBy: SORTS[filters.sort].by,
    sortOrder: SORTS[filters.sort].order,
  };
  const sessions = useSessions(instanceRef, sessionsQuery, !looksLikeId);
  const byId = useQuery({
    queryKey: [instanceRef, "agentos", "session-lookup", deferredQuery],
    queryFn: looksLikeId
      ? async (): Promise<Row[]> => {
          try {
            return [await gatewayJson<Row>(instanceRef, `sessions/${encodeURIComponent(deferredQuery)}`)];
          } catch (error) {
            if (error instanceof AgentOSHttpError && error.status === 404) return [];
            throw error;
          }
        }
      : skipToken,
    retry: false,
  });

  const rows: readonly Row[] = looksLikeId ? (byId.data ?? []) : (sessions.data?.data ?? []);
  const meta = sessions.data?.meta;
  const total = looksLikeId ? rows.length : (meta?.total_count ?? rows.length);
  const totalPages = meta?.total_pages ?? 1;
  const loading = looksLikeId ? byId.isPending : sessions.isPending;
  const error = looksLikeId ? byId.error : sessions.error;
  const roleLabel = me.data?.org_role ? ORG_ROLE_LABELS[me.data.org_role] : "an Instance admin";

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto px-8 pt-6 pb-10">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h1 className="text-[22px] font-semibold tracking-tight">Sessions</h1>
            <p className="text-[13px] text-fg-secondary">
              {meta ? `${formatCount(meta.total_count)} sessions. ` : ""}A session groups the runs that share
              one <code className="font-mono">session_id</code>.
            </p>
          </div>
          <Button
            variant="outline"
            size="32"
            disabled={sessions.isFetching}
            onClick={() => {
              void sessions.refetch();
            }}
          >
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        </div>

        {instance?.user_isolation && (
          <Callout tone="info" title="User isolation is on">
            <span className="inline-flex items-start gap-1.5">
              <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                User isolation is on for {instance.display_name}. Members without admin access only see
                sessions whose <code className="font-mono">user_id</code> matches their own;{" "}
                {isAdmin ? `you're seeing all users as ${roleLabel}.` : "you're seeing your own sessions."}
              </span>
            </span>
          </Callout>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl
            label="Session type"
            value={filters.type}
            onValueChange={(value) => {
              go({ type: value, component: undefined, page: 1 });
            }}
            options={TYPES}
          />
          <div className="relative w-72">
            <Search
              className="pointer-events-none absolute top-2 left-2.5 size-4 text-fg-muted"
              aria-hidden
            />
            <Input
              aria-label="Search name or session_id"
              placeholder="Search name or session_id"
              className="pl-8"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              onBlur={() => {
                if ((filters.q ?? "") !== query.trim()) go({ q: query.trim() || undefined, page: 1 });
              }}
            />
          </div>
          <Select
            value={filters.component ?? "any"}
            onValueChange={(value) => {
              go({ component: value === "any" ? undefined : value, page: 1 });
            }}
          >
            <SelectTrigger aria-label="Component" className="h-8 w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Component: Any</SelectItem>
              {componentOptions.map((item) => (
                <SelectItem key={`${item.family}:${item.id}`} value={item.id}>
                  {item.id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            aria-label="User"
            placeholder="User: Any"
            mono
            className="h-8 w-40"
            defaultValue={filters.user ?? ""}
            onBlur={(event) => {
              const value = event.target.value.trim();
              if ((filters.user ?? "") !== value) go({ user: value || undefined, page: 1 });
            }}
          />
          <Select
            value={filters.sort}
            onValueChange={(value) => {
              go({ sort: value as Sort, page: 1 });
            }}
          >
            <SelectTrigger aria-label="Sort" className="h-8 w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(SORTS) as Sort[]).map((value) => (
                <SelectItem key={value} value={value}>
                  Sort: {SORTS[value].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {error ? (
          <ErrorState
            {...describeError(error)}
            onRetry={() => void (looksLikeId ? byId.refetch() : sessions.refetch())}
          />
        ) : loading ? (
          <LoadingRows label="Loading sessions" />
        ) : rows.length === 0 ? (
          <EmptyState
            title={
              deferredQuery || filters.component || filters.user
                ? "No sessions match these filters."
                : "No sessions yet."
            }
            action={
              <Button asChild variant="primary" size="32">
                <Link to={`/i/${encodeURIComponent(instanceRef)}/chat`}>Open Chat</Link>
              </Button>
            }
          >
            Sessions appear when someone chats with an agent.
          </EmptyState>
        ) : (
          <DataTable
            label="Sessions"
            columns={columns()}
            rows={rows}
            rowKey={(row) => row.session_id}
            selectedKey={sessionId}
            onRowClick={(row) => {
              go({}, row.session_id);
            }}
            footer={
              <Pager
                summary={`${String(rows.length)} of ${formatCount(total)}`}
                onPrevious={
                  filters.page > 1
                    ? () => {
                        go({ page: filters.page - 1 });
                      }
                    : undefined
                }
                onNext={
                  filters.page < totalPages
                    ? () => {
                        go({ page: filters.page + 1 });
                      }
                    : undefined
                }
              />
            }
          />
        )}
      </div>

      {sessionId && (
        <SessionDetailPanel
          instance={instanceRef}
          sessionId={sessionId}
          tab={filters.tab}
          onTab={(tab) => {
            go({ tab });
          }}
          onClose={() => {
            go({ tab: "chat" }, undefined);
          }}
          onForked={(forked) => {
            go({ tab: "chat" }, forked);
          }}
          onDeleted={() => {
            go({ tab: "chat" }, undefined);
          }}
        />
      )}
    </div>
  );
}
