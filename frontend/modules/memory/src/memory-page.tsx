import {
  contextMemoryDuplicatesOptions,
  contextMemorySourceOptions,
  contextOptimizeMemories,
  describeError,
  type OptimizeOut,
} from "@agnostic/api";
import {
  PermissionGate,
  findInstance,
  formatCount,
  formatRelative,
  useCan,
  useInstances,
} from "@agnostic/core";
import {
  ApiHint,
  Button,
  Callout,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Input,
  KeyValueList,
  LoadingRows,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Textarea,
  cn,
  toast,
} from "@agnostic/ui";
import { skipToken, useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Eye, Plus, Search, Sparkles, X } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import {
  authors,
  memoryDatabases,
  topicCounts,
  useConfig,
  useMemories,
  useMemoryActions,
  useTopics,
  useUserStats,
  type Memory,
  type MemoryDraft,
} from "./memory-api";

type Filters = {
  user?: string | undefined;
  memory?: string | undefined;
  topic?: string | undefined;
  db?: string | undefined;
};
const NEW = "new";
const TOP_TOPICS = 5;

function readFilters(search: Record<string, unknown>): Filters {
  const text = (key: string) => (typeof search[key] === "string" && search[key] ? search[key] : undefined);
  return { user: text("user"), memory: text("memory"), topic: text("topic"), db: text("db") };
}

