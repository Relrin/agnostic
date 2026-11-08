import {
  artifactsListSharesOptions,
  artifactsListSharesQueryKey,
  artifactsRevokeShareMutation,
  describeError,
  type ShareOut,
} from "@agnostic/api";
import {
  ArtifactInspector,
  ArtifactRows,
  formatBytes,
  formatRelative,
  useRecentArtifacts,
  withQueryFn,
  type Artifact,
  type ArtifactKind,
} from "@agnostic/core";
import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  PageIntro,
  SegmentedControl,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

type KindFilter = "all" | ArtifactKind;
type View = "files" | "links";

const KINDS: readonly { value: KindFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "file", label: "Documents" },
  { value: "image", label: "Images" },
  { value: "video", label: "Video" },
  { value: "audio", label: "Audio" },
];

function chatPath(instance: string, artifact: Artifact): string | undefined {
  if (!artifact.component_id || !artifact.component_kind) return undefined;
  return `/i/${encodeURIComponent(instance)}/chat/${artifact.component_kind}s/${encodeURIComponent(artifact.component_id)}/${encodeURIComponent(artifact.session_id)}`;
}

function FilesView({
  instance,
  selectedKey,
  onSelect,
}: {
  instance: string;
  selectedKey: string | undefined;
  onSelect: (artifact: Artifact) => void;
}) {
  const [kind, setKind] = useState<KindFilter>("all");
  const [text, setText] = useState("");
  const needle = useDeferredValue(text.trim().toLowerCase());
  const recent = useRecentArtifacts(instance, { kind: kind === "all" ? undefined : kind });
  const rows = (recent.data?.data ?? []).filter(
    (artifact) =>
      !needle ||
      [artifact.filename, artifact.title, artifact.path, artifact.component_id]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
  );
  const selected = rows.find((artifact) => `${artifact.session_id}/${artifact.storage_key}` === selectedKey);
  const total = rows.reduce((sum, artifact) => sum + (artifact.size ?? 0), 0);

  return (
    <div className="flex min-h-0 flex-1 gap-4">
      <div className="flex w-[380px] shrink-0 flex-col gap-3">
        <SegmentedControl label="Kind" size="mini" value={kind} onValueChange={setKind} options={KINDS} />
        <div className="relative">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-fg-muted"
            aria-hidden
          />
          <Input
            aria-label="Filter files"
            placeholder="Filter by name, path or agent"
            className="pl-8"
            value={text}
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto rounded-tile border border-border bg-surface p-1.5">
          {recent.isPending ? (
            <LoadingRows rows={6} label="Loading files" />
          ) : recent.isError ? (
            <ErrorState {...describeError(recent.error)} onRetry={() => void recent.refetch()} />
          ) : rows.length === 0 ? (
            <EmptyState title={needle ? "No file matches" : "No files yet"}>
              {needle
                ? "Try another name."
                : "Files agents write show up here once a run stores them: give the agent media storage and collect its workspace or sandbox."}
            </EmptyState>
          ) : (
            <ArtifactRows artifacts={rows} onOpen={onSelect} selected={selected?.storage_key} showSession />
          )}
        </div>
        {recent.data && (
          <p className="text-[11.5px] text-fg-muted">
            {rows.length} {rows.length === 1 ? "file" : "files"} · {formatBytes(total)} · from the{" "}
            {recent.data.scanned_sessions} most recent sessions
          </p>
        )}
      </div>
      <section
        aria-label="Preview"
        className="flex min-w-0 flex-1 flex-col rounded-tile border border-border p-4"
      >
        {selected ? (
          <>
            <ArtifactInspector
              instance={instance}
              artifact={selected}
              heading={(title) => <h2 className="truncate text-[15px] font-semibold">{title}</h2>}
            />
            {chatPath(instance, selected) && (
              <Link
                to={chatPath(instance, selected) ?? "."}
                className="mt-3 text-[12px] text-info hover:underline"
              >
                Open the conversation that produced it
              </Link>
            )}
          </>
        ) : (
          <EmptyState title="Pick a file">Its preview, download and share link show here.</EmptyState>
        )}
      </section>
    </div>
  );
}

function LinksView({ instance }: { instance: string }) {
  const client = useQueryClient();
  const options = { path: { instance } };
  const shares = useQuery(withQueryFn(artifactsListSharesOptions(options)));
  const revoke = useMutation({
    ...artifactsRevokeShareMutation(),
    onSuccess: () => {
      toast("Link revoked. It stopped working.");
      void client.invalidateQueries({ queryKey: artifactsListSharesQueryKey(options) });
    },
  });
  if (shares.isPending) return <LoadingRows rows={4} label="Loading links" />;
  if (shares.isError) return <ErrorState {...describeError(shares.error)} />;
  const columns: Column<ShareOut>[] = [
    { id: "file", header: "File", cell: (share) => <span className="font-medium">{share.filename}</span> },
    {
      id: "audience",
      header: "Who can open it",
      cell: (share) => (share.audience === "link" ? "Anyone with the link" : "Members"),
    },
    {
      id: "state",
      header: "State",
      cell: (share) => <Badge tone={share.state === "active" ? "success" : "muted"}>{share.state}</Badge>,
    },
    {
      id: "expires",
      header: "Expires",
      cell: (share) => (share.state === "revoked" ? "—" : formatRelative(share.expires_at)),
    },
    { id: "opened", header: "Opened", cell: (share) => `${String(share.opened_count)}×` },
    { id: "by", header: "Shared by", cell: (share) => share.created_by_name },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      cell: (share) =>
        share.state === "active" ? (
          <Button
            variant="destructive-text"
            size="28"
            disabled={revoke.isPending}
            onClick={() => {
              revoke.mutate({ path: { instance, share_id: share.id } });
            }}
          >
            Revoke
          </Button>
        ) : null,
    },
  ];
  if (shares.data.data.length === 0)
    return <EmptyState title="No share links yet">Open a file and choose Share to make one.</EmptyState>;
  return (
    <DataTable label="Share links" columns={columns} rows={shares.data.data} rowKey={(share) => share.id} />
  );
}

/** `/i/:instance/artifacts?view=&file=`: the files agents produced on the instance, and the links to them. */
export function ArtifactsPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instance = params.instance ?? "";
  const view: View = search.view === "links" ? "links" : "files";
  const file = typeof search.file === "string" ? search.file : undefined;
  const go = (next: { view?: View; file?: string | undefined }) => {
    const merged = { view, file, ...next };
    void navigate({
      to: `/i/${encodeURIComponent(instance)}/artifacts`,
      search: Object.fromEntries(
        Object.entries(merged).filter(([key, value]) => value && !(key === "view" && value === "files")),
      ),
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 px-8 pt-6 pb-6">
      <PageIntro title="Files">
        What agents produced in their runs: reports, pages, data, charts and media, collected from their
        workspaces and sandboxes. Previews run isolated from this app.
      </PageIntro>
      <Tabs
        value={view}
        onValueChange={(value) => {
          go({ view: value as View });
        }}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList>
          <TabsTrigger value="files">Files</TabsTrigger>
          <TabsTrigger value="links">Share links</TabsTrigger>
        </TabsList>
        <TabsContent value="files" className="flex min-h-0 flex-1 pt-4">
          <FilesView
            instance={instance}
            selectedKey={file}
            onSelect={(artifact) => {
              go({ file: `${artifact.session_id}/${artifact.storage_key}` });
            }}
          />
        </TabsContent>
        <TabsContent value="links" className="pt-4">
          <LinksView instance={instance} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
