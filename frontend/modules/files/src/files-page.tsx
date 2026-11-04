import { contextFileProvenanceOptions, describeError } from "@agnostic/api";
import {
  findInstance,
  formatBytes,
  formatCount,
  formatRelative,
  formatWhen,
  useInstances,
} from "@agnostic/core";
import {
  Button,
  Callout,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  JsonView,
  KeyValueList,
  LoadingRows,
  MarkdownView,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  cn,
  toast,
  type Column,
} from "@agnostic/ui";
import { skipToken, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ChevronRight, Download, FileText, Folder, Lock, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import {
  accessSentence,
  baseName,
  extension,
  parseCsv,
  useContent,
  useEntries,
  useNamespaces,
  useSearchFiles,
  type Entry,
  type Namespace,
} from "./files-api";

type Filters = {
  ns?: string | undefined;
  dir: string;
  file?: string | undefined;
  owner?: string | undefined;
};

function readFilters(search: Record<string, unknown>): Filters {
  const text = (key: string) => (typeof search[key] === "string" && search[key] ? search[key] : undefined);
  return { ns: text("ns"), dir: text("dir") ?? "", file: text("file"), owner: text("owner") };
}

/** `/i/:instance/files?ns=&dir=&file=&owner=` (design spec B §4). */
export function FilesPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instance = params.instance ?? "";
  const filters = readFilters(search);
  const go = (next: Partial<Filters>) => {
    const merged = { ...filters, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/files`,
      search: Object.fromEntries(Object.entries(merged).filter(([, value]) => value)),
    });
  };

  const namespaces = useNamespaces(instance);
  const list = namespaces.data ?? [];
  const namespace = list.find((item) => item.namespace === filters.ns) ?? list[0];

  if (namespaces.error)
    return (
      <div className="px-8 pt-6">
        <ErrorState {...describeError(namespaces.error)} onRetry={() => void namespaces.refetch()} />
      </div>
    );
  if (namespaces.isPending)
    return (
      <div className="px-8 pt-6">
        <LoadingRows label="Loading file systems" />
      </div>
    );
  if (!namespace)
    return (
      <div className="px-8 pt-6">
        <EmptyState title="No agent file system on this instance">
          Give an agent a <code className="font-mono">FileSystem</code> (or the workspace tools) and its
          namespace shows up here.
        </EmptyState>
      </div>
    );
  return (
    <Workspace
      key={namespace.namespace}
      instance={instance}
      namespace={namespace}
      namespaces={list}
      filters={filters}
      go={go}
    />
  );
}

function Workspace({
  instance,
  namespace,
  namespaces,
  filters,
  go,
}: {
  instance: string;
  namespace: Namespace;
  namespaces: Namespace[];
  filters: Filters;
  go: (next: Partial<Filters>) => void;
}) {
  const instances = useInstances();
  const info = findInstance(instances.data, instance);
  const ns = namespace.namespace;
  const root = useEntries(instance, ns, "");
  const listing = useEntries(instance, ns, filters.dir);
  const [text, setText] = useState("");
  const deferred = useDeferredValue(text.trim());
  const found = useSearchFiles(instance, ns, filters.dir, deferred);
  const usage = root.data?.usage;
  const share = usage && usage.bytes_limit > 0 ? usage.total_bytes / usage.bytes_limit : 0;

  const entries: Entry[] = deferred
    ? (found.data?.entries ?? []).map((item) => ({
        path: item.path,
        type: "file",
        size_bytes: item.size_bytes,
        user_id: item.user_id ?? null,
      }))
    : (listing.data?.entries ?? []);
  const files = entries.filter((entry) => entry.type === "file");
  const folders = entries.filter((entry) => entry.type === "directory");
  const selected =
    files.find((entry) => entry.path === filters.file && (entry.user_id ?? undefined) === filters.owner) ??
    (filters.file
      ? { path: filters.file, type: "file" as const, user_id: filters.owner ?? null }
      : undefined);
  const { writers, readers } = accessSentence(namespace);

  const columns: Column<Entry>[] = [
    {
      id: "name",
      header: "Name",
      cell: (entry) => (
        <span className="flex min-w-0 items-center gap-2">
          {entry.type === "directory" ? (
            <Folder className="size-4 shrink-0 text-fg-muted" aria-hidden />
          ) : (
            <FileText className="size-4 shrink-0 text-fg-muted" aria-hidden />
          )}
          <span className="truncate font-mono text-[12.5px]">{baseName(entry.path)}</span>
        </span>
      ),
    },
    {
      id: "size",
      header: "Size",
      align: "right",
      cell: (entry) =>
        entry.size_bytes === null || entry.size_bytes === undefined ? "—" : formatBytes(entry.size_bytes),
    },
    {
      id: "modified",
      header: "Modified",
      cell: (entry) => <span className="text-fg-muted">{formatWhen(entry.updated_at)}</span>,
    },
    ...(namespace.user_isolation
      ? [
          {
            id: "owner",
            header: "Owner",
            cell: (entry: Entry) => (
              <span className="font-mono text-[12px] text-fg-muted">{entry.user_id ?? "shared"}</span>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-subtle px-6 py-3">
        <div className="flex items-center gap-2">
          {namespaces.length > 1 ? (
            <Select
              value={ns}
              onValueChange={(value) => {
                go({ ns: value, dir: "", file: undefined, owner: undefined });
              }}
            >
              <SelectTrigger aria-label="File system" className="h-8 w-60 font-mono text-[12px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {namespaces.map((item) => (
                  <SelectItem key={item.namespace} value={item.namespace}>
                    {item.namespace}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <span className="font-mono text-[13px]">{ns}</span>
          )}
          <span className="text-[12px] text-fg-muted">
            {namespace.backend_type}
            {namespace.table_name ? ` · ${namespace.table_name}` : ""}
          </span>
        </div>
        {usage && (
          <div className="flex w-64 flex-col gap-1" aria-label="Volume">
            <span className="flex justify-between text-[12px] text-fg-secondary">
              <span>
                Volume <code className="font-mono">{ns}</code>
              </span>
              <span>
                {formatBytes(usage.total_bytes)} of {formatBytes(usage.bytes_limit)}
              </span>
            </span>
            <span className="h-1 w-full rounded-full bg-track">
              <span
                className="block h-1 rounded-full bg-accent"
                style={{ width: `${String(Math.min(share, 1) * 100)}%` }}
              />
            </span>
          </div>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-wrap">
        <nav
          aria-label="Folders"
          className="flex min-w-0 flex-[1_1_210px] flex-col gap-2 overflow-y-auto border-r border-border-subtle px-3 pt-4 pb-6 lg:max-w-[250px]"
        >
          <p className="px-1 text-[12px] text-fg-muted">
            Read and written by agent file tools on {info?.display_name ?? instance}.
          </p>
          <TreeNode
            instance={instance}
            namespace={ns}
            path=""
            label={ns}
            depth={0}
            current={filters.dir}
            onOpen={(dir) => {
              go({ dir, file: undefined, owner: undefined });
            }}
          />
        </nav>

        <section className="flex min-w-0 flex-[2_1_420px] flex-col gap-4 overflow-y-auto px-6 pt-4 pb-8">
          <h1 className="flex flex-wrap items-center gap-1 font-mono text-[15px]">
            {["", ...filters.dir.split("/").filter(Boolean)].map((part, index, parts) => {
              const target = parts.slice(1, index + 1).join("/");
              const last = index === parts.length - 1;
              return (
                <span key={target || "root"} className="flex items-center gap-1">
                  {index > 0 && <span className="text-fg-faint">/</span>}
                  {last ? (
                    <span className="font-semibold">{part || ns}</span>
                  ) : (
                    <button
                      type="button"
                      className="cursor-pointer text-fg-secondary hover:text-fg"
                      onClick={() => {
                        go({ dir: target, file: undefined, owner: undefined });
                      }}
                    >
                      {part || ns}
                    </button>
                  )}
                </span>
              );
            })}
          </h1>

          <div className="flex gap-2 rounded-tile border border-border px-3 py-2.5 text-[12.5px] text-fg-secondary">
            <Lock className="mt-0.5 size-3.5 shrink-0 text-fg-muted" aria-hidden />
            <p>
              <strong className="text-fg">Folder access.</strong>{" "}
              {writers.length > 0
                ? `${writers.join(", ")} write${writers.length === 1 ? "s" : ""} here`
                : "No agent writes here"}
              {readers.length > 0 ? `; ${readers.join(", ")} can only read` : ""}.{" "}
              {namespace.user_isolation ? "Each user's files are kept apart. " : ""}
              Anyone with <code className="font-mono">filesystem:read</code> can browse and download. AgentOS
              file-system routes are read-only, so uploading, renaming and deleting happen through agents, not
              here.
            </p>
          </div>

          <div className="relative w-full max-w-[320px]">
            <Search
              className="pointer-events-none absolute top-2 left-2.5 size-4 text-fg-muted"
              aria-hidden
            />
            <Input
              aria-label="Search file contents"
              placeholder="Search file contents"
              className="h-8 pl-8"
              value={text}
              onChange={(event) => {
                setText(event.target.value);
              }}
            />
          </div>

          {(deferred ? found.error : listing.error) ? (
            <ErrorState {...describeError(deferred ? found.error : listing.error)} />
          ) : (deferred ? found.isPending : listing.isPending) ? (
            <LoadingRows rows={6} label="Loading files" />
          ) : (
            <div className="overflow-x-auto">
              <div className="min-w-[520px]">
                <DataTable
                  label="Files"
                  columns={columns}
                  rows={deferred ? files : [...folders, ...files]}
                  rowKey={(entry) => `${entry.type}:${entry.path}:${entry.user_id ?? ""}`}
                  selectedKey={selected ? `file:${selected.path}:${selected.user_id ?? ""}` : undefined}
                  onRowClick={(entry) => {
                    if (entry.type === "directory")
                      go({ dir: entry.path, file: undefined, owner: undefined });
                    else go({ file: entry.path, owner: entry.user_id ?? undefined });
                  }}
                  empty={
                    <EmptyState title={deferred ? "No file contains that text" : "This folder is empty"} />
                  }
                  footer={
                    <span>
                      {formatCount(files.length)} {files.length === 1 ? "file" : "files"}
                      {folders.length > 0 && !deferred ? ` · ${formatCount(folders.length)} folders` : ""}
                    </span>
                  }
                />
              </div>
            </div>
          )}
        </section>

        {selected && (
          <Preview
            key={`${selected.path}:${selected.user_id ?? ""}`}
            instance={instance}
            namespace={ns}
            entry={selected}
          />
        )}
      </div>
    </div>
  );
}

function TreeNode({
  instance,
  namespace,
  path,
  label,
  depth,
  current,
  onOpen,
}: {
  instance: string;
  namespace: string;
  path: string;
  label: string;
  depth: number;
  current: string;
  onOpen: (dir: string) => void;
}) {
  const [open, setOpen] = useState(depth === 0 || current === path || current.startsWith(`${path}/`));
  const entries = useEntries(instance, namespace, path, open);
  const children = (entries.data?.entries ?? []).filter((entry) => entry.type === "directory");
  const fileCount = (entries.data?.entries ?? []).filter((entry) => entry.type === "file").length;
  const active = current === path;
  return (
    <div className="flex flex-col">
      <button
        type="button"
        aria-expanded={open}
        aria-current={active ? "true" : undefined}
        onClick={() => {
          setOpen(active ? !open : true);
          onOpen(path);
        }}
        style={{ paddingLeft: 8 + depth * 14 }}
        className={cn(
          "flex h-7 cursor-pointer items-center gap-1.5 rounded-control pr-2 text-left font-mono text-[12.5px] hover:bg-surface-hover",
          active && "bg-segment-active text-fg-active",
        )}
      >
        <ChevronRight
          className={cn("size-3.5 shrink-0 text-fg-muted transition-transform", open && "rotate-90")}
          aria-hidden
        />
        <Folder className={cn("size-3.5 shrink-0", active ? "text-accent" : "text-fg-muted")} aria-hidden />
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {open && entries.data && fileCount > 0 && (
          <span className="text-[10.5px] text-fg-muted">{fileCount}</span>
        )}
      </button>
      {open &&
        children.map((child) => (
          <TreeNode
            key={child.path}
            instance={instance}
            namespace={namespace}
            path={child.path}
            label={baseName(child.path)}
            depth={depth + 1}
            current={current}
            onOpen={onOpen}
          />
        ))}
    </div>
  );
}

function Preview({ instance, namespace, entry }: { instance: string; namespace: string; entry: Entry }) {
  const [mode, setMode] = useState<"preview" | "source">("preview");
  const content = useContent(instance, namespace, entry);
  const provenanceOptions = contextFileProvenanceOptions({
    path: { instance },
    query: { path: entry.path, namespace },
  });
  const provenance = useQuery({
    ...provenanceOptions,
    queryFn: provenanceOptions.queryFn ?? skipToken,
    retry: false,
  });
  const name = baseName(entry.path);
  const kind = extension(entry.path);
  const body = content.data?.content ?? "";

  const download = () => {
    const url = URL.createObjectURL(new Blob([body], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <aside
      aria-label="File preview"
      className="flex min-w-0 flex-[2_1_380px] flex-col overflow-y-auto border-l border-border-subtle bg-rail lg:max-w-[520px]"
    >
      <header className="flex items-center justify-between gap-2 border-b border-border-subtle px-5 py-3">
        <h2 className="truncate font-mono text-[14px] font-semibold">{name}</h2>
        <div className="flex items-center gap-2">
          <SegmentedControl
            label="Preview mode"
            size="mini"
            value={mode}
            onValueChange={setMode}
            options={[
              { value: "preview", label: "Preview" },
              { value: "source", label: "Source" },
            ]}
          />
          <Button
            variant="icon"
            size="30"
            aria-label={`Download ${name}`}
            disabled={!content.data}
            onClick={download}
          >
            <Download aria-hidden />
          </Button>
        </div>
      </header>
      <div className="flex flex-col gap-4 px-5 py-4">
        {provenance.data?.partial && provenance.data.written && (
          <Callout tone="warning" title="Partial file">
            Run <code className="font-mono">{provenance.data.written.run_id}</code> ended in ERROR, so this
            file may stop part-way.
          </Callout>
        )}
        {content.error ? (
          <ErrorState {...describeError(content.error)} />
        ) : content.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : mode === "source" ? (
          <pre className="max-h-[480px] overflow-auto rounded-tile border border-border bg-inset px-3 py-2.5 font-mono text-[12px] leading-relaxed whitespace-pre-wrap">
            {body}
          </pre>
        ) : kind === "md" || kind === "markdown" ? (
          <MarkdownView>{body}</MarkdownView>
        ) : kind === "csv" ? (
          <CsvPreview text={body} />
        ) : kind === "json" ? (
          <JsonView value={safeJson(body)} label={name} />
        ) : (
          <pre className="max-h-[480px] overflow-auto rounded-tile border border-border bg-inset px-3 py-2.5 font-mono text-[12px] whitespace-pre-wrap">
            {body}
          </pre>
        )}
        {content.data?.truncated && (
          <p className="text-[12px] text-fg-muted">
            Showing the first {formatCount(content.data.limit)} characters of{" "}
            {formatBytes(content.data.size_bytes)}.
          </p>
        )}

        <section
          aria-label="Where this came from"
          className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4"
        >
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-[13.5px] font-semibold">Where this came from</h3>
            {provenance.data?.available && !provenance.data.exact && (
              <span className="text-[11.5px] text-fg-muted" title="Install agnostic-bridge for every trace">
                best effort · newest {provenance.data.scanned_traces} traces
              </span>
            )}
          </div>
          {provenance.isPending ? (
            <Skeleton className="h-24 w-full" />
          ) : provenance.error ? (
            <p className="text-[12.5px] text-fg-muted">{describeError(provenance.error).reason}</p>
          ) : !provenance.data.available ? (
            <p className="text-[12.5px] text-fg-muted">{provenance.data.reason}</p>
          ) : !provenance.data.written ? (
            <p className="text-[12.5px] text-fg-muted">
              No traced run wrote this file{provenance.data.exact ? "" : " among the newest traces"}.
            </p>
          ) : (
            <>
              <KeyValueList
                items={[
                  {
                    key: "by",
                    label: provenance.data.written.component_kind === "workflow" ? "Workflow" : "Agent",
                    value: provenance.data.written.component_id ?? "—",
                    mono: true,
                  },
                  {
                    key: "run",
                    label: "Run",
                    mono: true,
                    value: `${provenance.data.written.run_id ?? "—"} · ${provenance.data.written.run_status === "ERROR" ? "ERROR" : "COMPLETED"}`,
                  },
                  { key: "step", label: "Step", value: provenance.data.written.step ?? "—" },
                  { key: "tool", label: "Tool", value: provenance.data.written.tool, mono: true },
                  { key: "at", label: "Written", value: formatWhen(provenance.data.written.at) },
                  {
                    key: "read",
                    label: "Read by",
                    value:
                      provenance.data.read_by.length === 0
                        ? "Nobody yet"
                        : provenance.data.read_by
                            .map(
                              (reader) =>
                                `${reader.component_id}${reader.step ? `, step ${reader.step}` : ""}, ${reader.count === 1 ? "once" : `${String(reader.count)} times`}`,
                            )
                            .join("; "),
                  },
                ]}
              />
              <div className="flex flex-wrap gap-2">
                {provenance.data.written.session_id && (
                  <Button asChild variant="outline" size="28">
                    <Link
                      to={`/i/${encodeURIComponent(instance)}/sessions/${encodeURIComponent(provenance.data.written.session_id)}`}
                    >
                      Open session
                    </Link>
                  </Button>
                )}
                <Button asChild variant="outline" size="28">
                  <Link
                    to={`/i/${encodeURIComponent(instance)}/traces/${encodeURIComponent(provenance.data.written.trace_id)}`}
                  >
                    Open trace
                  </Link>
                </Button>
                <Button
                  variant="outline"
                  size="28"
                  onClick={() => {
                    void navigator.clipboard.writeText(entry.path).then(() => toast.success("Path copied"));
                  }}
                >
                  Copy path
                </Button>
              </div>
            </>
          )}
          <p className="text-[11.5px] text-fg-muted">
            Updated {formatRelative(entry.updated_at ?? content.data?.updated_at)}
          </p>
        </section>
      </div>
    </aside>
  );
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function CsvPreview({ text }: { text: string }) {
  const [header, ...rows] = parseCsv(text);
  if (!header) return <p className="text-[12.5px] text-fg-muted">Empty file.</p>;
  return (
    <div className="max-h-[480px] overflow-auto rounded-tile border border-border">
      <table className="w-full border-collapse font-mono text-[11.5px]" aria-label="CSV preview">
        <thead>
          <tr className="bg-surface text-left text-fg-muted">
            {header.map((cell, index) => (
              <th key={index} scope="col" className="border-b border-border-subtle px-2 py-1.5 font-medium">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-divider-row last:border-0">
              {row.map((cell, column) => (
                <td key={column} className="px-2 py-1.5 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