/** `/i/:instance/memory?user=&memory=&topic=&db=` (design spec B §1). */
export function MemoryPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instanceRef = params.instance ?? "";
  const filters = readFilters(search);
  const go = (next: Partial<Filters>) => {
    const merged = { ...filters, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instanceRef)}/memory`,
      search: Object.fromEntries(Object.entries(merged).filter(([, value]) => value)),
    });
  };

  const config = useConfig(instanceRef);
  const databases = memoryDatabases(config.data);
  const db = filters.db ?? (databases.length > 1 ? databases[0] : undefined);
  const users = useUserStats(instanceRef, db);
  const [userQuery, setUserQuery] = useState("");
  const userRows = (users.data?.data ?? []).filter((row) =>
    row.user_id.toLowerCase().includes(userQuery.trim().toLowerCase()),
  );
  const user = filters.user ?? users.data?.data[0]?.user_id;

  return (
    <div className="flex h-full min-h-0 flex-wrap">
      <nav
        aria-label="Users with memories"
        className="flex max-h-full min-w-0 flex-[1_1_220px] flex-col gap-3 overflow-y-auto border-r border-border-subtle px-4 pt-5 pb-6 lg:max-w-[260px]"
      >
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[13.5px] font-semibold">Users</h2>
          <span className="text-[12px] text-fg-muted">
            {users.data ? `${formatCount(users.data.meta.total_count)} with memories` : ""}
          </span>
        </div>
        <label className="sr-only" htmlFor="memory-user-search">
          Find a user
        </label>
        <Input
          id="memory-user-search"
          mono
          placeholder="Find user_id"
          className="h-8"
          value={userQuery}
          onChange={(event) => {
            setUserQuery(event.target.value);
          }}
        />
        {users.isPending ? (
          <LoadingRows rows={6} label="Loading users" />
        ) : users.error ? (
          <ErrorState {...describeError(users.error)} onRetry={() => void users.refetch()} />
        ) : userRows.length === 0 ? (
          <p className="text-[12.5px] text-fg-muted">{userQuery ? "No user matches." : "No memories yet."}</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {userRows.map((row) => {
              const active = row.user_id === user;
              return (
                <li key={row.user_id}>
                  <button
                    type="button"
                    aria-current={active ? "true" : undefined}
                    onClick={() => {
                      go({ user: row.user_id, memory: undefined, topic: undefined });
                    }}
                    className={cn(
                      "flex w-full cursor-pointer flex-col items-start gap-0.5 rounded-control px-2.5 py-1.5 text-left hover:bg-surface-hover",
                      active && "bg-segment-active",
                    )}
                  >
                    <span className="w-full truncate font-mono text-[12.5px] text-fg">{row.user_id}</span>
                    <span className="text-[11.5px] text-fg-muted">
                      {formatCount(row.total_memories)} memories ·{" "}
                      {formatRelative(row.last_memory_updated_at)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      {user ? (
        <UserMemories
          key={`${user}:${db ?? ""}`}
          instance={instanceRef}
          user={user}
          db={db}
          databases={databases}
          filters={filters}
          total={users.data?.data.find((row) => row.user_id === user)?.total_memories}
          go={go}
        />
      ) : (
        <main className="flex min-w-0 flex-[3_1_440px] flex-col px-6 pt-5">
          {!users.isPending && (
            <EmptyState title="No memories yet">
              Agents with memory enabled write what they learn about each user here.
            </EmptyState>
          )}
        </main>
      )}
    </div>
  );
}

function UserMemories({
  instance,
  user,
  db,
  databases,
  filters,
  total,
  go,
}: {
  instance: string;
  user: string;
  db: string | undefined;
  databases: string[];
  filters: Filters;
  total: number | undefined;
  go: (next: Partial<Filters>) => void;
}) {
  const [text, setText] = useState("");
  const deferred = useDeferredValue(text.trim());
  const memories = useMemories(instance, { user, search: deferred, topic: filters.topic, db });
  const all = useMemories(instance, { user, search: "", topic: undefined, db });
  const topics = useTopics(instance, user, db);
  const duplicatesOptions = contextMemoryDuplicatesOptions({
    path: { instance },
    query: { user_id: user, db_id: db ?? null },
  });
  const duplicates = useQuery({ ...duplicatesOptions, queryFn: duplicatesOptions.queryFn ?? skipToken });
  const flagged = new Map((duplicates.data?.duplicates ?? []).map((item) => [item.memory_id, item]));
  const [preview, setPreview] = useState<OptimizeOut | undefined>(undefined);
  const actions = useMemoryActions(instance, db);

  const loaded = useMemo(() => all.data?.data ?? [], [all.data]);
  const pills = useMemo(() => {
    const counts = topicCounts(loaded);
    const known = new Set(counts.map((item) => item.topic));
    for (const topic of Array.isArray(topics.data) ? topics.data : [])
      if (!known.has(topic)) counts.push({ topic, count: 0 });
    return counts.slice(0, TOP_TOPICS);
  }, [loaded, topics.data]);

  const optimize = useMutation({
    mutationFn: async (apply: boolean) =>
      (
        await contextOptimizeMemories({
          path: { instance },
          body: { user_id: user, apply, db_id: db ?? null },
          throwOnError: true,
        })
      ).data,
    onSuccess: async (result) => {
      if (result.applied) {
        setPreview(undefined);
        await actions.refresh();
        toast.success(
          `Optimized: ${String(result.memories_before)} → ${String(result.memories_after)} memories`,
        );
      } else {
        setPreview(result);
      }
    },
    onError: (error) => toast.error(`Optimization failed: ${describeError(error).reason}`),
  });

  const rows = memories.data?.data ?? [];
  const selected =
    filters.memory === NEW ? undefined : (rows.find((row) => row.memory_id === filters.memory) ?? undefined);
  const editing = filters.memory === NEW || selected !== undefined;
  const writtenBy = authors(loaded);
  const count = total ?? all.data?.meta.total_count ?? loaded.length;

  return (
    <>
      <main className="flex min-w-0 flex-[3_1_440px] flex-col gap-4 overflow-y-auto px-6 pt-5 pb-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <h1 className="truncate font-mono text-[20px] font-semibold">{user}</h1>
            <p className="text-[13px] text-fg-secondary">
              {formatCount(count)} memories{writtenBy ? ` · written by ${writtenBy}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {databases.length > 1 && (
              <Select
                value={db ?? databases[0] ?? ""}
                onValueChange={(value) => {
                  go({ db: value, memory: undefined, topic: undefined });
                }}
              >
                <SelectTrigger aria-label="Database" className="h-8 w-56 font-mono text-[12px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {databases.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <PermissionGate scope="memories:write" instance={instance}>
              <ApiHint call="POST /optimize-memories" scope="memories:write">
                <Button
                  variant="outline"
                  size="32"
                  disabled={optimize.isPending || loaded.length < 2}
                  onClick={() => {
                    optimize.mutate(false);
                  }}
                >
                  <Sparkles className="text-accent" aria-hidden />
                  {optimize.isPending && !preview ? "Optimizing…" : "Optimize memories"}
                </Button>
              </ApiHint>
              <Button
                variant="primary"
                size="32"
                onClick={() => {
                  go({ memory: NEW });
                }}
              >
                <Plus aria-hidden />
                Add memory
              </Button>
            </PermissionGate>
          </div>
        </div>

        {preview && (
          <OptimizationPreview
            preview={preview}
            before={loaded}
            applying={optimize.isPending}
            onApply={() => {
              optimize.mutate(true);
            }}
            onDismiss={() => {
              setPreview(undefined);
            }}
          />
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full max-w-[260px]">
            <Search
              className="pointer-events-none absolute top-2 left-2.5 size-4 text-fg-muted"
              aria-hidden
            />
            <label className="sr-only" htmlFor="memory-search">
              Search memories
            </label>
            <Input
              id="memory-search"
              placeholder="Search memories"
              className="h-8 pl-8"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
          </div>
          <div role="group" aria-label="Filter by topic" className="flex flex-wrap items-center gap-1.5">
            <TopicPill
              label="All"
              count={loaded.length}
              active={!filters.topic}
              onClick={() => {
                go({ topic: undefined });
              }}
            />
            {pills.map((pill) => (
              <TopicPill
                key={pill.topic}
                label={pill.topic}
                count={pill.count}
                active={filters.topic === pill.topic}
                onClick={() => {
                  go({ topic: filters.topic === pill.topic ? undefined : pill.topic });
                }}
              />
            ))}
          </div>
        </div>

        {memories.error ? (
          <ErrorState {...describeError(memories.error)} onRetry={() => void memories.refetch()} />
        ) : memories.isPending ? (
          <LoadingRows rows={5} label="Loading memories" />
        ) : rows.length === 0 ? (
          <EmptyState
            title={deferred || filters.topic ? "No memories match." : "No memories for this user."}
          />
        ) : (
          <>
            <ul aria-label="Memories" className="flex flex-col gap-2">
              {rows.map((memory) => (
                <li key={memory.memory_id}>
                  <MemoryCard
                    memory={memory}
                    duplicateOf={flagged.get(memory.memory_id)?.duplicate_of}
                    selected={memory.memory_id === filters.memory}
                    onSelect={() => {
                      go({ memory: memory.memory_id });
                    }}
                  />
                </li>
              ))}
            </ul>
            <p className="text-[12px] text-fg-muted">
              Showing {formatCount(rows.length)} of {formatCount(count)}
              {duplicates.data?.partial
                ? ` · duplicates checked on the newest ${formatCount(duplicates.data.scanned)}`
                : ""}
            </p>
          </>
        )}
      </main>

      {editing && (
        <MemoryEditor
          key={filters.memory}
          instance={instance}
          user={user}
          db={db}
          memory={selected}
          actions={actions}
          onClose={() => {
            go({ memory: undefined });
          }}
          onCreated={(id) => {
            go({ memory: id });
          }}
        />
      )}
    </>
  );
}

function TopicPill({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 cursor-pointer items-center gap-1.5 rounded-full border px-2.5 text-[12.5px]",
        active
          ? "border-border-strong bg-segment-active text-fg-active"
          : "border-border text-fg-secondary hover:text-fg",
      )}
    >
      {label}
      <span className="font-mono text-[11px] text-fg-muted">{count}</span>
    </button>
  );
}

