// The tool catalog: MCP servers and Agno toolkits approved for the organization, set up by teams, or by builders for
// one instance, as cards; and per instance, whether its runtime pulls the catalog and how each entry is doing there.
import {
  describeError,
  toolCatalogDeleteEntryMutation,
  toolCatalogDisableEntryMutation,
  toolCatalogEnableEntryMutation,
  toolCatalogListEntriesOptions,
  toolCatalogNudgeMutation,
  toolCatalogSyncStatusOptions,
  toolCatalogSyncTokenMutation,
  type EntryOut,
  type InstanceOut,
  type SyncTokenOut,
} from "@agnostic/api";
import { STALE_TIME, formatRelative, useCan, useInstances, withQueryFn } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  CodeBlock,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  PageIntro,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  cn,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Blocks, Plug, Plus, RefreshCw, Search, Server, Wrench } from "lucide-react";
import { useState } from "react";

import { LEVEL_TONE, STATE_TEXT, kindLabel, refreshCatalog, type Level } from "./catalog-api";
import { EntryEditor } from "./entry-editor";

type Tab = Level | "instances";

const TAB_HINT: Record<Level, string> = {
  org: "Approved for everyone in the organization.",
  team: "Set up by teams for their members. You see the teams you're in (owners and administrators see all).",
  custom: "Set up by builders for one instance, from the full list of Agno toolkits.",
};

function EntryCard({ entry, onOpen }: { entry: EntryOut; onOpen: () => void }) {
  const client = useQueryClient();
  const toggle = useMutation({
    ...(entry.status === "active" ? toolCatalogDisableEntryMutation() : toolCatalogEnableEntryMutation()),
    onSuccess: () => refreshCatalog(client),
  });
  const remove = useMutation({
    ...toolCatalogDeleteEntryMutation(),
    onSuccess: () => refreshCatalog(client),
  });
  const Icon = entry.kind === "mcp" ? Plug : Wrench;
  return (
    <li
      className={cn(
        "flex flex-col gap-3 rounded-tile border border-border bg-surface p-4",
        entry.status === "disabled" && "opacity-70",
      )}
    >
      <div className="flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-control bg-surface-hover text-fg-secondary">
          <Icon aria-hidden className="size-4" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <button
            type="button"
            className="cursor-pointer self-start truncate text-left text-[14px] font-semibold text-fg hover:underline"
            onClick={onOpen}
          >
            {entry.display_name}
          </button>
          <code className="truncate font-mono text-[11.5px] text-fg-muted">{entry.registry_name}</code>
        </div>
        <Badge tone={LEVEL_TONE[entry.level]}>{entry.level_label}</Badge>
      </div>
      {entry.description && (
        <p className="line-clamp-2 text-[12.5px] text-fg-secondary">{entry.description}</p>
      )}
      <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-fg-muted">
        <span>{kindLabel(entry)}</span>
        {entry.local && <Badge tone="warning">runs commands</Badge>}
        {entry.status === "disabled" && <Badge tone="muted">disabled</Badge>}
        {entry.instance_ids.length > 0 && entry.level !== "custom" && (
          <Badge tone="outline">{entry.instance_ids.length} instance(s)</Badge>
        )}
      </div>
      {entry.same_as.length > 0 && (
        <p className="text-[11.5px] text-fg-muted">
          Also offered as{" "}
          {entry.same_as.map((other, index) => (
            <span key={other.entry_id}>
              {index > 0 && ", "}
              <span className="font-medium text-fg-secondary">{other.level_label}</span> ({other.display_name}
              )
            </span>
          ))}
        </p>
      )}
      {entry.editable && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border-subtle pt-3">
          <Button size="28" variant="ghost" onClick={onOpen}>
            Change
          </Button>
          <Button
            size="28"
            variant="ghost"
            disabled={toggle.isPending}
            onClick={() => {
              toggle.mutate({ path: { entry_id: entry.id } });
            }}
          >
            {entry.status === "active" ? "Disable" : "Enable"}
          </Button>
          <Button
            size="28"
            variant="ghost"
            className="text-danger"
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate({ path: { entry_id: entry.id } });
            }}
          >
            Delete
          </Button>
        </div>
      )}
      {(remove.error ?? toggle.error) && (
        <p className="text-[12px] text-danger">{describeError(remove.error ?? toggle.error).reason}</p>
      )}
    </li>
  );
}

