import {
  contextKnowledgeBasesOptions,
  contextKnowledgeContentOptions,
  describeError,
  type KnowledgeBaseOut,
} from "@agnostic/api";
import { formatBytes, formatCount, formatRelative } from "@agnostic/core";
import {
  Button,
  Card,
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
  cn,
  type Column,
} from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { AddContent } from "./add-content";
import { ContentDetail } from "./content-detail";
import { useKnowledgeSettings, useProcessingStatus, useRetrieval, type ContentRow } from "./knowledge-api";

type Filters = {
  kb?: string | undefined;
  status?: string | undefined;
  type?: string | undefined;
  q?: string | undefined;
  page: number;
  content?: string | undefined;
};
const PAGE_SIZE = 20;
const COMPLETED = { dot: "bg-accent", text: "text-fg", label: "Completed" };
const STATUS_TONE: Record<string, { dot: string; text: string; label: string }> = {
  completed: COMPLETED,
  processing: { dot: "bg-info", text: "text-info", label: "Processing" },
  partial: { dot: "bg-warning", text: "text-warning", label: "Partial" },
  failed: { dot: "bg-danger", text: "text-danger", label: "Failed" },
};

function readFilters(search: Record<string, unknown>): Filters {
  const text = (key: string) => (typeof search[key] === "string" && search[key] ? search[key] : undefined);
  const page = typeof search.page === "number" ? search.page : Number(text("page") ?? 1);
  return {
    kb: text("kb"),
    status: text("status"),
    type: text("type"),
    q: text("q"),
    content: text("content"),
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

function size(row: ContentRow): string {
  const bytes = Number(row.size);
  return row.size && Number.isFinite(bytes) ? formatBytes(bytes) : (row.size ?? "—");
}

function metadataChips(metadata: Record<string, unknown> | null | undefined) {
  return Object.entries(metadata ?? {})
    .filter(([key]) => !key.startsWith("_"))
    .slice(0, 3)
    .map(([key, value]) => (
      <span
        key={key}
        className="rounded-badge border border-border px-1.5 py-0.5 font-mono text-[11px] whitespace-nowrap text-fg-secondary"
      >
        {key}: {typeof value === "string" ? value : JSON.stringify(value)}
      </span>
    ));
}

function columns(): Column<ContentRow>[] {
  return [
    {
      id: "name",
      header: "Name",
      cell: (row) => (
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-mono text-[12.5px] text-info">{row.name ?? row.id}</span>
          {row.description && <span className="truncate text-[12px] text-fg-muted">{row.description}</span>}
        </div>
      ),
    },
    { id: "type", header: "Type", cell: (row) => row.kind ?? row.type ?? "—" },
    { id: "size", header: "Size", align: "right", className: "whitespace-nowrap", cell: size },
    {
      id: "status",
      header: "Status",
      cell: (row) => {
        const tone = STATUS_TONE[row.status ?? "completed"] ?? COMPLETED;
        return (
          <div className="flex flex-col">
            <span className={cn("inline-flex items-center gap-1.5", tone.text)}>
              <span aria-hidden className={cn("size-[7px] rounded-full", tone.dot)} />
              {tone.label}
            </span>
            {row.status_message && <span className="text-[12px] text-fg-muted">{row.status_message}</span>}
          </div>
        );
      },
    },
    {
      id: "metadata",
      header: "Metadata",
      cell: (row) => <div className="flex flex-wrap gap-1">{metadataChips(row.metadata)}</div>,
    },
    {
      id: "updated",
      header: "Updated",
      className: "whitespace-nowrap",
      cell: (row) => (
        <span className="text-fg-muted">{formatRelative(row.updated_at ?? row.created_at)}</span>
      ),
    },
  ];
}

/** `/i/:instance/knowledge?kb=&status=&type=&q=&page=&content=` (design spec B §2). */
export function KnowledgePage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instance = params.instance ?? "";
  const filters = readFilters(search);
  const go = (next: Partial<Filters>) => {
    const merged = { ...filters, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/knowledge`,
      search: Object.fromEntries(
        Object.entries(merged).filter(([key, value]) => value && !(key === "page" && value === 1)),
      ),
    });
  };

  const basesOptions = contextKnowledgeBasesOptions({ path: { instance } });
  const bases = useQuery({
    ...basesOptions,
    queryFn: instance ? (basesOptions.queryFn ?? skipToken) : skipToken,
  });
  const list = bases.data?.bases ?? [];
  const base = list.find((item) => item.id === filters.kb) ?? list[0];

  if (bases.error) {
    return (
      <div className="px-8 pt-6">
        <ErrorState {...describeError(bases.error)} onRetry={() => void bases.refetch()} />
      </div>
    );
  }
  if (bases.isPending) {
    return (
      <div className="px-8 pt-6">
        <LoadingRows label="Loading knowledge bases" />
      </div>
    );
  }
  if (!base) {
    return (
      <div className="px-8 pt-6">
        <EmptyState title="No knowledge bases on this instance">
          Give an agent <code className="font-mono">knowledge=Knowledge(…)</code> and AgentOS lists it here.
        </EmptyState>
      </div>
    );
  }
  return (
    <KnowledgeBaseView key={base.id} instance={instance} base={base} bases={list} filters={filters} go={go} />
  );
}

function KnowledgeBaseView({
  instance,
  base,
  bases,
  filters,
  go,
}: {
  instance: string;
  base: KnowledgeBaseOut;
  bases: KnowledgeBaseOut[];
  filters: Filters;
  go: (next: Partial<Filters>) => void;
}) {
  const [text, setText] = useState(filters.q ?? "");
  const deferred = useDeferredValue(text.trim());
  const contentOptions = contextKnowledgeContentOptions({
    path: { instance },
    query: {
      knowledge_id: base.id,
      status: filters.status ?? null,
      type: filters.type ?? null,
      search: deferred || null,
      page: filters.page,
      limit: PAGE_SIZE,
    },
  });
  const content = useQuery({
    ...contentOptions,
    queryFn: contentOptions.queryFn ?? skipToken,
    placeholderData: (previous) => previous,
  });
  const settings = useKnowledgeSettings(instance, base.id);
  const rows = (content.data?.data ?? []) as ContentRow[];
  const live = useProcessingStatus(instance, base.id, rows);
  const shown = rows.map((row) => {
    const status = live.get(row.id);
    return status
      ? { ...row, status: status.status, status_message: status.status_message ?? row.status_message ?? null }
      : row;
  });
  const counts = content.data?.counts;
  const totalPages = content.data ? Math.max(1, Math.ceil(content.data.matching / PAGE_SIZE)) : 1;
  const selected = shown.find((row) => row.id === filters.content);
  const searchTypes = [...new Set(base.vector_dbs.flatMap((db) => db.search_types))];

  return (
    <div className="flex h-full min-h-0 flex-wrap">
      <section className="flex min-w-0 flex-[3_1_560px] flex-col gap-5 overflow-y-auto px-6 pt-5 pb-8">
        {bases.length > 1 && (
          <SegmentedControl
            label="Knowledge base"
            value={base.id}
            onValueChange={(value) => {
              go({
                kb: value,
                page: 1,
                content: undefined,
                status: undefined,
                type: undefined,
                q: undefined,
              });
            }}
            options={bases.map((item) => ({
              value: item.id,
              label: (
                <span className="font-mono text-[12px]">
                  {item.name} <span className="text-fg-muted">{formatCount(item.entries)}</span>
                </span>
              ),
            }))}
          />
        )}

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <h1 className="font-mono text-[22px] font-semibold">{base.name}</h1>
            <p className="text-[13px] text-fg-secondary">
              {formatCount(base.entries)} content entries
              {base.vector_dbs.length > 0 && ` · ${base.vector_dbs.map((db) => db.name ?? db.id).join(", ")}`}
              {" · "}
              <code className="font-mono text-[12px]">
                {base.db_id}.{base.table}
              </code>
            </p>
            {base.description && <p className="text-[12.5px] text-fg-muted">{base.description}</p>}
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <span className="text-[12px] text-fg-muted">Used by</span>
            <div className="flex flex-wrap justify-end gap-1.5">
              {base.used_by === null ? (
                <span className="text-[12px] text-fg-muted">Needs agents:read</span>
              ) : base.used_by.length === 0 ? (
                <span className="text-[12px] text-fg-muted">No agent reads it</span>
              ) : (
                base.used_by.map((reader) => (
                  <Link
                    key={`${reader.kind}:${reader.id}`}
                    to={`/i/${encodeURIComponent(instance)}/sessions`}
                    search={{ component: reader.id }}
                    title={`Sessions of ${reader.name}`}
                    className="inline-flex h-6 items-center gap-1.5 rounded-control border border-border px-2 font-mono text-[11.5px] text-fg-secondary hover:text-fg"
                  >
                    <span aria-hidden className="size-1.5 rounded-[2px] bg-[#7DA6FF]" />
                    {reader.id}
                  </Link>
                ))
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-[320px]">
            <Search
              className="pointer-events-none absolute top-2 left-2.5 size-4 text-fg-muted"
              aria-hidden
            />
            <Input
              aria-label="Search content by name or metadata"
              placeholder="Search content by name or metadata"
              className="h-8 pl-8"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
              }}
              onBlur={() => {
                if ((filters.q ?? "") !== text.trim()) go({ q: text.trim() || undefined, page: 1 });
              }}
            />
          </div>
          <Select
            value={filters.status ?? "any"}
            onValueChange={(value) => {
              go({ status: value === "any" ? undefined : value, page: 1 });
            }}
          >
            <SelectTrigger aria-label="Status" className="h-8 w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Status: Any</SelectItem>
              {Object.entries(STATUS_TONE).map(([value, tone]) => (
                <SelectItem key={value} value={value}>
                  Status: {tone.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={filters.type ?? "any"}
            onValueChange={(value) => {
              go({ type: value === "any" ? undefined : value, page: 1 });
            }}
          >
            <SelectTrigger aria-label="Type" className="h-8 w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Type: Any</SelectItem>
              {Object.keys(counts?.by_kind ?? {}).map((kind) => (
                <SelectItem key={kind} value={kind}>
                  Type: {kind}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="ml-auto flex gap-3 text-[12.5px]">
            {(counts?.by_status.failed ?? 0) > 0 && (
              <button
                type="button"
                className="cursor-pointer text-danger hover:underline"
                onClick={() => {
                  go({ status: "failed", page: 1 });
                }}
              >
                {formatCount(counts?.by_status.failed)} failed
              </button>
            )}
            {(counts?.by_status.processing ?? 0) > 0 && (
              <button
                type="button"
                className="cursor-pointer text-info hover:underline"
                onClick={() => {
                  go({ status: "processing", page: 1 });
                }}
              >
                {formatCount(counts?.by_status.processing)} processing
              </button>
            )}
          </span>
        </div>

        {content.error ? (
          <ErrorState {...describeError(content.error)} onRetry={() => void content.refetch()} />
        ) : content.isPending ? (
          <LoadingRows label="Loading content" />
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[760px]">
              <DataTable
                label="Content"
                columns={columns()}
                rows={shown}
                rowKey={(row) => row.id}
                selectedKey={filters.content}
                onRowClick={(row) => {
                  go({ content: row.id });
                }}
                empty={
                  <EmptyState
                    title={
                      filters.status || filters.type || deferred ? "No content matches" : "No content yet"
                    }
                  >
                    Add files, pages, text or a remote source on the right.
                  </EmptyState>
                }
                footer={
                  <Pager
                    summary={`${formatCount(shown.length)} of ${formatCount(content.data.matching)} entries${
                      content.data.partial ? ` (newest ${formatCount(content.data.scanned)} searched)` : ""
                    }`}
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
            </div>
          </div>
        )}

        <TestRetrieval instance={instance} kb={base.id} searchTypes={searchTypes} />
      </section>

      <AddContent instance={instance} base={base} settings={settings.data} />

      {selected && (
        <ContentDetail
          instance={instance}
          kb={base.id}
          row={selected}
          onClose={() => {
            go({ content: undefined });
          }}
        />
      )}
    </div>
  );
}

function TestRetrieval({
  instance,
  kb,
  searchTypes,
}: {
  instance: string;
  kb: string;
  searchTypes: string[];
}) {
  const retrieval = useRetrieval(instance, kb);
  const [text, setText] = useState("");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [filterDraft, setFilterDraft] = useState("");
  const [topK, setTopK] = useState("5");
  const [searchType, setSearchType] = useState(
    searchTypes.includes("hybrid") ? "hybrid" : (searchTypes[0] ?? "vector"),
  );
  const result = retrieval.data;
  const reranked = result?.results.some(
    (item) => item.reranking_score !== null && item.reranking_score !== undefined,
  );

  return (
    <Card
      title="Test retrieval"
      meta={
        <span>
          Runs the same search agents use · <code className="font-mono">POST /knowledge/search</code>
        </span>
      }
    >
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim()) retrieval.mutate({ text: text.trim(), filters, topK: Number(topK), searchType });
        }}
      >
        <Input
          aria-label="Query"
          placeholder="What would a user ask?"
          className="h-8 min-w-60 flex-1"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        {Object.entries(filters).map(([key, value]) => (
          <span
            key={key}
            className="inline-flex h-7 items-center gap-1 rounded-control border border-border px-2 font-mono text-[11.5px]"
          >
            {key} = {value}
            <button
              type="button"
              aria-label="Remove filter"
              className="cursor-pointer text-fg-muted hover:text-fg"
              onClick={() => {
                setFilters(Object.fromEntries(Object.entries(filters).filter(([name]) => name !== key)));
              }}
            >
              <X className="size-3" aria-hidden />
            </button>
          </span>
        ))}
        <Input
          aria-label="Add a metadata filter (key=value)"
          placeholder="key=value"
          mono
          className="h-8 w-32"
          value={filterDraft}
          onChange={(event) => {
            setFilterDraft(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            const [key, ...rest] = filterDraft.split("=");
            if (key?.trim() && rest.length > 0) {
              setFilters({ ...filters, [key.trim()]: rest.join("=").trim() });
              setFilterDraft("");
            }
          }}
        />
        <Select value={topK} onValueChange={setTopK}>
          <SelectTrigger aria-label="Top" className="h-8 w-24">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {["3", "5", "10"].map((value) => (
              <SelectItem key={value} value={value}>
                Top {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {searchTypes.length > 1 && (
          <Select value={searchType} onValueChange={setSearchType}>
            <SelectTrigger aria-label="Search type" className="h-8 w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {searchTypes.map((value) => (
                <SelectItem key={value} value={value}>
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Button type="submit" variant="primary" size="32" disabled={!text.trim() || retrieval.isPending}>
          {retrieval.isPending ? "Searching…" : "Search"}
        </Button>
      </form>
      {retrieval.error && <ErrorState title="The search failed" {...describeError(retrieval.error)} />}
      {result && (
        <>
          {result.results.length === 0 ? (
            <p className="text-[12.5px] text-fg-muted">
              No chunks match. Try fewer filters or a broader question.
            </p>
          ) : (
            <ol aria-label="Top chunks" className="flex flex-col divide-y divide-border-subtle">
              {result.results.map((item, index) => {
                const score = item.reranking_score ?? undefined;
                return (
                  <li key={item.id ?? index} className="flex gap-4 py-3">
                    <div className="flex w-12 shrink-0 flex-col gap-1">
                      <span className="font-mono text-[13px] font-semibold">
                        {score === undefined ? `#${String(index + 1)}` : score.toFixed(2)}
                      </span>
                      {score !== undefined && (
                        <span className="h-1 w-10 rounded-full bg-surface-hover">
                          <span
                            className="block h-1 rounded-full bg-accent"
                            style={{ width: `${String(Math.max(0, Math.min(1, score)) * 100)}%` }}
                          />
                        </span>
                      )}
                    </div>
                    <div className="flex min-w-0 flex-col gap-1">
                      <p className="text-[13px] text-fg">{item.content}</p>
                      <span className="font-mono text-[11.5px] text-fg-muted">
                        {item.name ?? item.content_origin ?? item.content_id ?? "—"}
                        {typeof item.meta_data?.chunk === "number"
                          ? ` · chunk ${String(item.meta_data.chunk)}`
                          : ""}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
          <p className="text-[12px] text-fg-muted">
            {result.results.length} results in {Math.round(result.latencyMs)} ms · {result.searchType} search
            · reranking {reranked ? "on" : "off"}
          </p>
        </>
      )}
    </Card>
  );
}
