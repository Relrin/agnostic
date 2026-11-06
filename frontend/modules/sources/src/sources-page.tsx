// Code sources: the repositories (and local folders) Studio syncs with on this instance. Left, the source cards with
// their path mappings and sync policy, and the org's connections to git hosts; right, the selected source's changes:
// incoming (repo → Studio drafts), outgoing (Studio → repo) with the commit composer, conflicts with both sides, and
// pull requests.
import {
  describeError,
  sourcesChangeDiff,
  sourcesDeleteSource,
  sourcesFetchSource,
  sourcesIncludeChange,
  sourcesPullChanges,
  sourcesRefreshOutgoing,
  sourcesResolveConflict,
  sourcesUpdateSource,
  type ChangeOut,
  type ConflictOut,
  type PathMappingIo,
  type CodeSourceOut,
  type SyncPolicyIo,
} from "@agnostic/api";
import { formatRelative, useCan } from "@agnostic/core";
import { CodeView } from "@agnostic/editor";
import { CommitComposer, MergeDialog, conflictValue, sha7 } from "@agnostic/studio";
import {
  Badge,
  Button,
  Callout,
  Card,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  PageIntro,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Switch,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, Folder, GitBranch, Plus, RefreshCw, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { ConnectWizard } from "./connect-wizard";
import { ConnectionsCard } from "./connections";
import {
  PUBLISH_MODES,
  PULL_MODES,
  TARGET_LABEL,
  chips,
  useChanges,
  useRefresh,
  useSources,
} from "./sources-api";

const CHIP_TONE = {
  info: "border-info/40 text-info",
  warning: "border-warning/40 text-warning",
  danger: "border-danger/40 text-danger",
  success: "border-accent/40 text-accent",
  muted: "border-border-strong text-fg-muted",
} as const;

function SourceCard({
  source,
  selected,
  onSelect,
}: {
  source: CodeSourceOut;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={cn(
          "flex w-full flex-col gap-2 rounded-card border bg-surface p-3 text-left",
          selected ? "border-accent bg-canvas ring-3 ring-accent/12" : "border-border hover:bg-surface-hover",
        )}
      >
        <span className="flex items-center gap-2.5">
          <span aria-hidden className="grid size-[30px] place-items-center rounded-control bg-segment-active">
            {source.provider === "local" ? <Folder className="size-4" /> : <GitBranch className="size-4" />}
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="text-[13px] font-medium">{source.provider_label}</span>
            <span className="truncate font-mono text-[11.5px] text-fg-secondary">
              {source.provider === "local" ? source.repo : `${source.repo} · ${source.branch}`}
            </span>
          </span>
        </span>
        <span className="flex flex-wrap gap-1.5">
          {chips(source).map((chip) => (
            <span
              key={chip.label}
              className={cn("rounded-[5px] border px-1.5 py-px font-mono text-[11px]", CHIP_TONE[chip.tone])}
            >
              {chip.label}
            </span>
          ))}
        </span>
        <span className="text-[12px] text-fg-muted">
          {source.auth}
          {source.head_sha && source.last_fetched_at
            ? ` · pulled ${formatRelative(source.last_fetched_at)} at ${sha7(source.head_sha)}`
            : ""}
        </span>
        {source.status_detail && <span className="text-[12px] text-warning">{source.status_detail}</span>}
      </button>
    </li>
  );
}

function DisconnectSource({
  instance,
  source,
  onDone,
}: {
  instance: string;
  source: CodeSourceOut;
  onDone: () => void;
}) {
  const refresh = useRefresh();
  const [open, setOpen] = useState(false);
  const remove = useMutation({
    mutationFn: async () =>
      sourcesDeleteSource({ path: { instance, source_id: source.id }, throwOnError: true }),
    onSuccess: () => {
      toast.success(`Disconnected ${source.repo}; its components stay in Studio.`);
      setOpen(false);
      refresh();
      onDone();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const label = source.provider === "local" ? source.repo : `${source.repo} · ${source.branch}`;
  return (
    <>
      <Button
        variant="destructive-outline"
        size="28"
        className="self-start"
        onClick={() => {
          setOpen(true);
        }}
      >
        Disconnect source
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{`Disconnect ${label}?`}</DialogTitle>
            <DialogDescription>
              Its components stay in Studio, unbound. Pending changes and conflicts are dropped, and the
              webhook and the mirror are removed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => {
                setOpen(false);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive-outline"
              disabled={remove.isPending}
              onClick={() => {
                remove.mutate();
              }}
            >
              Disconnect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function PathMappingCard({
  instance,
  source,
  canEdit,
}: {
  instance: string;
  source: CodeSourceOut;
  canEdit: boolean;
}) {
  const refresh = useRefresh();
  const [editing, setEditing] = useState<PathMappingIo[] | undefined>(undefined);
  const save = useMutation({
    mutationFn: async (mappings: PathMappingIo[]) =>
      (
        await sourcesUpdateSource({
          path: { instance, source_id: source.id },
          body: { mappings, version: source.version },
          throwOnError: true,
        })
      ).data,
    onSuccess: () => {
      toast.success("Saved the path mappings; Studio reads the repository again.");
      setEditing(undefined);
      refresh();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const rows =
    editing ?? source.mappings.map(({ glob, target_kind, writable }) => ({ glob, target_kind, writable }));
  return (
    <Card
      title="Path mapping"
      action={
        canEdit && !editing ? (
          <Button
            variant="link"
            size="28"
            onClick={() => {
              setEditing(rows);
            }}
          >
            Edit
          </Button>
        ) : undefined
      }
    >
      <ul aria-label="Path mappings" className="flex flex-col gap-1.5">
        {rows.map((mapping, index) => {
          const shown = source.mappings[index];
          const muted = mapping.target_kind === "registry" || mapping.target_kind === "ignored";
          if (!editing) {
            return (
              <li key={`${mapping.glob}-${String(index)}`} className="flex items-center gap-2 text-[12.5px]">
                <code className={cn("font-mono", mapping.target_kind === "ignored" && "text-fg-muted")}>
                  {mapping.glob}
                </code>
                <span className="flex-1 border-b border-dotted border-border" aria-hidden />
                <span className={cn(muted ? "text-fg-muted" : "text-fg-secondary")}>
                  {TARGET_LABEL[mapping.target_kind]}
                  {mapping.target_kind === "registry"
                    ? " · read-only"
                    : mapping.target_kind !== "ignored" && shown?.count !== null && shown?.count !== undefined
                      ? ` · ${String(shown.count)}`
                      : ""}
                </span>
              </li>
            );
          }
          return (
            <li key={String(index)} className="flex items-center gap-2">
              <Input
                mono
                aria-label={`Pattern ${String(index + 1)}`}
                value={mapping.glob}
                onChange={(event) => {
                  setEditing(
                    rows.map((row, at) => (at === index ? { ...row, glob: event.target.value } : row)),
                  );
                }}
              />
              <Select
                value={mapping.target_kind}
                onValueChange={(value) => {
                  setEditing(
                    rows.map((row, at) =>
                      at === index ? { ...row, target_kind: value as PathMappingIo["target_kind"] } : row,
                    ),
                  );
                }}
              >
                <SelectTrigger aria-label={`Maps to ${String(index + 1)}`} className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(TARGET_LABEL).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="ghost"
                size="28"
                aria-label={`Remove ${mapping.glob}`}
                onClick={() => {
                  setEditing(rows.filter((_, at) => at !== index));
                }}
              >
                Remove
              </Button>
            </li>
          );
        })}
      </ul>
      {editing && (
        <div className="flex gap-2">
          <Button
            variant="dashed-add"
            size="28"
            onClick={() => {
              setEditing([...rows, { glob: "", target_kind: "agents", writable: true }]);
            }}
          >
            <Plus aria-hidden />
            Add a pattern
          </Button>
          <span className="flex-1" />
          <Button
            variant="ghost"
            size="28"
            onClick={() => {
              setEditing(undefined);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="28"
            disabled={save.isPending || rows.some((row) => !row.glob.trim())}
            onClick={() => {
              save.mutate(rows);
            }}
          >
            Save mappings
          </Button>
        </div>
      )}
    </Card>
  );
}

function RadioGroup<T extends string>({
  legend,
  name,
  value,
  options,
  disabled,
  onChange,
}: {
  legend: string;
  name: string;
  value: T;
  options: readonly { value: T; label: string }[];
  disabled: boolean;
  onChange: (value: T) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1 text-[12.5px] font-medium text-fg-secondary">{legend}</legend>
      {options.map((option) => (
        <label key={option.value} className="flex items-center gap-2 text-[12.5px]">
          <input
            type="radio"
            name={name}
            className="accent-accent"
            checked={option.value === value}
            disabled={disabled}
            onChange={() => {
              onChange(option.value);
            }}
          />
          {option.label}
        </label>
      ))}
    </fieldset>
  );
}

function SyncPolicyCard({
  instance,
  source,
  canEdit,
}: {
  instance: string;
  source: CodeSourceOut;
  canEdit: boolean;
}) {
  const refresh = useRefresh();
  const save = useMutation({
    mutationFn: async (policy: SyncPolicyIo) =>
      (
        await sourcesUpdateSource({
          path: { instance, source_id: source.id },
          body: { policy, version: source.version },
          throwOnError: true,
        })
      ).data,
    onSuccess: () => {
      toast.success("Saved the sync policy.");
      refresh();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const policy = source.policy;
  const change = (next: Partial<SyncPolicyIo>) => {
    save.mutate({ ...policy, ...next });
  };
  const disabled = !canEdit || save.isPending;
  const local = source.provider === "local";
  return (
    <Card title="Sync policy">
      <RadioGroup
        legend="Pull from repo"
        name={`pull-${source.id}`}
        value={policy.pull_mode ?? "on_demand"}
        options={PULL_MODES.map((mode) =>
          mode.value === "on_push_as_drafts"
            ? { ...mode, label: `On every push to ${source.branch}, as drafts` }
            : mode,
        )}
        disabled={disabled}
        onChange={(value) => {
          change({ pull_mode: value });
        }}
      />
      {!local && (
        <RadioGroup
          legend="When Studio publishes"
          name={`publish-${source.id}`}
          value={policy.publish_mode ?? "open_pr"}
          options={PUBLISH_MODES.map((mode) =>
            mode.value === "commit_direct" ? { ...mode, label: `Commit directly to ${source.branch}` } : mode,
          )}
          disabled={disabled}
          onChange={(value) => {
            change({ publish_mode: value });
          }}
        />
      )}
      {!local && policy.publish_mode === "open_pr" && (
        <Switch
          label="Block publish until the pull request merges"
          checked={policy.block_publish_until_merged ?? false}
          disabled={disabled}
          onCheckedChange={(checked) => {
            change({ block_publish_until_merged: checked });
          }}
        />
      )}
      {!local && (
        <p className="font-mono text-[11.5px] text-fg-muted">{`Branches ${policy.branch_template ?? ""} · commits “${policy.commit_template ?? ""}”`}</p>
      )}
    </Card>
  );
}

function Stats({ change }: { change: ChangeOut }) {
  return (
    <span className="font-mono text-[11.5px]">
      <span className="text-accent">{`+${String(change.additions)}`}</span>{" "}
      <span className="text-danger">{`−${String(change.deletions)}`}</span>
    </span>
  );
}

function DiffSheet({
  instance,
  sourceId,
  change,
  onClose,
}: {
  instance: string;
  sourceId: string;
  change: ChangeOut;
  onClose: () => void;
}) {
  const diff = useQuery({
    queryKey: ["sourcesChangeDiff", instance, sourceId, change.id],
    queryFn: async () =>
      (
        await sourcesChangeDiff({
          path: { instance, source_id: sourceId, change_id: change.id },
          throwOnError: true,
        })
      ).data,
  });
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent className="w-[min(760px,100vw)]">
        <div className="flex flex-col gap-1">
          <SheetTitle className="font-mono">{change.path}</SheetTitle>
          <SheetDescription>{change.message ?? change.summary ?? ""}</SheetDescription>
        </div>
        {diff.isPending ? (
          <LoadingRows rows={6} label="Loading the diff" />
        ) : diff.isError ? (
          <ErrorState {...describeError(diff.error)} />
        ) : (
          <CodeView
            value={diff.data.unified || "No changes."}
            language="python"
            ariaLabel={`Diff of ${change.path}`}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function IncomingSection({
  instance,
  source,
  changes,
  canWrite,
}: {
  instance: string;
  source: CodeSourceOut;
  changes: ChangeOut[];
  canWrite: boolean;
}) {
  const refresh = useRefresh();
  const [diff, setDiff] = useState<ChangeOut | undefined>(undefined);
  const include = useMutation({
    mutationFn: async ({ change, included }: { change: ChangeOut; included: boolean }) =>
      sourcesIncludeChange({
        path: { instance, source_id: source.id, change_id: change.id },
        body: { included },
        throwOnError: true,
      }),
    onSuccess: refresh,
    onError: (error) => toast.error(describeError(error).reason),
  });
  const pullable = changes.filter(
    (change) =>
      change.included && (change.outcome.action === "new_draft" || change.outcome.action === "new_component"),
  );
  const pull = useMutation({
    mutationFn: async () =>
      (
        await sourcesPullChanges({
          path: { instance, source_id: source.id },
          body: { change_ids: pullable.map((change) => change.id) },
          throwOnError: true,
        })
      ).data,
    onSuccess: (results) => {
      const done = results.filter((result) => typeof result.version === "number");
      if (done.length)
        toast.success(`Pulled ${String(done.length)} as draft${done.length === 1 ? "" : "s"}.`);
      for (const result of results) if (result.error) toast.error(`${result.path}: ${result.error}`);
      refresh();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  return (
    <section aria-label="Incoming" className="flex flex-col gap-2">
      <header className="flex items-center gap-2">
        <h3 className="text-[13px] font-semibold">↓ Incoming</h3>
        <span className="text-[12px] text-fg-muted">repo → Studio drafts</span>
        <span className="flex-1" />
        {canWrite && (
          <Button
            variant="primary"
            size="28"
            disabled={pullable.length === 0 || pull.isPending}
            onClick={() => {
              pull.mutate();
            }}
          >
            <ArrowDown aria-hidden />
            {`Pull ${String(pullable.length)} as draft${pullable.length === 1 ? "" : "s"}`}
          </Button>
        )}
      </header>
      {changes.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">Nothing new in the repository since the last pull.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {changes.map((change) => (
            <li
              key={change.id}
              className="flex gap-3 rounded-[9px] border border-border-subtle bg-canvas px-3 py-2.5"
            >
              <Checkbox
                aria-label={`Include ${change.path}`}
                checked={change.included}
                disabled={!canWrite || include.isPending}
                onCheckedChange={(checked) => {
                  include.mutate({ change, included: checked === true });
                }}
              />
              <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-[12.5px]">
                <span className="flex flex-wrap items-center gap-2">
                  <code className="font-mono">{change.path}</code>
                  <Stats change={change} />
                </span>
                <span className="text-fg-secondary">
                  <code className="font-mono">{sha7(change.commit_sha)}</code>
                  {change.message ? ` “${change.message}”` : ""}
                  {change.author_name ? ` · ${change.author_name}` : ""}
                  {change.committed_at ? `, ${formatRelative(change.committed_at)}` : ""}
                </span>
                <span className={change.outcome.action === "conflict" ? "text-danger" : "text-fg"}>
                  {change.outcome_sentence}
                </span>
                {change.diagnostics
                  .filter((item) => item.severity === "error")
                  .slice(0, 2)
                  .map((item) => (
                    <span key={String(item.message)} className="text-warning">
                      {String(item.message)}
                    </span>
                  ))}
              </div>
              <Button
                variant="link"
                size="28"
                onClick={() => {
                  setDiff(change);
                }}
              >
                Diff
              </Button>
            </li>
          ))}
        </ul>
      )}
      {diff && (
        <DiffSheet
          instance={instance}
          sourceId={source.id}
          change={diff}
          onClose={() => {
            setDiff(undefined);
          }}
        />
      )}
    </section>
  );
}

function OutgoingSection({
  instance,
  source,
  changes,
  canWrite,
}: {
  instance: string;
  source: CodeSourceOut;
  changes: ChangeOut[];
  canWrite: boolean;
}) {
  const refresh = useRefresh();
  const scoped = `/i/${encodeURIComponent(instance)}`;
  const look = useMutation({
    mutationFn: async () =>
      (await sourcesRefreshOutgoing({ path: { instance, source_id: source.id }, throwOnError: true })).data,
    onSuccess: refresh,
    onError: (error) => toast.error(describeError(error).reason),
  });
  const writable = source.policy.publish_mode !== "no_write_back" || source.provider === "local";
  return (
    <section aria-label="Outgoing" className="flex flex-col gap-2">
      <header className="flex items-center gap-2">
        <h3 className="text-[13px] font-semibold">↑ Outgoing</h3>
        <span className="text-[12px] text-fg-muted">Studio drafts → repo</span>
        <span className="flex-1" />
        {canWrite && writable && (
          <Button
            variant="ghost"
            size="28"
            disabled={look.isPending}
            onClick={() => {
              look.mutate();
            }}
          >
            <RefreshCw aria-hidden />
            Look for changes
          </Button>
        )}
      </header>
      {changes.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">
          {writable ? "The repository says what Studio has." : "This source doesn't write back."}
        </p>
      ) : (
        <>
          <ul className="flex flex-col gap-2">
            {changes.map((change) => (
              <li
                key={change.id}
                className="flex gap-3 rounded-[9px] border border-border-subtle bg-canvas px-3 py-2.5"
              >
                <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-[12.5px]">
                  <span className="flex flex-wrap items-center gap-2">
                    <code className="font-mono">{change.path}</code>
                    <Stats change={change} />
                    {change.status === "committing" && <Badge tone="muted">committing…</Badge>}
                  </span>
                  <span className="text-fg-secondary">
                    {`Draft v${String(change.draft_version ?? "")}${change.author_name ? ` by ${change.author_name}` : ""} · ${change.summary ?? ""}`}
                  </span>
                  {change.outcome.action === "blocked" && (
                    <span className="text-warning">
                      Changed in the repository too: pull the incoming change first.
                    </span>
                  )}
                </div>
                <Button asChild variant="link" size="28">
                  <Link
                    to={`${scoped}/studio/${change.component_kind ?? "agent"}s/${change.component_id ?? ""}`}
                  >
                    Open
                  </Link>
                </Button>
              </li>
            ))}
          </ul>
          {canWrite && (
            <CommitComposer
              instance={instance}
              sourceId={source.id}
              changes={changes.filter(
                (change) => change.status === "pending" && change.outcome.action !== "blocked",
              )}
              onCommitted={refresh}
            />
          )}
        </>
      )}
    </section>
  );
}

function ConflictCard({
  instance,
  sourceId,
  conflict,
  canWrite,
  onMerge,
}: {
  instance: string;
  sourceId: string;
  conflict: ConflictOut;
  canWrite: boolean;
  onMerge: () => void;
}) {
  const refresh = useRefresh();
  const resolve = useMutation({
    mutationFn: async (resolution: "keep_studio" | "keep_repo") =>
      sourcesResolveConflict({
        path: { instance, source_id: sourceId, conflict_id: conflict.id },
        body: { resolution },
        throwOnError: true,
      }),
    onSuccess: () => {
      toast.success(`Resolved ${conflict.field_path}.`);
      refresh();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  return (
    <article
      aria-label={`Conflict on ${conflict.field_path}`}
      className="flex flex-col gap-2.5 rounded-card border border-danger/35 bg-danger/[0.04] p-3"
    >
      <p className="text-[12.5px]">
        <code className="font-mono">{conflict.path}</code>{" "}
        <code className="rounded-[4px] bg-surface-hover px-1 font-mono">{conflict.field_path}</code>
      </p>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-2">
        {(
          [
            ["Repo", conflict.repo],
            ["Studio", conflict.studio],
          ] as const
        ).map(([label, side]) => (
          <div
            key={label}
            className="flex flex-col gap-1 rounded-control border border-border-subtle bg-inset p-2.5"
          >
            <span className="font-mono text-[11px] text-fg-muted">
              {`${label} · ${side.reference ?? ""} · ${side.author ?? "unknown"}`}
            </span>
            <span className="font-mono text-[12.5px]">{conflictValue(side.value, side.present)}</span>
          </div>
        ))}
      </div>
      {canWrite && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="28" onClick={onMerge}>
            Merge in editor
          </Button>
          <Button
            variant="outline"
            size="28"
            disabled={resolve.isPending}
            onClick={() => {
              resolve.mutate("keep_studio");
            }}
          >
            Keep Studio
          </Button>
          <Button
            variant="outline"
            size="28"
            disabled={resolve.isPending}
            onClick={() => {
              resolve.mutate("keep_repo");
            }}
          >
            Keep repo
          </Button>
        </div>
      )}
    </article>
  );
}

function ChangesPanel({
  instance,
  source,
  canWrite,
}: {
  instance: string;
  source: CodeSourceOut;
  canWrite: boolean;
}) {
  const changes = useChanges(instance, source.id);
  const refresh = useRefresh();
  const [merging, setMerging] = useState<ConflictOut | undefined>(undefined);
  const fetchNow = useMutation({
    mutationFn: async () =>
      sourcesFetchSource({ path: { instance, source_id: source.id }, throwOnError: true }),
    onSuccess: () => {
      toast.success("Fetching; incoming changes show up here in a moment.");
      window.setTimeout(refresh, 1500);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const data = changes.data;
  return (
    <Card
      title="Changes"
      meta={
        data ? (
          <span className="font-mono text-[11.5px] text-fg-muted">
            {`Studio ⇄ ${data.remote.ref}`}
            {data.remote.head_sha ? ` @ ${sha7(data.remote.head_sha)}` : ""}
            {data.remote.fetched_at ? ` · fetched ${formatRelative(data.remote.fetched_at)}` : ""}
          </span>
        ) : undefined
      }
      action={
        canWrite ? (
          <Button
            variant="outline"
            size="28"
            disabled={fetchNow.isPending}
            onClick={() => {
              fetchNow.mutate();
            }}
          >
            <RefreshCw aria-hidden />
            Fetch
          </Button>
        ) : undefined
      }
    >
      {changes.isPending ? (
        <LoadingRows rows={4} label="Loading the changes" />
      ) : changes.isError || !data ? (
        <ErrorState {...describeError(changes.error)} onRetry={() => void changes.refetch()} />
      ) : (
        <div className="flex flex-col gap-5">
          {source.status !== "active" && (
            <Callout tone="info" title="Not syncing yet">
              Finish connecting the source: review the scan and bind its files (Connect source › Scan report).
            </Callout>
          )}
          <IncomingSection instance={instance} source={source} changes={data.incoming} canWrite={canWrite} />
          <OutgoingSection instance={instance} source={source} changes={data.outgoing} canWrite={canWrite} />
          {data.conflicts.length > 0 && (
            <section aria-label="Conflicts" className="flex flex-col gap-2">
              <header className="flex items-center gap-2">
                <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
                  <TriangleAlert aria-hidden className="size-3.5 text-danger" />
                  Conflict
                </h3>
                <span className="text-[12px] text-fg-muted">changed in both places</span>
              </header>
              {data.conflicts.map((conflict) => (
                <ConflictCard
                  key={conflict.id}
                  instance={instance}
                  sourceId={source.id}
                  conflict={conflict}
                  canWrite={canWrite}
                  onMerge={() => {
                    setMerging(conflict);
                  }}
                />
              ))}
            </section>
          )}
          {data.pull_requests.length > 0 && (
            <section aria-label="Pull requests" className="flex flex-col gap-1.5">
              <h3 className="text-[13px] font-semibold">Pull requests</h3>
              {data.pull_requests.map((pull) => (
                <a
                  key={pull.id}
                  href={pull.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex flex-wrap items-center gap-2 text-[12.5px] hover:text-fg"
                >
                  <ArrowUp aria-hidden className="size-3.5 text-fg-muted" />
                  <span className="font-mono">{`#${String(pull.number)} ${pull.branch}`}</span>
                  <Badge
                    tone={pull.status === "merged" ? "success" : pull.status === "open" ? "info" : "muted"}
                  >
                    {pull.status}
                  </Badge>
                  {pull.status === "open" && pull.review_requirement && (
                    <span className="text-fg-muted">{pull.review_requirement}</span>
                  )}
                </a>
              ))}
            </section>
          )}
        </div>
      )}
      {merging && (
        <MergeDialog
          instance={instance}
          sourceId={source.id}
          conflicts={[merging]}
          onOpenChange={(open) => {
            if (!open) setMerging(undefined);
          }}
          onResolved={refresh}
        />
      )}
    </Card>
  );
}

/** `/i/:instance/studio/sources?source=`: code sources, their changes, conflicts and pull requests. */
export function SourcesPage() {
  const params = useParams({ strict: false }) as unknown as Record<string, string | undefined>;
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const instance = params.instance ?? "";
  const sources = useSources(instance);
  const canConfigure = useCan("studio:sources:write", instance).allowed === true;
  const canDelete = useCan("studio:sources:delete", instance).allowed === true;
  const canWrite = useCan("components:write", instance).allowed === true;
  const [connecting, setConnecting] = useState(search.connect !== undefined);
  // Back from installing the GitHub App (`?connect=1&connection=scn_…`): the wizard picks up at the repository.
  const resumeConnection = typeof search.connection === "string" ? search.connection : undefined;
  const list = sources.data ?? [];
  const wanted = typeof search.source === "string" ? search.source : undefined;
  const selected = list.find((item) => item.id === wanted) ?? list[0];
  const select = (id: string) => {
    void navigate({ to: ".", search: { source: id }, replace: true });
  };

  let body;
  if (sources.isPending) {
    body = <LoadingRows rows={6} label="Loading the sources" />;
  } else if (sources.isError) {
    body = <ErrorState {...describeError(sources.error)} onRetry={() => void sources.refetch()} />;
  } else if (!selected) {
    body = (
      <EmptyState
        title="No code sources yet"
        action={
          canConfigure ? (
            <Button
              variant="primary"
              onClick={() => {
                setConnecting(true);
              }}
            >
              <Plus aria-hidden />
              Connect source
            </Button>
          ) : undefined
        }
      >
        Connect a GitHub, GitLab, Gitea or Forgejo repository (or a local folder on a development instance) to
        edit the same agents, teams and workflows in Studio and in code.
      </EmptyState>
    );
    if (canConfigure) {
      body = (
        <div className="flex flex-col gap-4">
          {body}
          <div className="max-w-[380px]">
            <ConnectionsCard canEdit={canConfigure} canDelete={canDelete} />
          </div>
        </div>
      );
    }
  } else {
    body = (
      <div className="grid gap-4 lg:grid-cols-[minmax(300px,380px)_1fr]">
        <div className="flex flex-col gap-4">
          <ul aria-label="Connected sources" className="flex flex-col gap-2">
            {list.map((source) => (
              <SourceCard
                key={source.id}
                source={source}
                selected={source.id === selected.id}
                onSelect={() => {
                  select(source.id);
                }}
              />
            ))}
          </ul>
          {canDelete && (
            <DisconnectSource
              instance={instance}
              source={selected}
              onDone={() => {
                void navigate({ to: ".", search: {}, replace: true });
              }}
            />
          )}
          <PathMappingCard instance={instance} source={selected} canEdit={canConfigure} />
          <SyncPolicyCard instance={instance} source={selected} canEdit={canConfigure} />
          {canConfigure && <ConnectionsCard canEdit={canConfigure} canDelete={canDelete} />}
        </div>
        <ChangesPanel instance={instance} source={selected} canWrite={canWrite} />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="flex flex-col gap-4 px-6 pt-5 pb-8">
        <PageIntro
          title="Code sources"
          actions={
            canConfigure ? (
              <Button
                variant="primary"
                size="32"
                onClick={() => {
                  setConnecting(true);
                }}
              >
                <Plus aria-hidden />
                Connect source
              </Button>
            ) : undefined
          }
        >
          Studio and your repositories edit the same agents, teams and workflows. Nothing moves until someone
          pulls or commits, and pulled changes always arrive as drafts.
        </PageIntro>
        {body}
      </div>
      {connecting && (
        <ConnectWizard
          instance={instance}
          resumeConnection={resumeConnection}
          onClose={(created) => {
            setConnecting(false);
            if (created) select(created);
            else if (search.connect !== undefined) void navigate({ to: ".", search: {}, replace: true });
          }}
        />
      )}
    </div>
  );
}