function EntryGrid({ level, query }: { level: Level; query: string }) {
  const [open, setOpen] = useState<EntryOut | undefined>();
  const list = useQuery({
    ...withQueryFn(
      toolCatalogListEntriesOptions({ query: { level, ...(query.trim() ? { q: query.trim() } : {}) } }),
    ),
    staleTime: STALE_TIME.list,
  });
  if (list.isPending) return <LoadingRows rows={3} />;
  if (list.error) {
    const { reason, requestId } = describeError(list.error);
    return <ErrorState reason={reason} requestId={requestId} onRetry={() => void list.refetch()} />;
  }
  if (list.data.length === 0) {
    return (
      <EmptyState title={query ? "Nothing matches" : "Nothing here yet"}>
        {query ? `No ${level} entry matches “${query}”.` : TAB_HINT[level]}
      </EmptyState>
    );
  }
  return (
    <>
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label={`${level} entries`}>
        {list.data.map((entry) => (
          <EntryCard
            key={entry.id}
            entry={entry}
            onOpen={() => {
              setOpen(entry);
            }}
          />
        ))}
      </ul>
      <EntryEditor
        open={Boolean(open?.editable)}
        entry={open}
        onOpenChange={(next) => {
          if (!next) setOpen(undefined);
        }}
      />
    </>
  );
}

function TokenOnce({ token }: { token: SyncTokenOut }) {
  const lines = Object.entries(token.env)
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
  return (
    <Callout tone="warning" title="Set these on the runtime — the token is shown only once">
      <CodeBlock code={lines} />
    </Callout>
  );
}

function InstanceSync({ instance }: { instance: InstanceOut }) {
  const client = useQueryClient();
  const canWrite = useCan("tool_catalog:write").allowed === true;
  const [token, setToken] = useState<SyncTokenOut | undefined>();
  const status = useQuery({
    ...withQueryFn(toolCatalogSyncStatusOptions({ path: { instance: instance.id } })),
    staleTime: STALE_TIME.live,
  });
  const issue = useMutation({ ...toolCatalogSyncTokenMutation(), onSuccess: setToken });
  const nudge = useMutation({
    ...toolCatalogNudgeMutation(),
    onSuccess: () => client.invalidateQueries({ queryKey: [{ _id: "toolCatalogSyncStatus" }] }),
  });
  const data = status.data;
  const bridge = data?.bridge;
  const reported = bridge?.entries ?? [];
  return (
    <li className="flex flex-col gap-3 rounded-tile border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Server aria-hidden className="size-4 text-fg-secondary" />
        <span className="text-[14px] font-semibold">{instance.display_name}</span>
        {data &&
          (data.last_pulled_at ? (
            <Badge tone="success">pulled {formatRelative(data.last_pulled_at)}</Badge>
          ) : (
            <Badge tone="muted">never pulled</Badge>
          ))}
        {data?.bridge_version && <Badge tone="outline">bridge {data.bridge_version}</Badge>}
        {bridge && (
          <Badge tone={bridge.local_allowed ? "warning" : "muted"}>
            {bridge.local_allowed ? "local tools allowed" : "local tools off"}
          </Badge>
        )}
        <span className="flex-1" />
        {canWrite && (
          <>
            <Button
              size="28"
              variant="ghost"
              disabled={nudge.isPending}
              onClick={() => {
                nudge.mutate({ path: { instance: instance.id } });
              }}
            >
              <RefreshCw aria-hidden />
              Pull now
            </Button>
            <Button
              size="28"
              variant="secondary"
              disabled={issue.isPending}
              onClick={() => {
                issue.mutate({ path: { instance: instance.id } });
              }}
            >
              {data?.last_pulled_at ? "Replace sync token" : "Set up sync"}
            </Button>
          </>
        )}
      </div>
      {nudge.data && !nudge.data.reached && (
        <p className="text-[12px] text-warning">
          The runtime didn&apos;t answer; it pulls on its own interval.
        </p>
      )}
      {token && <TokenOnce token={token} />}
      {issue.error && <p className="text-[12px] text-danger">{describeError(issue.error).reason}</p>}
      {reported.length > 0 && (
        <ul className="flex flex-col divide-y divide-border-subtle rounded-control border border-border-subtle">
          {reported.map((item) => {
            const state = STATE_TEXT[item.state] ?? { text: item.state, tone: "muted" as const };
            return (
              <li key={item.name} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[12.5px]">
                <code className="font-mono">{item.name}</code>
                <Badge tone={state.tone}>{state.text}</Badge>
                {(item.functions ?? []).length > 0 && (
                  <span className="text-fg-muted">{(item.functions ?? []).length} tool(s)</span>
                )}
                {item.detail && <span className="text-fg-muted">{item.detail}</span>}
              </li>
            );
          })}
        </ul>
      )}
      {data && !data.reachable && (
        <p className="text-[12px] text-fg-muted">
          The runtime&apos;s bridge didn&apos;t report its tool catalog status (it needs agnostic-bridge with
          the catalog set up).
        </p>
      )}
    </li>
  );
}

