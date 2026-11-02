import { contextDeleteUserLearnings, describeError } from "@agnostic/api";
import { PermissionGate, formatRelative, useCan } from "@agnostic/core";
import {
  Badge,
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type ReactNode } from "react";

import { LEARNING_TYPES, humanize, useLearningActions, type Learning } from "./learnings-api";

type View = "readable" | "raw";
const ALL = "all";

function text(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseObject(label: string, value: string): Record<string, unknown> {
  const parsed = JSON.parse(value) as unknown;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
    throw new Error(`${label} must be a JSON object.`);
  return parsed as Record<string, unknown>;
}

function lines(value: unknown): string[] {
  if (Array.isArray(value))
    return value.map((item) => (typeof item === "string" ? item : JSON.stringify(item)));
  if (value !== null && typeof value === "object") return [JSON.stringify(value)];
  return [String(value)];
}

/** Record detail: facts, Readable / Raw JSON, save (replaces content and metadata), delete, per-user deletion. */
export function LearningDetail({
  instance,
  record,
  idScheme,
  onDeleted,
}: {
  instance: string;
  record: Learning;
  idScheme: string | undefined;
  onDeleted: () => void;
}) {
  const actions = useLearningActions(instance);
  const canWrite = useCan("learnings:write", instance).allowed === true;
  const [view, setView] = useState<View>("readable");
  const ids = useId();
  const [content, setContent] = useState(text(record.content));
  const [metadata, setMetadata] = useState(text(record.metadata));
  const [error, setError] = useState<string | undefined>(undefined);
  const dirty = content !== text(record.content) || metadata !== text(record.metadata);

  const facts: { label: string; value: ReactNode }[] = [
    { label: "learning_type", value: record.learning_type },
    { label: "user_id", value: record.user_id ?? "null" },
    { label: "agent_id", value: record.agent_id ?? record.team_id ?? "—" },
    ...(record.learning_type === "session_context"
      ? [{ label: "session_id", value: record.session_id ?? "—" }]
      : []),
    ...(record.namespace ? [{ label: "namespace", value: record.namespace }] : []),
    ...(record.learning_type === "entity_memory"
      ? [{ label: "entity", value: `${record.entity_type ?? "—"} / ${record.entity_id ?? "—"}` }]
      : []),
    { label: "updated_at", value: formatRelative(record.updated_at) },
  ];

  const save = () => {
    try {
      const body = {
        id: record.learning_id,
        content: parseObject("content", content),
        metadata: parseObject("metadata", metadata),
      };
      setError(undefined);
      actions.save.mutate(body, {
        onSuccess: () => toast.success("Record saved"),
        onError: (problem) => toast.error(describeError(problem).reason),
      });
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Not valid JSON.");
    }
  };

  return (
    <div className="flex min-w-0 flex-[3_1_480px] flex-col gap-4">
      <section
        aria-label="Record"
        className="flex flex-col gap-4 rounded-card border border-border bg-surface p-4"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-1.5">
            <h2 className="font-mono text-[15px] font-semibold break-all">{record.learning_id}</h2>
            <span className="flex flex-wrap items-center gap-2">
              <Badge className="bg-[rgba(183,156,255,0.14)] text-[#CDBBFF] normal-case">
                {record.learning_type}
              </Badge>
              {idScheme && <span className="text-[12px] text-fg-muted">{idScheme}</span>}
            </span>
          </div>
          <SegmentedControl
            label="View"
            value={view}
            onValueChange={setView}
            options={[
              { value: "readable", label: "Readable" },
              { value: "raw", label: "Raw JSON" },
            ]}
          />
        </div>
        <dl className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
          {facts.map((fact) => (
            <div key={fact.label} className="flex min-w-0 flex-col gap-0.5">
              <dt className="font-mono text-[11px] text-fg-muted">{fact.label}</dt>
              <dd className="truncate font-mono text-[12.5px]">{fact.value}</dd>
            </div>
          ))}
        </dl>

        {view === "readable" ? (
          <div className="flex flex-col rounded-tile border border-border">
            <div className="border-b border-border-subtle px-3 py-1.5 font-mono text-[11px] text-fg-muted">
              content
            </div>
            <dl className="flex flex-col divide-y divide-border-subtle">
              {Object.entries(record.content ?? {}).map(([key, value]) => (
                <div
                  key={key}
                  className="grid grid-cols-[minmax(120px,180px)_1fr] gap-3 px-3 py-2 text-[13px]"
                >
                  <dt className="text-fg-muted">{humanize(key)}</dt>
                  <dd className="flex flex-col gap-0.5">
                    {lines(value).map((line, index) => (
                      <span key={index}>{line}</span>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
            <div className="flex flex-wrap items-center gap-1.5 border-t border-border-subtle px-3 py-2 text-[12px] text-fg-muted">
              metadata:
              {Object.entries(record.metadata ?? {}).length === 0
                ? " none"
                : Object.entries(record.metadata ?? {}).map(([key, value]) => (
                    <span
                      key={key}
                      className="rounded-badge border border-border px-1.5 py-0.5 font-mono text-[11px]"
                    >
                      {key}: {typeof value === "string" ? value : JSON.stringify(value)}
                    </span>
                  ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <label
              htmlFor={`${ids}-content`}
              className="flex flex-col gap-1 font-mono text-[11px] text-fg-muted"
            >
              content
              <Textarea
                id={`${ids}-content`}
                rows={8}
                readOnly={!canWrite}
                value={content}
                onChange={(event) => {
                  setContent(event.target.value);
                }}
              />
            </label>
            <label
              htmlFor={`${ids}-metadata`}
              className="flex flex-col gap-1 font-mono text-[11px] text-fg-muted"
            >
              metadata
              <Textarea
                id={`${ids}-metadata`}
                rows={4}
                readOnly={!canWrite}
                value={metadata}
                onChange={(event) => {
                  setMetadata(event.target.value);
                }}
              />
            </label>
            {error && (
              <p role="alert" className="text-[12.5px] text-danger">
                {error}
              </p>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border-subtle pt-3">
          <span className="text-[12px] text-fg-muted">
            Saving replaces <code className="font-mono">content</code> and{" "}
            <code className="font-mono">metadata</code> ·{" "}
            <code className="font-mono">PATCH /learnings/{"{learning_id}"}</code>
          </span>
          <div className="flex gap-2">
            <PermissionGate scope="learnings:delete" instance={instance}>
              <DeleteRecord record={record} actions={actions} onDeleted={onDeleted} />
            </PermissionGate>
            {canWrite && (
              <>
                <Button
                  variant="outline"
                  size="30"
                  disabled={!dirty}
                  onClick={() => {
                    setContent(text(record.content));
                    setMetadata(text(record.metadata));
                    setError(undefined);
                  }}
                >
                  Discard
                </Button>
                <Button
                  variant="primary"
                  size="30"
                  disabled={!dirty || actions.save.isPending}
                  onClick={save}
                >
                  {actions.save.isPending ? "Saving…" : "Save"}
                </Button>
              </>
            )}
          </div>
        </div>
      </section>

      {record.user_id && (
        <PermissionGate scope="learnings:delete" instance={instance}>
          <DeleteUserLearnings instance={instance} user={record.user_id} onDeleted={actions.refresh} />
        </PermissionGate>
      )}
    </div>
  );
}

function DeleteRecord({
  record,
  actions,
  onDeleted,
}: {
  record: Learning;
  actions: ReturnType<typeof useLearningActions>;
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
        Delete record
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {record.learning_id}?</DialogTitle>
          <DialogDescription>Agents stop loading this record. This can&apos;t be undone.</DialogDescription>
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
                { id: record.learning_id },
                {
                  onSuccess: () => {
                    setOpen(false);
                    toast.success("Record deleted");
                    onDeleted();
                  },
                  onError: (problem) => toast.error(describeError(problem).reason),
                },
              );
            }}
          >
            Delete record
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** "Delete learnings for {user}": every type or one, enabled once the user id is typed. */
function DeleteUserLearnings({
  instance,
  user,
  onDeleted,
}: {
  instance: string;
  user: string;
  onDeleted: () => Promise<void>;
}) {
  const [type, setType] = useState(ALL);
  const [confirm, setConfirm] = useState("");
  const remove = useMutation({
    mutationFn: async () =>
      (
        await contextDeleteUserLearnings({
          path: { instance },
          body: { user_id: user, learning_type: type === ALL ? null : type, confirm },
          throwOnError: true,
        })
      ).data,
    onSuccess: async (result) => {
      setConfirm("");
      await onDeleted();
      toast.success(
        `Deleted ${result.deleted === null ? "the" : String(result.deleted)} learnings of ${user}${type === ALL ? "" : ` (${type})`}`,
      );
    },
    onError: (problem) => toast.error(describeError(problem).reason),
  });
  const matches = confirm.trim() === user;

  return (
    <section
      aria-label={`Delete learnings for ${user}`}
      className="flex flex-col gap-3 rounded-card border border-danger/35 bg-danger/4 p-4"
    >
      <h3 className="text-[13.5px] font-semibold">
        Delete learnings for <code className="font-mono">{user}</code>
      </h3>
      <p className="text-[12.5px] text-fg-secondary">
        Use for data-deletion requests. Removes every learning this user owns, or one type only. Memories and
        sessions are separate. Needs <code className="font-mono">learnings:delete</code>.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={type} onValueChange={setType}>
          <SelectTrigger aria-label="Which types" className="h-8 w-52">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All types</SelectItem>
            {LEARNING_TYPES.map((item) => (
              <SelectItem key={item} value={item}>
                {item} only
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          aria-label="Confirmation"
          mono
          className="h-8 w-56"
          placeholder={`Type ${user} to confirm`}
          value={confirm}
          onChange={(event) => {
            setConfirm(event.target.value);
          }}
        />
        <Button
          variant="destructive-outline"
          size="32"
          disabled={!matches || remove.isPending}
          onClick={() => {
            remove.mutate();
          }}
        >
          {remove.isPending ? "Deleting…" : "Delete all"}
        </Button>
      </div>
    </section>
  );
}
