import {
  describeError,
  studioRefreshRegistry,
  studioRegistryEntryOptions,
  studioRegistryOptions,
  studioRegistryQueryKey,
  type RegistryEntryOut,
} from "@agnostic/api";
import { findInstance, useInstances, withQueryFn } from "@agnostic/core";
import {
  Breadcrumb,
  Button,
  Callout,
  EmptyState,
  ErrorState,
  Input,
  KeyValueList,
  LoadingRows,
  StatusPill,
  Tabs,
  TabsList,
  TabsTrigger,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { RefreshCw, ShieldAlert } from "lucide-react";
import { useState } from "react";

const TYPES: readonly { type: string; label: string }[] = [
  { type: "tool", label: "Tools" },
  { type: "model", label: "Models" },
  { type: "db", label: "Databases" },
  { type: "vector_db", label: "Vector DBs" },
  { type: "schema", label: "Schemas" },
  { type: "function", label: "Functions" },
  { type: "knowledge", label: "Knowledge" },
  { type: "memory_manager", label: "Memory managers" },
  { type: "session_summary_manager", label: "Summary managers" },
  { type: "learning", label: "Learning" },
  { type: "agent", label: "Agents" },
  { type: "team", label: "Teams" },
  { type: "workflow", label: "Workflows" },
];

/** Type colours from the design tokens (a square before each name). */
const TYPE_COLOR: Record<string, string> = {
  tool: "bg-info",
  model: "bg-accent",
  db: "bg-fg-secondary",
  vector_db: "bg-[var(--reg-vector-db,#59D4E8)]",
  schema: "bg-[var(--reg-schema)]",
  function: "bg-[var(--reg-function)]",
  knowledge: "bg-[var(--reg-knowledge)]",
  memory_manager: "bg-entity-team",
  session_summary_manager: "bg-entity-team",
  learning: "bg-entity-team",
  agent: "bg-entity-agent",
  team: "bg-entity-team",
  workflow: "bg-entity-workflow",
};

function TypeSquare({ type }: { type: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-[7px] shrink-0 rounded-[2px]", TYPE_COLOR[type] ?? "bg-fg-muted")}
    />
  );
}

function EntryDetail({ instance, type, name }: { instance: string; type: string; name: string }) {
  const detail = useQuery(
    withQueryFn(studioRegistryEntryOptions({ path: { instance, entry_type: type, name } })),
  );
  if (detail.isPending) return <LoadingRows rows={5} label="Loading the entry" />;
  if (detail.isError) return <ErrorState {...describeError(detail.error)} />;
  const { entry, used_by: usedBy } = detail.data;
  const scoped = `/i/${encodeURIComponent(instance)}`;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <span className="rounded-badge border border-current px-1.5 font-mono text-[10.5px] font-semibold text-fg-secondary uppercase">
          {type.replace(/_/g, " ")}
        </span>
        <StatusPill status={entry.status.toUpperCase()} />
      </div>
      <h2 className="font-mono text-[17px] font-semibold">{entry.name}</h2>
      <p className="text-[12.5px] text-fg-secondary">{entry.blurb}</p>
      {entry.details.length > 0 && (
        <KeyValueList
          items={entry.details.map((item) => ({
            key: item.key,
            label: item.key,
            value: item.value,
            mono: true,
          }))}
        />
      )}
      {entry.source && (
        <p className="font-mono text-[11.5px] text-fg-muted">
          {`${entry.source.file ?? entry.source.module ?? ""}${entry.source.line ? `:${String(entry.source.line)}` : ""}`}
        </p>
      )}
      {entry.code && (
        <div className="overflow-hidden rounded-card border border-border">
          <div className="border-b border-border-subtle bg-canvas px-3 py-1.5 font-mono text-[11px] text-fg-muted">
            {entry.code_label}
          </div>
          <pre className="max-h-64 overflow-auto bg-inset p-3 font-mono text-[12px]">{entry.code}</pre>
        </div>
      )}
      {entry.requires_approval && (
        <Callout tone="warning" title="Requires approval">
          <span className="inline-flex items-start gap-1.5">
            <ShieldAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            Runs pause in Approvals until someone holding approvals:write resolves them.
          </span>
        </Callout>
      )}
      <section aria-labelledby="used-by" className="flex flex-col gap-2">
        <h3 id="used-by" className="text-[13px] font-medium">{`Used by ${String(usedBy.length)}`}</h3>
        {usedBy.length === 0 ? (
          <p className="text-[12.5px] text-fg-muted">Not used by any agent, team or workflow yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {usedBy.map((item) => (
              <li key={item.component_id}>
                <Link
                  to={`${scoped}/studio/${item.component_kind}s/${encodeURIComponent(item.component_id)}`}
                  className="flex items-center gap-2 rounded-control px-2 py-1 hover:bg-surface-hover"
                >
                  <TypeSquare type={item.component_kind} />
                  <span className="font-mono text-[12.5px]">{item.component_name}</span>
                  <span className="text-[12px] text-fg-muted">{item.versions_text || "defined in code"}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
      <Callout
        tone={entry.availability.kind === "unavailable" ? "warning" : "availability"}
        title={entry.availability.title}
      >
        {entry.availability.text}
      </Callout>
    </div>
  );
}

/** `/i/:instance/studio/registry/:type?/:name?`: everything Studio can compose with, read-only. */
export function RegistryPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const instance = params.instance ?? "";
  const instances = useInstances();
  const found = findInstance(instances.data, instance);
  const [filter, setFilter] = useState("");
  const options = studioRegistryOptions({ path: { instance } });
  const catalog = useQuery(withQueryFn(options));
  const type = params.type ?? "tool";
  const selected = params.name;
  const scoped = `/i/${encodeURIComponent(instance)}/studio/registry`;
  const refresh = useMutation({
    mutationFn: async () => (await studioRefreshRegistry({ path: { instance }, throwOnError: true })).data,
    onSuccess: (data) => {
      queryClient.setQueryData(studioRegistryQueryKey({ path: { instance } }), data);
      void queryClient.invalidateQueries({ queryKey: [{ _id: "studioRegistryEntry" }] });
      toast.success("The registry and its used-by index are up to date.");
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const entries = catalog.data?.entries ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = entries.filter(
    (entry: RegistryEntryOut) =>
      (type === "all" || entry.type === type) && (!needle || entry.name.toLowerCase().includes(needle)),
  );
  const counts = catalog.data?.counts ?? {};
  const select = (next: RegistryEntryOut) => {
    void navigate({ to: `${scoped}/${next.type}/${encodeURIComponent(next.name)}` });
  };
  return (
    <div className="flex flex-1 flex-col">
      <div className="flex items-center gap-3 border-b border-border-subtle px-6 py-2.5">
        <Breadcrumb items={[{ label: "Studio" }, { label: "Registry" }]} />
        <span className="flex-1" />
        <Button
          variant="icon"
          size="32"
          aria-label="Refresh registry"
          disabled={refresh.isPending}
          onClick={() => {
            refresh.mutate();
          }}
        >
          <RefreshCw aria-hidden className={cn(refresh.isPending && "animate-spin")} />
        </Button>
      </div>
      <div className="flex flex-1 flex-wrap gap-6">
        <div className="flex min-w-[320px] flex-[3_1_560px] flex-col gap-4 px-7 py-5">
          <div className="flex flex-col gap-1">
            <h1 className="text-[22px] font-semibold tracking-tight">Registry</h1>
            <p className="text-[13px] text-fg-secondary">
              {`Everything Studio can compose with on ${found?.display_name ?? instance}. Entries are defined in code, so they're read-only here; each one shows where it's used.`}
            </p>
          </div>
          <Tabs
            value={type}
            onValueChange={(next) => {
              void navigate({ to: next === "tool" ? scoped : `${scoped}/${next}` });
            }}
          >
            <TabsList variant="pill" aria-label="Entry types" className="overflow-x-auto">
              <TabsTrigger value="all" count={catalog.data?.total ?? 0} className="whitespace-nowrap">
                All
              </TabsTrigger>
              {TYPES.filter((item) => (counts[item.type] ?? 0) > 0 || item.type === "tool").map((item) => (
                <TabsTrigger
                  key={item.type}
                  value={item.type}
                  count={counts[item.type] ?? 0}
                  className="whitespace-nowrap"
                >
                  {item.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <div className="flex items-center gap-3">
            <Input
              aria-label="Filter by name"
              placeholder="Filter by name"
              className="h-8 w-60"
              value={filter}
              onChange={(event) => {
                setFilter(event.target.value);
              }}
            />
            <span className="text-[12.5px] text-fg-muted">{`${String(shown.length)} of ${String(catalog.data?.total ?? 0)} entries`}</span>
          </div>
          {catalog.data && !catalog.data.bridge && (
            <p className="text-[12px] text-fg-muted">
              Without agnostic-bridge, tools discovered on components defined in code show as registered.
            </p>
          )}
          <div className="max-h-[700px] overflow-auto rounded-card border border-border bg-surface">
            <table className="w-full border-collapse text-[13px]" aria-label="Registry entries">
              <thead>
                <tr className="border-b border-border-subtle text-left font-mono text-[11px] tracking-[0.04em] text-fg-muted uppercase">
                  <th scope="col" className="px-3 py-2 font-normal">
                    Name
                  </th>
                  <th scope="col" className="px-2 py-2 font-normal">
                    Type
                  </th>
                  <th scope="col" className="px-2 py-2 font-normal">
                    Details
                  </th>
                  <th scope="col" className="px-2 py-2 font-normal">
                    Status
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-normal">
                    Used by
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((entry) => {
                  const active = entry.name === selected && entry.type === (params.type ?? entry.type);
                  return (
                    <tr
                      key={`${entry.type}:${entry.name}`}
                      aria-current={active ? "true" : undefined}
                      className={cn(
                        "border-b border-divider-row last:border-0 hover:bg-surface-hover",
                        active && "bg-row-selected shadow-[inset_2px_0_0_var(--accent)]",
                      )}
                    >
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          className="inline-flex items-center gap-2 font-mono hover:underline"
                          onClick={() => {
                            select(entry);
                          }}
                        >
                          <TypeSquare type={entry.type} />
                          {entry.name}
                        </button>
                      </td>
                      <td className="px-2 py-2 text-[12.5px] text-fg-secondary">
                        {entry.type.replace(/_/g, " ")}
                      </td>
                      <td className="max-w-[320px] truncate px-2 py-2 font-mono text-[11.5px] text-fg-muted">
                        {entry.meta}
                      </td>
                      <td className="px-2 py-2">
                        <StatusPill status={entry.status.toUpperCase()} />
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{entry.used_by_count}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {catalog.isPending && (
              <div className="p-3">
                <LoadingRows rows={6} label="Loading the registry" />
              </div>
            )}
            {catalog.isError && (
              <div className="p-3">
                <ErrorState
                  {...describeError(catalog.error)}
                  onRetry={() => {
                    void catalog.refetch();
                  }}
                />
              </div>
            )}
            {catalog.isSuccess && shown.length === 0 && (
              <div className="p-4">
                <EmptyState title="No entries match." />
              </div>
            )}
          </div>
        </div>
        <aside
          aria-label="Entry details"
          className="max-w-[400px] min-w-[300px] flex-[1_1_320px] border-l border-border-subtle bg-rail px-5 py-5"
        >
          {selected && params.type ? (
            <EntryDetail instance={instance} type={params.type} name={selected} />
          ) : (
            <EmptyState title="Pick an entry">
              See its details, where it's used and whether Studio can build with it.
            </EmptyState>
          )}
        </aside>
      </div>
    </div>
  );
}