function Instances() {
  const instances = useInstances();
  if (instances.isPending) return <LoadingRows rows={2} />;
  if (!instances.data?.length)
    return <EmptyState title="No instances">Connect an instance first.</EmptyState>;
  return (
    <ul className="flex flex-col gap-3" aria-label="Instances">
      {instances.data.map((instance) => (
        <InstanceSync key={instance.id} instance={instance} />
      ))}
    </ul>
  );
}

/** `/access/tool-catalog`. */
export function ToolCatalogPage() {
  const [tab, setTab] = useState<Tab>("org");
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  return (
    <div className="flex flex-col gap-6 px-8 py-6">
      <PageIntro
        title={
          <span className="flex items-center gap-2">
            <Blocks aria-hidden className="size-5" /> Tool catalog
          </span>
        }
        actions={
          <Button
            onClick={() => {
              setAdding(true);
            }}
          >
            <Plus aria-hidden />
            Add to the catalog
          </Button>
        }
      >
        MCP servers and Agno toolkits that builders add to agents and teams as tool blocks. Every runtime
        pulls the entries for its instance; credentials stay on the runtime as environment variables.
      </PageIntro>
      <Tabs
        value={tab}
        onValueChange={(value) => {
          setTab(value as Tab);
        }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <TabsList>
            <TabsTrigger value="org">Organization</TabsTrigger>
            <TabsTrigger value="team">Teams</TabsTrigger>
            <TabsTrigger value="custom">Custom</TabsTrigger>
            <TabsTrigger value="instances">Instances</TabsTrigger>
          </TabsList>
          {tab !== "instances" && (
            <div className="relative flex w-64 items-center">
              <Search aria-hidden className="pointer-events-none absolute left-2.5 size-3.5 text-fg-muted" />
              <Input
                aria-label="Search the catalog"
                placeholder="Search…"
                className="pl-8"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                }}
              />
            </div>
          )}
        </div>
        {(["org", "team", "custom"] as const).map((level) => (
          <TabsContent key={level} value={level} className="mt-4 flex flex-col gap-3">
            <p className="text-[12.5px] text-fg-muted">{TAB_HINT[level]}</p>
            <EntryGrid level={level} query={query} />
          </TabsContent>
        ))}
        <TabsContent value="instances" className="mt-4">
          <Instances />
        </TabsContent>
      </Tabs>
      <EntryEditor open={adding} onOpenChange={setAdding} defaultLevel={tab === "instances" ? "org" : tab} />
    </div>
  );
}
