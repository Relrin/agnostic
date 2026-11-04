import { contextLearningCountsOptions, describeError } from "@agnostic/api";
import { PermissionGate, formatCount, formatRelative, useComponents } from "@agnostic/core";
import {
  Button,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  Pager,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsList,
  TabsTrigger,
  cn,
} from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ArrowUpRight, Plus } from "lucide-react";

import { DataSubjectDialog, NewRecordDialog } from "./dialogs";
import { LearningDetail } from "./learning-detail";
import {
  LEARNING_TYPES,
  summary,
  useLearnings,
  type LearningFilters,
  type LearningType,
} from "./learnings-api";

type Filters = LearningFilters & { record?: string | undefined };

function readFilters(search: Record<string, unknown>): Filters {
  const text = (key: string) => (typeof search[key] === "string" && search[key] ? search[key] : undefined);
  const type = text("type");
  const page = typeof search.page === "number" ? search.page : Number(text("page") ?? 1);
  return {
    type: LEARNING_TYPES.includes(type as LearningType) ? (type as LearningType) : "user_profile",
    user: text("user"),
    agent: text("agent"),
    namespace: text("namespace"),
    entityType: text("entityType"),
    record: text("record"),
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

/** `/i/:instance/learnings?type=&user=&agent=&namespace=&entityType=&record=&page=` (design spec B §3). */
export function LearningsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instance = params.instance ?? "";
  const filters = readFilters(search);
  const go = (next: Partial<Filters>) => {
    const merged = { ...filters, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/learnings`,
      search: Object.fromEntries(
        Object.entries(merged).filter(
          ([key, value]) =>
            value && !(key === "page" && value === 1) && !(key === "type" && value === "user_profile"),
        ),
      ),
    });
  };

  const countsOptions = contextLearningCountsOptions({
    path: { instance },
    query: {
      user_id: filters.user ?? null,
      agent_id: filters.agent ?? null,
      namespace: filters.namespace ?? null,
    },
  });
  const counts = useQuery({
    ...countsOptions,
    queryFn: instance ? (countsOptions.queryFn ?? skipToken) : skipToken,
  });
  const agents = useComponents(instance, "agents");
  const learnings = useLearnings(instance, filters);
  const rows = learnings.data?.data ?? [];
  const total = learnings.data?.meta.total_count ?? rows.length;
  const totalPages = learnings.data?.meta.total_pages ?? 1;
  const selected = rows.find((row) => row.learning_id === filters.record) ?? rows[0];

  return (
    <div className="flex h-full min-h-0 flex-col gap-5 overflow-y-auto px-6 pt-5 pb-10">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex max-w-3xl flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-tight">Learnings</h1>
          <p className="text-[13px] text-fg-secondary">
            What agents write to their learning stores between runs. Learned knowledge is stored in{" "}
            <Link
              to={`/i/${encodeURIComponent(instance)}/knowledge`}
              className="text-info hover:text-info-hover"
            >
              Knowledge
            </Link>
            , not here.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <PermissionGate scope="learnings:delete" instance={instance}>
            <DataSubjectDialog />
          </PermissionGate>
          <PermissionGate scope="learnings:write" instance={instance}>
            <NewRecordDialog
              instance={instance}
              type={filters.type}
              onCreated={(record) => {
                go({ type: record.learning_type as LearningType, record: record.learning_id, page: 1 });
              }}
              trigger={
                <Button variant="outline" size="32">
                  <Plus aria-hidden />
                  New record
                </Button>
              }
            />
          </PermissionGate>
        </div>
      </div>

      <Tabs
        value={filters.type}
        onValueChange={(value) => {
          go({ type: value as LearningType, record: undefined, page: 1, entityType: undefined });
        }}
      >
        <div className="flex flex-wrap items-end justify-between gap-2 border-b border-border-subtle">
          <TabsList panels={false} className="border-0">
            {LEARNING_TYPES.map((type) => {
              const count = counts.data?.counts[type];
              return (
                <TabsTrigger
                  key={type}
                  value={type}
                  className="font-mono text-[12.5px]"
                  {...(typeof count === "number" ? { count } : {})}
                >
                  {type}
                </TabsTrigger>
              );
            })}
          </TabsList>
          <Link
            to={`/i/${encodeURIComponent(instance)}/knowledge`}
            className="mb-2 inline-flex items-center gap-1 font-mono text-[12.5px] text-fg-muted hover:text-fg"
          >
            learned_knowledge
            <ArrowUpRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      </Tabs>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="user_id"
          placeholder="user_id"
          mono
          className="h-8 w-44"
          defaultValue={filters.user ?? ""}
          key={`user:${filters.user ?? ""}`}
          onBlur={(event) => {
            const value = event.target.value.trim();
            if ((filters.user ?? "") !== value) go({ user: value || undefined, record: undefined, page: 1 });
          }}
        />
        <Select
          value={filters.agent ?? "any"}
          onValueChange={(value) => {
            go({ agent: value === "any" ? undefined : value, record: undefined, page: 1 });
          }}
        >
          <SelectTrigger aria-label="Agent" className="h-8 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="any">Any agent</SelectItem>
            {(agents.data ?? []).map((agent) => (
              <SelectItem key={agent.id} value={agent.id}>
                {agent.id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          aria-label="Namespace"
          placeholder="Any namespace"
          mono
          className="h-8 w-40"
          defaultValue={filters.namespace ?? ""}
          key={`ns:${filters.namespace ?? ""}`}
          onBlur={(event) => {
            const value = event.target.value.trim();
            if ((filters.namespace ?? "") !== value)
              go({ namespace: value || undefined, record: undefined, page: 1 });
          }}
        />
        {filters.type === "entity_memory" && (
          <Input
            aria-label="entity_type"
            placeholder="Any entity_type"
            mono
            className="h-8 w-40"
            defaultValue={filters.entityType ?? ""}
            key={`entity:${filters.entityType ?? ""}`}
            onBlur={(event) => {
              const value = event.target.value.trim();
              if ((filters.entityType ?? "") !== value)
                go({ entityType: value || undefined, record: undefined, page: 1 });
            }}
          />
        )}
        <span className="ml-auto text-[12px] text-fg-muted">Sorted by updated_at, newest first</span>
      </div>

      {learnings.error ? (
        <ErrorState {...describeError(learnings.error)} onRetry={() => void learnings.refetch()} />
      ) : learnings.isPending ? (
        <LoadingRows label="Loading learnings" />
      ) : rows.length === 0 ? (
        <EmptyState
          title={`No ${filters.type} records${filters.user || filters.agent || filters.namespace ? " match" : " yet"}`}
        >
          Agents with a learning machine write these between runs.
        </EmptyState>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <div className="flex min-w-0 flex-[2_1_380px] flex-col overflow-hidden rounded-card border border-border bg-surface">
            <ul aria-label="Records" className="flex flex-col">
              {rows.map((row) => {
                const active = row.learning_id === selected?.learning_id;
                const owner =
                  row.learning_type === "entity_memory"
                    ? `${row.entity_type ?? "entity"} · ${row.entity_id ?? "—"}`
                    : (row.user_id ?? "shared");
                return (
                  <li key={row.learning_id} className="border-b border-divider-row last:border-0">
                    <button
                      type="button"
                      aria-current={active ? "true" : undefined}
                      onClick={() => {
                        go({ record: row.learning_id });
                      }}
                      className={cn(
                        "flex w-full cursor-pointer flex-col gap-1 px-4 py-3 text-left hover:bg-surface-hover",
                        active && "bg-row-selected shadow-[inset_2px_0_0_var(--accent)]",
                      )}
                    >
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="truncate font-mono text-[12.5px]">{row.learning_id}</span>
                        <span className="shrink-0 text-[12px] text-fg-muted">
                          {formatRelative(row.updated_at)}
                        </span>
                      </span>
                      <span className="truncate text-[13px] text-fg-secondary">{summary(row.content)}</span>
                      <span className="flex items-center gap-1.5 font-mono text-[11.5px] text-fg-muted">
                        {owner}
                        {row.agent_id && (
                          <>
                            {" · "}
                            <span aria-hidden className="size-1.5 rounded-[2px] bg-[#7DA6FF]" />
                            {row.agent_id}
                          </>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="flex items-center justify-end gap-2 border-t border-border-subtle px-4 py-2 text-[12px] text-fg-muted">
              <Pager
                summary={`${formatCount(rows.length)} of ${formatCount(total)}`}
                onPrevious={
                  filters.page > 1
                    ? () => {
                        go({ page: filters.page - 1, record: undefined });
                      }
                    : undefined
                }
                onNext={
                  filters.page < totalPages
                    ? () => {
                        go({ page: filters.page + 1, record: undefined });
                      }
                    : undefined
                }
              />
            </div>
          </div>
          {selected && (
            <LearningDetail
              key={`${selected.learning_id}:${String(selected.updated_at ?? "")}`}
              instance={instance}
              record={selected}
              idScheme={counts.data?.id_schemes?.[selected.learning_type]}
              onDeleted={() => {
                go({ record: undefined });
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
