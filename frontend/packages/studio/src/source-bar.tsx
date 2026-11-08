// Where a component is synced with a repository, in its editor: the source bar above the code (repo · branch, what
// came in, what Studio hasn't committed, Pull and Commit & PR…), the incoming-commit chip in the header, and the
// dialogs behind them. Nothing moves until someone pulls or commits.
import {
  describeError,
  sourcesCommitChanges,
  sourcesCommitPreview,
  sourcesComponentSourceOptions,
  sourcesPullChanges,
  sourcesRefreshOutgoing,
  sourcesResolveConflict,
  type ChangeOut,
  type ComponentSourceOut,
  type ConflictOut,
} from "@agnostic/api";
import { SuggestButton } from "@agnostic/assistant";
import { formatRelative, withQueryFn } from "@agnostic/core";
import { CodeView, type ChangeMark } from "@agnostic/editor";
import {
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  Input,
  LoadingRows,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, BookMarked, GitBranch, TriangleAlert, Upload } from "lucide-react";
import { useMemo, useState } from "react";

import { display } from "./config";

export function sha7(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : "";
}

/** The component's source binding (`bound: false` when no repository syncs it). */
export function useComponentSource(instance: string, componentId: string, enabled = true) {
  return useQuery({
    ...withQueryFn(sourcesComponentSourceOptions({ path: { instance, component_id: componentId } })),
    staleTime: 15_000,
    enabled,
  });
}

/** The lines the last pull brought in, for the code pane's gutter (only on the draft they were pulled into). */
export function incomingMarks(
  source: ComponentSourceOut | undefined,
  version: number | undefined,
): Record<number, ChangeMark> | undefined {
  if (!source?.bound || version === undefined || source.marks_version !== version) return undefined;
  const marks: Record<number, ChangeMark> = {};
  for (const line of Object.keys(source.incoming_marks ?? {})) marks[Number(line)] = "incoming";
  return marks;
}

function sourcesHref(instance: string, sourceId: string | null | undefined): string {
  const base = `/i/${encodeURIComponent(instance)}/studio/sources`;
  return sourceId ? `${base}?source=${encodeURIComponent(sourceId)}` : base;
}

/** After a pull, commit or resolution: the source views and the component (a pull adds a draft). */
export function useRefreshSources() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      predicate: (query) => {
        const [first] = query.queryKey;
        if (typeof first !== "object" || first === null || !("_id" in first)) return false;
        const id = String(first._id);
        return id.startsWith("sources") || id === "studioGetComponent" || id === "studioGetCodeDocument";
      },
    });
  };
}

/** "↓ 1 incoming commit on GitHub" in the editor header, linking to the source's changes. */
export function IncomingChip({ instance, componentId }: { instance: string; componentId: string }) {
  const source = useComponentSource(instance, componentId).data;
  const count = source?.bound ? (source.incoming ?? []).length : 0;
  if (!source || count === 0) return null;
  return (
    <Link
      to={sourcesHref(instance, source.source_id)}
      className="inline-flex h-7 items-center gap-1.5 rounded-full border border-info/35 px-3 font-mono text-[11.5px] text-info hover:text-info-hover"
    >
      <ArrowDown aria-hidden className="size-3.5" />
      {`${String(count)} incoming commit${count === 1 ? "" : "s"} on ${source.provider_label ?? "the repository"}`}
    </Link>
  );
}