function MemoryCard({
  memory,
  duplicateOf,
  selected,
  onSelect,
}: {
  memory: Memory;
  duplicateOf: string | undefined;
  selected: boolean;
  onSelect: () => void;
}) {
  const author = memory.agent_id ?? memory.team_id;
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "flex w-full cursor-pointer flex-col gap-2 rounded-card border px-3.5 py-3 text-left",
        selected ? "border-accent bg-surface-raised" : "border-border bg-surface hover:border-border-strong",
      )}
    >
      <span className="text-[13.5px] text-fg">{memory.memory}</span>
      <span className="flex flex-wrap items-center gap-1.5">
        {(memory.topics ?? []).map((topic) => (
          <span
            key={topic}
            className="rounded-badge border border-border px-1.5 py-0.5 font-mono text-[11px] text-fg-secondary"
          >
            {topic}
          </span>
        ))}
        {duplicateOf && (
          <span
            title={`Says the same as ${duplicateOf}`}
            className="rounded-badge border border-warning/40 px-1.5 py-0.5 font-mono text-[11px] text-warning"
          >
            likely duplicate
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5 text-[12px] text-fg-muted">
          {author && <span aria-hidden className="size-1.5 rounded-[2px] bg-[#7DA6FF]" />}
          {author ? `${author} · ` : "Added directly · "}
          {formatRelative(memory.updated_at)}
        </span>
      </span>
    </button>
  );
}

