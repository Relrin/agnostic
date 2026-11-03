// Dialogs around a draft: the diff against the base version, a save conflict, the versions drawer (view, restore as
// draft, set current), publish (validation, eval gates, override) and promotion to another instance.
import {
  describeError,
  studioApplyPromotion,
  studioDiffVersionsOptions,
  studioGetComponentQueryKey,
  studioGetVersionOptions,
  studioNewDraft,
  studioPromote,
  studioPublish,
  studioPublishCheck,
  studioPublishCheckOptions,
  studioSetCurrent,
  type ComponentDetailOut,
  type PromotionOut,
  type PublishCheckOut,
  type VersionOut,
} from "@agnostic/api";
import { formatWhen, useCan, useInstances, withQueryFn } from "@agnostic/core";
import { CodeView } from "@agnostic/editor";
import {
  Badge,
  Button,
  Callout,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  GateResultList,
  LoadingRows,
  ScopeDiff,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  StepList,
  Textarea,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { display, type Config } from "./config";

// ---------------------------------------------------------------- diff

export function DiffDialog({
  open,
  onOpenChange,
  instance,
  componentId,
  from,
  to,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: string;
  componentId: string;
  from: number;
  to: number;
}) {
  const options = studioDiffVersionsOptions({
    path: { instance, component_id: componentId },
    query: { from, to },
  });
  const diff = useQuery({ ...withQueryFn(options), enabled: open });
  const ops = { added: "add", removed: "remove", changed: "change" } as const;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{`v${String(to)} against v${String(from)}`}</DialogTitle>
          <DialogDescription>{diff.data?.summary ?? "Comparing the saved versions…"}</DialogDescription>
        </DialogHeader>
        {diff.isPending ? (
          <LoadingRows rows={4} label="Loading the diff" />
        ) : diff.data ? (
          <div className="flex max-h-[60vh] flex-col gap-4 overflow-auto">
            <ScopeDiff
              lines={diff.data.changes.map((change) => ({
                op: ops[change.op],
                text:
                  change.op === "changed"
                    ? `${change.path}: ${display(change.before)} → ${display(change.after)}`
                    : `${change.path}: ${display(change.op === "added" ? change.after : change.before)}`,
              }))}
            />
            <div className="overflow-hidden rounded-card border border-border">
              <div className="border-b border-border-subtle px-3 py-1.5 font-mono text-[11.5px] text-fg-muted">
                {`+${String(diff.data.lines_added)} −${String(diff.data.lines_removed)} lines`}
              </div>
              <CodeView
                value={diff.data.unified || "No differences."}
                language="python"
                ariaLabel="Code diff"
              />
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- conflict

export function ConflictDialog({
  open,
  savedBy,
  savedAt,
  onKeep,
}: {
  open: boolean;
  savedBy: string | undefined;
  savedAt: string | undefined;
  onKeep: (keep: "mine" | "theirs") => void;
}) {
  return (
    <Dialog open={open}>
      <DialogContent showClose={false}>
        <DialogHeader>
          <DialogTitle>Someone else saved this draft</DialogTitle>
          <DialogDescription>
            {`${savedBy ?? "Someone"} saved it${savedAt ? ` ${formatWhen(savedAt)}` : ""}, after you opened it. `}
            Keep their version to continue from it, or save yours over it.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="secondary"
            onClick={() => {
              onKeep("theirs");
            }}
          >
            Load their version
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              onKeep("mine");
            }}
          >
            Save mine over it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- versions

function VersionView({
  instance,
  componentId,
  version,
  onClose,
}: {
  instance: string;
  componentId: string;
  version: number;
  onClose: () => void;
}) {
  const options = studioGetVersionOptions({ path: { instance, component_id: componentId, version } });
  const loaded = useQuery(withQueryFn(options));
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{loaded.data?.tag ?? `v${String(version)}`}</DialogTitle>
          <DialogDescription>
            {loaded.data?.change_summary ?? loaded.data?.notes ?? "The stored config."}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-auto rounded-card border border-border">
          <CodeView
            value={JSON.stringify(loaded.data?.config ?? {}, null, 2)}
            language="json"
            ariaLabel="Version config"
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}

function evalStatus(version: VersionOut): string | undefined {
  switch (version.eval_status) {
    case "passed":
      return "gates passed";
    case "overridden":
      return "gate overridden";
    case "no_gates":
      return "no gates";
    default:
      return undefined;
  }
}

export function VersionsDrawer({
  open,
  onOpenChange,
  instance,
  instanceName,
  detail,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: string;
  instanceName: string;
  detail: ComponentDetailOut;
}) {
  const queryClient = useQueryClient();
  const canWrite = useCan("components:write", instance);
  const componentId = detail.component.id;
  const [viewing, setViewing] = useState<number | undefined>(undefined);
  const [rollback, setRollback] = useState<VersionOut | undefined>(undefined);
  const [reason, setReason] = useState("");
  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: studioGetComponentQueryKey({ path: { instance, component_id: componentId } }),
    });
  };
  const restore = useMutation({
    mutationFn: async (version: number) =>
      (
        await studioNewDraft({
          path: { instance, component_id: componentId },
          body: { from_version: version },
          throwOnError: true,
        })
      ).data,
    onSuccess: (created) => {
      toast.success(
        `Draft v${String(created.version)} starts from v${String(created.based_on_version ?? "")}.`,
      );
      refresh();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const setCurrent = useMutation({
    mutationFn: async (version: number) =>
      (
        await studioSetCurrent({
          path: { instance, component_id: componentId, version },
          body: { reason: reason.trim() || null },
          throwOnError: true,
        })
      ).data,
    onSuccess: (result) => {
      toast.success(result.outcome);
      setRollback(undefined);
      setReason("");
      refresh();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const hasDraft = detail.draft !== null;
  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
        <SheetContent side="right" className="flex flex-col gap-3 overflow-auto">
          <SheetTitle>Versions</SheetTitle>
          <SheetDescription>{`${detail.component.name} on ${instanceName}`}</SheetDescription>
          <ol className="flex flex-col gap-2">
            {detail.versions.map((version) => (
              <li
                key={version.version}
                className="flex flex-col gap-1 rounded-card border border-border bg-surface p-3"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[13px] font-medium">{version.tag}</span>
                  {version.current && <Badge tone="success">current</Badge>}
                  {version.stage === "draft" && <Badge tone="warning">draft</Badge>}
                  {version.label && <Badge tone="outline">{version.label}</Badge>}
                  <span className="flex-1" />
                  {evalStatus(version) && (
                    <span
                      className={cn(
                        "text-[11.5px]",
                        version.eval_status === "overridden" ? "text-warning" : "text-fg-muted",
                      )}
                    >
                      {evalStatus(version)}
                    </span>
                  )}
                </div>
                {(version.change_summary ?? version.notes) && (
                  <p className="text-[12.5px] text-fg-secondary">{version.notes ?? version.change_summary}</p>
                )}
                <p className="text-[11.5px] text-fg-muted">
                  {version.published_at
                    ? `Published by ${version.published_by_name ?? "someone"} · ${formatWhen(version.published_at)}`
                    : `${version.author_name ? `By ${version.author_name} · ` : ""}${formatWhen(version.saved_at ?? version.updated_at ?? version.created_at)}`}
                  {version.promoted_from &&
                    ` · promoted from ${typeof version.promoted_from.instance === "string" ? version.promoted_from.instance : "another instance"}`}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  <Button
                    variant="ghost"
                    size="28"
                    onClick={() => {
                      setViewing(version.version);
                    }}
                  >
                    View
                  </Button>
                  {version.stage === "published" && canWrite.allowed && !hasDraft && (
                    <Button
                      variant="ghost"
                      size="28"
                      disabled={restore.isPending}
                      onClick={() => {
                        restore.mutate(version.version);
                      }}
                    >
                      Restore as draft
                    </Button>
                  )}
                  {version.stage === "published" && !version.current && canWrite.allowed && (
                    <Button
                      variant="ghost"
                      size="28"
                      onClick={() => {
                        setRollback(version);
                      }}
                    >
                      Set current
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ol>
          {hasDraft && (
            <p className="text-[11.5px] text-fg-muted">
              Publish or discard the open draft to restore another version as a draft.
            </p>
          )}
        </SheetContent>
      </Sheet>
      {viewing !== undefined && (
        <VersionView
          instance={instance}
          componentId={componentId}
          version={viewing}
          onClose={() => {
            setViewing(undefined);
          }}
        />
      )}
      <Dialog
        open={rollback !== undefined}
        onOpenChange={(next) => {
          if (!next) setRollback(undefined);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{`Make ${rollback?.tag ?? ""} current?`}</DialogTitle>
            <DialogDescription>
              {`v${String(rollback?.version ?? "")} becomes current on ${instanceName} instead of v${String(detail.component.current_version ?? "")}; the API serves it from the next request. This is recorded in the audit log.`}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            aria-label="Reason"
            placeholder="Why roll back? (optional)"
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
          <DialogFooter>
            <Button
              variant="primary"
              disabled={setCurrent.isPending}
              onClick={() => {
                if (rollback) setCurrent.mutate(rollback.version);
              }}
            >
              {`Make v${String(rollback?.version ?? "")} current`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ---------------------------------------------------------------- publish

function steps(check: PublishCheckOut) {
  return check.validation.layers.map((layer) => {
    const first = layer.diagnostics.find((item) => item.severity === "error") ?? layer.diagnostics[0];
    return {
      id: layer.id,
      label: layer.label,
      status: layer.status,
      detail: first
        ? `${first.path ? `${first.path}: ` : ""}${first.message}`
        : layer.status === "ok"
          ? "OK"
          : "",
      hint: layer.hint ?? null,
    };
  });
}

export function PublishDialog({
  open,
  onOpenChange,
  instance,
  componentId,
  version,
  evalsHref,
  beforeCheck,
  onPublished,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: string;
  componentId: string;
  version: number;
  /** Where "Run evals" goes (the evaluations page, preset for this version). */
  evalsHref: string;
  /** Save pending edits before the check runs. */
  beforeCheck: () => Promise<boolean>;
  onPublished: () => void;
}) {
  const queryClient = useQueryClient();
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const options = studioPublishCheckOptions({
    path: { instance, component_id: componentId },
    query: { version },
  });
  const check = useQuery({
    queryKey: options.queryKey,
    queryFn: async () => {
      await beforeCheck();
      return (
        await studioPublishCheck({
          path: { instance, component_id: componentId },
          query: { version },
          throwOnError: true,
        })
      ).data;
    },
    enabled: open,
    staleTime: 0,
  });
  const publish = useMutation({
    mutationFn: async () =>
      (
        await studioPublish({
          path: { instance, component_id: componentId, version },
          body: { notes: notes.trim() || null, override_reason: reason.trim() || null },
          throwOnError: true,
        })
      ).data,
    onSuccess: (result) => {
      toast.success(result.overridden ? `${result.outcome} Published with a gate override.` : result.outcome);
      void queryClient.invalidateQueries({
        queryKey: studioGetComponentQueryKey({ path: { instance, component_id: componentId } }),
      });
      setNotes("");
      setReason("");
      onOpenChange(false);
      onPublished();
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const data = check.data;
  const blocked = data?.blocked_by_gates ?? false;
  const invalid = data ? !data.validation.ok : false;
  const needsReason = blocked && reason.trim().length === 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{`Publish v${String(version)}`}</DialogTitle>
          <DialogDescription>{data?.summary ?? "Checking the draft…"}</DialogDescription>
        </DialogHeader>
        {check.isPending ? (
          <LoadingRows rows={4} label="Checking the draft" />
        ) : check.isError ? (
          <Callout tone="danger">{describeError(check.error).reason}</Callout>
        ) : data ? (
          <div className="flex flex-col gap-4">
            <section aria-label="Validation" className="flex flex-col gap-2">
              <h3 className="text-[12.5px] font-medium text-fg-secondary">{`Validation · ${data.validation.summary}`}</h3>
              <StepList steps={steps(data)} />
            </section>
            <section aria-label="Eval gates" className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <h3 className="text-[12.5px] font-medium text-fg-secondary">Eval gates</h3>
                <span className="flex-1" />
                <Button asChild variant="link" size="28">
                  <Link to={evalsHref}>Run evals</Link>
                </Button>
              </div>
              <GateResultList
                rows={data.gates.map((gate) => ({
                  id: gate.gate_id,
                  dataset: gate.dataset_name ?? gate.dataset_id,
                  evalType: gate.eval_type,
                  minAverage: gate.min_average,
                  value: gate.value ?? undefined,
                  state: gate.state,
                  consequence: gate.consequence,
                }))}
              />
            </section>
            {blocked &&
              (data.can_override ? (
                <Callout tone="warning" title="Publishing past a failed gate">
                  <p className="mb-2">The override and your reason are recorded in the audit log.</p>
                  <Textarea
                    aria-label="Override reason"
                    placeholder="Why publish anyway?"
                    value={reason}
                    onChange={(event) => {
                      setReason(event.target.value);
                    }}
                  />
                </Callout>
              ) : (
                <Callout tone="danger">
                  An eval gate blocks this version. Owners and Administrators (evals:gates:override) can
                  publish it with a reason.
                </Callout>
              ))}
            <Textarea
              aria-label="Release notes"
              placeholder="Release notes (optional)"
              value={notes}
              onChange={(event) => {
                setNotes(event.target.value);
              }}
            />
            <p className="text-[12.5px] text-fg-secondary">{data.outcome}</p>
          </div>
        ) : null}
        <DialogFooter>
          <Button
            variant="primary"
            disabled={
              !data ||
              !data.can_publish ||
              invalid ||
              needsReason ||
              publish.isPending ||
              (blocked && !data.can_override)
            }
            onClick={() => {
              publish.mutate();
            }}
          >
            {blocked ? `Override and publish v${String(version)}` : `Publish v${String(version)}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- promote

export function PromoteDialog({
  open,
  onOpenChange,
  instance,
  componentId,
  version,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: string;
  componentId: string;
  version: number;
}) {
  const instances = useInstances();
  const others = (instances.data ?? []).filter((item) => item.slug !== instance && item.id !== instance);
  const [target, setTarget] = useState<string | undefined>(undefined);
  const [children, setChildren] = useState(true);
  const [promotion, setPromotion] = useState<PromotionOut | undefined>(undefined);
  const chosen = target ?? others[0]?.slug;
  const name = others.find((item) => item.slug === chosen)?.display_name ?? chosen ?? "";
  const dryRun = useMutation({
    mutationFn: async () =>
      (
        await studioPromote({
          path: { instance, component_id: componentId },
          body: { target: chosen ?? "", version, include_children: children },
          throwOnError: true,
        })
      ).data,
    onSuccess: setPromotion,
    onError: (error) => toast.error(describeError(error).reason),
  });
  const apply = useMutation({
    mutationFn: async (publish: boolean) =>
      (
        await studioApplyPromotion({
          path: { instance, promotion_id: promotion?.id ?? "" },
          body: { publish },
          throwOnError: true,
        })
      ).data,
    onSuccess: (result) => {
      toast.success(
        result.status === "published"
          ? `${componentId} v${String(result.to_version ?? "")} is current on ${name}.`
          : `Draft v${String(result.to_version ?? "")} of ${componentId} is ready on ${name}.`,
      );
      setPromotion(undefined);
      onOpenChange(false);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const report = promotion?.report as
    | {
        ok?: boolean;
        summary?: string;
        missing?: { type: string; name: string; paths: string[] }[];
        children?: { component_id: string; status: string; version: number | null }[];
      }
    | undefined;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setPromotion(undefined);
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{`Promote v${String(version)}`}</DialogTitle>
          <DialogDescription>
            A dry run checks that every registry reference and pinned member exists on the target. Nothing
            changes until you apply it.
          </DialogDescription>
        </DialogHeader>
        {others.length === 0 ? (
          <Callout tone="info">Connect another instance to promote to it.</Callout>
        ) : (
          <div className="flex flex-col gap-3">
            <Select
              value={chosen ?? ""}
              onValueChange={(next) => {
                setTarget(next);
                setPromotion(undefined);
              }}
            >
              <SelectTrigger aria-label="Target instance" className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {others.map((item) => (
                  <SelectItem key={item.id} value={item.slug}>
                    {item.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Checkbox
              checked={children}
              onCheckedChange={(checked) => {
                setChildren(checked === true);
                setPromotion(undefined);
              }}
              label="Promote pinned members that the target doesn't have"
            />
            {report && (
              <Callout
                tone={report.ok ? "insight" : "danger"}
                title={report.ok ? "Ready to promote" : "Can't promote yet"}
              >
                <p>{report.summary}</p>
                {report.missing && report.missing.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 font-mono text-[12px]">
                    {report.missing.map((item) => (
                      <li
                        key={`${item.type}:${item.name}`}
                      >{`${item.type} ${item.name} · ${item.paths.join(", ")}`}</li>
                    ))}
                  </ul>
                )}
              </Callout>
            )}
          </div>
        )}
        <DialogFooter>
          {!promotion || !report?.ok ? (
            <Button
              variant="primary"
              disabled={!chosen || dryRun.isPending}
              onClick={() => {
                dryRun.mutate();
              }}
            >
              Check the target
            </Button>
          ) : (
            <>
              <Button
                variant="secondary"
                disabled={apply.isPending}
                onClick={() => {
                  apply.mutate(false);
                }}
              >
                {`Create a draft on ${name}`}
              </Button>
              <Button
                variant="primary"
                disabled={apply.isPending}
                onClick={() => {
                  apply.mutate(true);
                }}
              >
                {`Publish on ${name}`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export type { Config };