/** The row above the code: repository, branch, file, what's incoming and uncommitted, Pull and Commit & PR…. */
export function SourceBar({
  instance,
  componentId,
  canWrite,
  onPulled,
}: {
  instance: string;
  componentId: string;
  canWrite: boolean;
  /** A pull created a new draft (the editor switches to it). */
  onPulled?: (version: number) => void;
}) {
  const query = useComponentSource(instance, componentId);
  const invalidate = useRefreshSources();
  const [dialog, setDialog] = useState<"commit" | "merge" | undefined>(undefined);
  const source = query.data;
  const pull = useMutation({
    mutationFn: async (changes: ChangeOut[]) =>
      (
        await sourcesPullChanges({
          path: { instance, source_id: source?.source_id ?? "" },
          body: { change_ids: changes.map((change) => change.id) },
          throwOnError: true,
        })
      ).data,
    onSuccess: (results) => {
      const failed = results.find((result) => result.error);
      if (failed?.error) toast.error(failed.error);
      const pulled = results.find((result) => typeof result.version === "number");
      if (pulled?.version) {
        toast.success(`Pulled as draft v${String(pulled.version)}.`);
        onPulled?.(pulled.version);
      }
      invalidate();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  if (!source?.bound) return null;
  const incomingChanges = source.incoming ?? [];
  const conflictList = source.conflicts ?? [];
  const others = source.other_sources ?? [];
  const incoming = incomingChanges[0];
  const conflicts = conflictList.length;
  return (
    <div
      aria-label={`Source: ${source.provider_label ?? ""} repository ${source.repo ?? ""}`}
      className="flex flex-wrap items-center gap-2 border-b border-border-subtle bg-canvas px-3 py-1.5 text-[12px]"
      role="group"
    >
      <Link
        to={sourcesHref(instance, source.source_id)}
        className="inline-flex items-center gap-1.5 text-fg-secondary hover:text-fg"
        aria-label={`Source: ${source.provider_label ?? ""} repository ${source.repo ?? ""}. Change source`}
      >
        <BookMarked aria-hidden className="size-3.5" />
        {source.provider_label}
        <span className="font-mono text-fg">{source.repo}</span>
      </Link>
      <span
        className="inline-flex h-6 items-center gap-1 rounded-control border border-border px-1.5 font-mono text-[11.5px] text-fg-secondary"
        aria-label={`Branch ${source.branch ?? ""}`}
      >
        <GitBranch aria-hidden className="size-3" />
        {source.branch}
      </span>
      <span className="font-mono text-[11.5px] text-fg-muted">{source.path}</span>
      {others.length > 0 && (
        <span className="text-[11.5px] text-fg-muted">{`also in ${others.join(", ")}`}</span>
      )}
      <span className="flex-1" />
      {incoming ? (
        <span className="font-mono text-[11.5px] text-info">
          {`↓ ${sha7(incoming.commit_sha)} · ${incoming.author_name ?? "someone"}`}
          {incoming.committed_at ? ` · ${formatRelative(incoming.committed_at)}` : ""}
        </span>
      ) : (
        <span
          className="font-mono text-[11.5px] text-fg-muted"
          title={source.fetched_at ? `Fetched ${formatRelative(source.fetched_at)}` : undefined}
        >
          {source.synced_sha ? `${sha7(source.synced_sha)} · no incoming` : "not synced yet"}
        </span>
      )}
      {source.uncommitted && (
        <span className="font-mono text-[11.5px] text-warning">{`↑ 1 uncommitted · ${source.uncommitted}`}</span>
      )}
      {source.pull_request && (
        <a
          href={source.pull_request.url}
          target="_blank"
          rel="noreferrer"
          className="font-mono text-[11.5px] text-info hover:text-info-hover"
        >
          {`PR #${String(source.pull_request.number)}`}
        </a>
      )}
      {conflicts > 0 && (
        <Button
          variant="destructive-text"
          size="28"
          onClick={() => {
            setDialog("merge");
          }}
        >
          <TriangleAlert aria-hidden />
          {`${String(conflicts)} conflict${conflicts === 1 ? "" : "s"} · Merge…`}
        </Button>
      )}
      {canWrite && incoming && (
        <Button
          variant={conflicts > 0 ? "outline" : "primary"}
          size="28"
          disabled={pull.isPending || conflicts > 0}
          onClick={() => {
            pull.mutate(incomingChanges);
          }}
        >
          <ArrowDown aria-hidden />
          {source.uncommitted ? "Pull & review" : "Pull"}
        </Button>
      )}
      {canWrite && (
        <Button
          variant="outline"
          size="28"
          onClick={() => {
            setDialog("commit");
          }}
        >
          <ArrowUp aria-hidden />
          Commit & PR…
        </Button>
      )}
      {dialog === "commit" && source.source_id && (
        <CommitDialog
          instance={instance}
          sourceId={source.source_id}
          componentId={componentId}
          onOpenChange={(open) => {
            if (!open) setDialog(undefined);
          }}
          onCommitted={invalidate}
        />
      )}
      {dialog === "merge" && source.source_id && (
        <MergeDialog
          instance={instance}
          sourceId={source.source_id}
          conflicts={conflictList}
          onOpenChange={(open) => {
            if (!open) setDialog(undefined);
          }}
          onResolved={invalidate}
        />
      )}
    </div>
  );
}

/** The commit composer: message, branch and review requirement, then Commit & open PR. */
export function CommitComposer({
  instance,
  sourceId,
  changes,
  onCommitted,
}: {
  instance: string;
  sourceId: string;
  changes: readonly ChangeOut[];
  onCommitted: () => void;
}) {
  const ids = changes.filter((change) => change.included).map((change) => change.id);
  const preview = useQuery({
    queryKey: ["sourcesCommitPreview", instance, sourceId, ids],
    queryFn: async () =>
      (
        await sourcesCommitPreview({
          path: { instance, source_id: sourceId },
          query: { change_ids: ids },
          throwOnError: true,
        })
      ).data,
    enabled: ids.length > 0,
    retry: false,
  });
  const [message, setMessage] = useState<string | undefined>(undefined);
  const commit = useMutation({
    mutationFn: async () =>
      (
        await sourcesCommitChanges({
          path: { instance, source_id: sourceId },
          body: { change_ids: ids, message: message ?? preview.data?.message ?? null },
          throwOnError: true,
        })
      ).data,
    onSuccess: () => {
      toast.success(
        preview.data?.mode === "open_pr"
          ? "Committing and opening the pull request…"
          : "Committing the change…",
      );
      setMessage(undefined);
      onCommitted();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  if (ids.length === 0)
    return <p className="text-[12.5px] text-fg-muted">Pick at least one change to commit.</p>;
  if (preview.isError) return <Callout tone="warning">{describeError(preview.error).reason}</Callout>;
  const label = preview.data?.mode === "open_pr" ? "Commit & open PR" : "Commit";
  return (
    <div className="flex flex-col gap-2">
      <Field label="Commit message">
        {({ id }) => (
          <Input
            id={id}
            mono
            value={message ?? preview.data?.message ?? ""}
            onChange={(event) => {
              setMessage(event.target.value);
            }}
          />
        )}
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11.5px] text-fg-muted">
          {preview.data?.sentence ?? "Working out the branch…"}
        </span>
        <span className="flex-1" />
        <SuggestButton
          instance={instance}
          label="Suggest message"
          request={{
            kind: "studio.commit_message",
            subject: { source_id: sourceId },
            material: changes
              .filter((change) => change.included)
              .map((change) => ({
                path: change.path,
                component: change.component_id,
                summary: change.summary,
                additions: change.additions,
                deletions: change.deletions,
              })),
          }}
          onUse={setMessage}
        />
        <Button
          variant="secondary"
          size="30"
          disabled={!preview.data || commit.isPending}
          onClick={() => {
            commit.mutate();
          }}
        >
          <Upload aria-hidden />
          {label}
        </Button>
      </div>
    </div>
  );
}

function CommitDialog({
  instance,
  sourceId,
  componentId,
  onOpenChange,
  onCommitted,
}: {
  instance: string;
  sourceId: string;
  componentId: string;
  onOpenChange: (open: boolean) => void;
  onCommitted: () => void;
}) {
  const outgoing = useQuery({
    queryKey: ["sourcesRefreshOutgoing", instance, sourceId],
    queryFn: async () =>
      (await sourcesRefreshOutgoing({ path: { instance, source_id: sourceId }, throwOnError: true })).data,
    staleTime: 0,
  });
  const mine = (outgoing.data ?? []).filter((change) => change.component_id === componentId);
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Commit & PR</DialogTitle>
          <DialogDescription>
            What Studio has that the repository doesn't, written into the bound file.
          </DialogDescription>
        </DialogHeader>
        {outgoing.isPending ? (
          <LoadingRows rows={2} label="Working out the changes" />
        ) : outgoing.isError ? (
          <Callout tone="danger">{describeError(outgoing.error).reason}</Callout>
        ) : mine.length === 0 ? (
          <p className="text-[12.5px] text-fg-secondary">The repository already says what Studio has.</p>
        ) : (
          <div className="flex flex-col gap-3">
            {mine.map((change) => (
              <div
                key={change.id}
                className="rounded-card border border-border bg-canvas px-3 py-2 text-[12.5px]"
              >
                <span className="font-mono">{change.path}</span>{" "}
                <span className="font-mono text-accent">{`+${String(change.additions)}`}</span>{" "}
                <span className="font-mono text-danger">{`−${String(change.deletions)}`}</span>
                <p className="text-fg-secondary">{`Draft v${String(change.draft_version ?? "")} · ${change.summary ?? ""}`}</p>
                {change.outcome.action === "blocked" && (
                  <p className="text-warning">
                    The file changed in the repository too; pull the incoming change first.
                  </p>
                )}
              </div>
            ))}
            <CommitComposer
              instance={instance}
              sourceId={sourceId}
              changes={mine.filter((change) => change.outcome.action !== "blocked")}
              onCommitted={() => {
                onCommitted();
                onOpenChange(false);
              }}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function text(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

/** Lines of `after` that differ from `before` (a plain line diff, for the merge view's gutters). */
function differing(before: string, after: string): Record<number, ChangeMark> {
  const left = before.split("\n");
  const marks: Record<number, ChangeMark> = {};
  after.split("\n").forEach((line, index) => {
    if (left[index] !== line) marks[index + 1] = left.includes(line) ? "modified" : "added";
  });
  return marks;
}

/** Merge in editor: both sides with who wrote them, and an editable result; or keep one side as it is. */
export function MergeDialog({
  instance,
  sourceId,
  conflicts,
  onOpenChange,
  onResolved,
}: {
  instance: string;
  sourceId: string;
  conflicts: readonly ConflictOut[];
  onOpenChange: (open: boolean) => void;
  onResolved: () => void;
}) {
  const [index, setIndex] = useState(0);
  const conflict = conflicts[Math.min(index, conflicts.length - 1)];
  const [draft, setDraft] = useState<string | undefined>(undefined);
  const resolve = useMutation({
    mutationFn: async (body: { resolution: "keep_studio" | "keep_repo" | "merged"; value?: unknown }) =>
      (
        await sourcesResolveConflict({
          path: { instance, source_id: sourceId, conflict_id: conflict?.id ?? "" },
          body,
          throwOnError: true,
        })
      ).data,
    onSuccess: () => {
      toast.success(`Resolved ${conflict?.field_path ?? "the conflict"}.`);
      setDraft(undefined);
      onResolved();
      if (conflicts.length <= 1) onOpenChange(false);
      else setIndex((current) => current % (conflicts.length - 1));
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const repo = conflict ? text(conflict.repo.value) : "";
  const studio = conflict ? text(conflict.studio.value) : "";
  const result = draft ?? studio;
  const marks = useMemo(
    () => ({ repo: differing(studio, repo), studio: differing(repo, studio) }),
    [repo, studio],
  );
  if (!conflict) return null;
  const parsed = (): unknown => {
    if (typeof conflict.studio.value === "string" || typeof conflict.repo.value === "string") return result;
    return JSON.parse(result) as unknown;
  };
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>{`Merge ${conflict.field_path}`}</DialogTitle>
          <DialogDescription>
            {`${conflict.path} · changed in both places`}
            {conflicts.length > 1 ? ` · ${String(index + 1)} of ${String(conflicts.length)}` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 md:grid-cols-2">
          <section aria-label="Repository side" className="flex min-w-0 flex-col gap-1">
            <h3 className="font-mono text-[11.5px] text-fg-muted">
              {`Repo · ${conflict.repo.reference ?? ""} · ${conflict.repo.author ?? ""}`}
            </h3>
            {conflict.repo.present ? (
              <CodeView value={repo} language="json" marks={marks.repo} ariaLabel="Repository value" />
            ) : (
              <p className="text-[12.5px] text-fg-secondary">Removed in the repository.</p>
            )}
          </section>
          <section aria-label="Studio side" className="flex min-w-0 flex-col gap-1">
            <h3 className="font-mono text-[11.5px] text-fg-muted">
              {`Studio · ${conflict.studio.reference ?? ""} · ${conflict.studio.author ?? ""}`}
            </h3>
            {conflict.studio.present ? (
              <CodeView value={studio} language="json" marks={marks.studio} ariaLabel="Studio value" />
            ) : (
              <p className="text-[12.5px] text-fg-secondary">Removed in Studio.</p>
            )}
          </section>
        </div>
        <Field label="Merged value">
          {({ id }) => (
            <Textarea
              id={id}
              className="min-h-24 font-mono text-[12.5px]"
              value={result}
              onChange={(event) => {
                setDraft(event.target.value);
              }}
            />
          )}
        </Field>
        <DialogFooter>
          <Button
            variant="outline"
            disabled={resolve.isPending}
            onClick={() => {
              resolve.mutate({ resolution: "keep_studio" });
            }}
          >
            Keep Studio
          </Button>
          <Button
            variant="outline"
            disabled={resolve.isPending}
            onClick={() => {
              resolve.mutate({ resolution: "keep_repo" });
            }}
          >
            Keep repo
          </Button>
          <Button
            variant="primary"
            disabled={resolve.isPending || draft === undefined}
            onClick={() => {
              try {
                resolve.mutate({ resolution: "merged", value: parsed() });
              } catch {
                toast.error("The merged value isn't valid JSON.");
              }
            }}
          >
            Use merged value
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** The value of one side of a conflict, short enough for a card. */
export function conflictValue(value: unknown, present: boolean): string {
  return present ? display(value) : "(removed)";
}