function OptimizationPreview({
  preview,
  before,
  applying,
  onApply,
  onDismiss,
}: {
  preview: OptimizeOut;
  before: readonly Memory[];
  applying: boolean;
  onApply: () => void;
  onDismiss: () => void;
}) {
  return (
    <section
      aria-label="Optimization preview"
      className="flex flex-col gap-3 rounded-panel border border-accent/35 bg-accent/4 p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h2 className="text-[14px] font-semibold">
            Preview: {preview.memories_before} → {preview.memories_after} memories
          </h2>
          <p className="text-[12.5px] text-fg-secondary">
            Strategy: summarize · {formatCount(preview.tokens_saved)} tokens saved (
            {preview.reduction_percentage.toFixed(0)}%) · nothing changes until you apply. Applying runs the
            optimization again, so the saved wording can differ slightly from this preview.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="30" onClick={onDismiss}>
            Dismiss
          </Button>
          <Button variant="primary" size="30" disabled={applying} onClick={onApply}>
            {applying ? "Applying…" : "Apply"}
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-3">
        <div className="flex flex-col gap-1.5 rounded-tile border border-border bg-surface p-3">
          <span className="font-mono text-[11px] text-fg-muted uppercase">Before · {before.length}</span>
          <ul className="flex flex-col gap-1 text-[12.5px] text-fg-secondary">
            {before.map((memory) => (
              <li key={memory.memory_id} className="line-through decoration-fg-faint">
                <span className="sr-only">(removed) </span>
                {memory.memory}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-1.5 rounded-tile border border-accent/30 bg-surface p-3">
          <span className="font-mono text-[11px] text-accent uppercase">
            After · {preview.memories_after}
          </span>
          <ul className="flex flex-col gap-1 text-[12.5px] text-fg">
            {preview.memories.map((memory, index) => (
              <li key={memory.memory_id || index}>
                <span className="sr-only">(added) </span>
                {memory.memory}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function MemoryEditor({
  instance,
  user,
  db,
  memory,
  actions,
  onClose,
  onCreated,
}: {
  instance: string;
  user: string;
  db: string | undefined;
  memory: Memory | undefined;
  actions: ReturnType<typeof useMemoryActions>;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const instances = useInstances();
  const info = findInstance(instances.data, instance);
  const canWrite = useCan("memories:write", instance).allowed === true;
  const [draft, setDraft] = useState<MemoryDraft>({
    memory: memory?.memory ?? "",
    topics: memory?.topics ?? [],
  });
  const [topic, setTopic] = useState<string | undefined>(undefined);
  const sourceOptions = contextMemorySourceOptions({
    path: { instance, memory_id: memory?.memory_id ?? "" },
    query: { db_id: db ?? null },
  });
  const source = useQuery({
    ...sourceOptions,
    queryFn: memory ? (sourceOptions.queryFn ?? skipToken) : skipToken,
  });
  const dirty =
    draft.memory !== (memory?.memory ?? "") || draft.topics.join("\n") !== (memory?.topics ?? []).join("\n");
  const saving = actions.create.isPending || actions.update.isPending;

  const save = () => {
    const body = { ...draft, memory: draft.memory.trim() };
    if (memory) {
      actions.update.mutate(
        { id: memory.memory_id, user, draft: body },
        {
          onSuccess: () => toast.success("Memory saved"),
          onError: (error) => toast.error(describeError(error).reason),
        },
      );
    } else {
      actions.create.mutate(
        { user, draft: body },
        {
          onSuccess: (created) => {
            toast.success("Memory added");
            onCreated(created.memory_id);
          },
          onError: (error) => toast.error(describeError(error).reason),
        },
      );
    }
  };

  return (
    <aside
      aria-label="Edit memory"
      className="flex min-w-0 flex-[1_1_320px] flex-col border-l border-border-subtle bg-rail lg:max-w-[380px]"
    >
      <header className="flex items-baseline justify-between gap-2 border-b border-border-subtle px-5 py-4">
        <h2 className="text-[14px] font-semibold">{memory ? "Memory" : "New memory"}</h2>
        <span className="truncate font-mono text-[11.5px] text-fg-muted">{memory?.memory_id ?? user}</span>
      </header>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="memory-text" className="text-[13px] font-medium text-fg-secondary">
            Memory
          </label>
          <Textarea
            id="memory-text"
            rows={3}
            className="min-h-20 font-sans text-[13px]"
            readOnly={!canWrite}
            value={draft.memory}
            onChange={(event) => {
              setDraft({ ...draft, memory: event.target.value });
            }}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-medium text-fg-secondary">Topics</span>
            {canWrite && topic === undefined && (
              <Button
                variant="link"
                size="28"
                onClick={() => {
                  setTopic("");
                }}
              >
                Add topic
              </Button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {draft.topics.map((item) => (
              <span
                key={item}
                className="inline-flex h-[26px] items-center gap-1 rounded-control border border-border px-2 font-mono text-[11.5px]"
              >
                {item}
                {canWrite && (
                  <button
                    type="button"
                    aria-label={`Remove topic ${item}`}
                    className="cursor-pointer text-fg-muted hover:text-fg"
                    onClick={() => {
                      setDraft({ ...draft, topics: draft.topics.filter((value) => value !== item) });
                    }}
                  >
                    <X className="size-3" aria-hidden />
                  </button>
                )}
              </span>
            ))}
            {topic !== undefined && (
              <Input
                aria-label="New topic"
                mono
                className="h-[26px] w-32 text-[11.5px]"
                value={topic}
                onChange={(event) => {
                  setTopic(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") setTopic(undefined);
                  if (event.key !== "Enter") return;
                  event.preventDefault();
                  const value = topic.trim();
                  if (value && !draft.topics.includes(value))
                    setDraft({ ...draft, topics: [...draft.topics, value] });
                  setTopic(undefined);
                }}
                onBlur={() => {
                  const value = topic.trim();
                  if (value && !draft.topics.includes(value))
                    setDraft({ ...draft, topics: [...draft.topics, value] });
                  setTopic(undefined);
                }}
              />
            )}
            {draft.topics.length === 0 && topic === undefined && (
              <span className="text-[12px] text-fg-muted">No topics</span>
            )}
          </div>
        </div>

        {memory && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[13px] font-medium text-fg-secondary">Generated from this input</span>
            {source.isPending ? (
              <Skeleton className="h-12 w-full" />
            ) : source.data?.input ? (
              <>
                <blockquote className="rounded-tile border-l-2 border-border-strong bg-surface px-3 py-2 text-[13px] text-fg">
                  {source.data.input}
                </blockquote>
                <span className="text-[11.5px] text-fg-muted">
                  Best effort: the run of {source.data.agent_id ?? source.data.team_id} for {user} just before
                  this memory was written.
                </span>
              </>
            ) : (
              <p className="text-[12.5px] text-fg-muted">
                {source.data?.reason ?? (source.error ? describeError(source.error).reason : "Unknown")}
              </p>
            )}
          </div>
        )}

        {memory && (
          <KeyValueList
            items={[
              {
                key: "by",
                label: "Created by",
                value: memory.agent_id ?? memory.team_id ?? "Added directly",
                mono: true,
              },
              {
                key: "session",
                label: "Session",
                mono: true,
                value: source.data?.session_id ? (
                  <Link
                    to={`/i/${encodeURIComponent(instance)}/sessions/${encodeURIComponent(source.data.session_id)}`}
                    className="text-info hover:text-info-hover"
                  >
                    {source.data.session_id}
                  </Link>
                ) : (
                  "—"
                ),
              },
              { key: "updated", label: "Updated", value: formatRelative(memory.updated_at) },
            ]}
          />
        )}

        <div className="flex gap-2 rounded-tile border border-border px-3 py-2.5 text-[12.5px] text-fg-secondary">
          <Eye className="mt-0.5 size-3.5 shrink-0 text-fg-muted" aria-hidden />
          <p>
            <strong className="text-fg">Who can see this:</strong>{" "}
            {info?.user_isolation
              ? `user isolation is on, so only runs for ${user} load it into context.`
              : "user isolation is off, so any run that passes this user_id loads it into context."}{" "}
            Here, anyone with <code className="font-mono">memories:read</code> on{" "}
            {info?.display_name ?? instance} can view it.
          </p>
        </div>
        {(actions.update.isError || actions.create.isError) && (
          <Callout tone="danger">
            {describeError(actions.update.error ?? actions.create.error).reason}
          </Callout>
        )}
      </div>
      <footer className="flex items-center justify-between gap-2 border-t border-border-subtle px-5 py-3">
        {memory ? (
          <PermissionGate scope="memories:delete" instance={instance}>
            <DeleteMemory memory={memory} actions={actions} onDeleted={onClose} />
          </PermissionGate>
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <Button variant="outline" size="30" onClick={onClose}>
            Cancel
          </Button>
          {canWrite && (
            <Button
              variant="primary"
              size="30"
              disabled={!dirty || !draft.memory.trim() || saving}
              onClick={save}
            >
              {saving ? "Saving…" : "Save"}
            </Button>
          )}
        </div>
      </footer>
    </aside>
  );
}

function DeleteMemory({
  memory,
  actions,
  onDeleted,
}: {
  memory: Memory;
  actions: ReturnType<typeof useMemoryActions>;
  onDeleted: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button
        variant="destructive-text"
        size="30"
        onClick={() => {
          setOpen(true);
        }}
      >
        Delete
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this memory?</DialogTitle>
          <DialogDescription>
            Agents stop loading “{memory.memory}” into context. This can&apos;t be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" size="32">
              Cancel
            </Button>
          </DialogClose>
          <Button
            variant="destructive-outline"
            size="32"
            disabled={actions.remove.isPending}
            onClick={() => {
              actions.remove.mutate(
                { id: memory.memory_id },
                {
                  onSuccess: () => {
                    setOpen(false);
                    toast.success("Memory deleted");
                    onDeleted();
                  },
                  onError: (error) => toast.error(describeError(error).reason),
                },
              );
            }}
          >
            Delete memory
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
