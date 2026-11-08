// Right rail "Session": ids, runs, started, summary, files, session_state, token tiles, rename, delete.
import { describeError } from "@agnostic/api";
import {
  PermissionGate,
  SessionArtifacts,
  formatCount,
  formatWhen,
  useSessionActions,
  type SessionDetail,
  type StoredRun,
} from "@agnostic/core";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  JsonView,
  KeyValueList,
} from "@agnostic/ui";
import { X } from "lucide-react";
import { useState } from "react";

function metric(metrics: unknown, key: string): number | undefined {
  if (typeof metrics !== "object" || metrics === null) return undefined;
  const value = (metrics as Record<string, unknown>)[key];
  return typeof value === "number" ? value : undefined;
}

function summaryText(session: SessionDetail): string | undefined {
  const raw = (session as { session_summary?: unknown }).session_summary;
  if (!raw) return undefined;
  if (typeof raw === "string") return raw;
  if (typeof raw === "object" && "summary" in raw) {
    const summary = raw.summary;
    return typeof summary === "string" ? summary : undefined;
  }
  return undefined;
}

export function SessionRail({
  instance,
  session,
  runs,
  onClose,
  onDeleted,
}: {
  instance: string;
  session: SessionDetail;
  runs: readonly StoredRun[];
  onClose: () => void;
  onDeleted: () => void;
}) {
  const actions = useSessionActions(instance);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [name, setName] = useState(session.session_name);
  const last = runs.at(-1);
  const metrics = (session as { metrics?: unknown }).metrics;
  const input = metric(metrics, "input_tokens");
  const output = metric(metrics, "output_tokens");
  const total =
    metric(metrics, "total_tokens") ??
    (input !== undefined || output !== undefined ? (input ?? 0) + (output ?? 0) : undefined);
  const summary = summaryText(session);

  return (
    <aside
      aria-label="Session"
      className="flex w-80 shrink-0 flex-col gap-4 overflow-y-auto border-l border-border-subtle px-4 py-4"
    >
      <header className="flex items-center justify-between">
        <h2 className="text-[14px] font-semibold">Session</h2>
        <Button variant="icon" size="28" aria-label="Close session details" onClick={onClose}>
          <X aria-hidden />
        </Button>
      </header>
      <KeyValueList
        items={[
          { key: "session_id", label: "session_id", value: session.session_id, mono: true },
          { key: "user_id", label: "user_id", value: session.user_id ?? "—", mono: true },
          {
            key: "runs",
            label: "Runs",
            value: `${String(runs.length)}${last?.status ? ` · ${last.status.toLowerCase()}` : ""}`,
          },
          { key: "started", label: "Started", value: formatWhen(session.created_at) },
        ]}
      />
      <section className="flex flex-col gap-1.5">
        <h3 className="text-[12px] font-semibold text-fg-muted">Summary</h3>
        <p className="text-[13px] text-fg-secondary">{summary ?? "No summary yet."}</p>
      </section>
      <section className="flex flex-col gap-1.5" aria-label="Files">
        <h3 className="text-[12px] font-semibold text-fg-muted">Files</h3>
        <SessionArtifacts instance={instance} sessionId={session.session_id} />
      </section>
      <section className="flex flex-col gap-1.5">
        <h3 className="text-[12px] font-semibold text-fg-muted">session_state</h3>
        <JsonView value={session.session_state ?? {}} label="session_state" />
      </section>
      <section className="grid grid-cols-3 gap-2" aria-label="Tokens">
        {[
          ["Input", input],
          ["Output", output],
          ["Total", total],
        ].map(([label, value]) => (
          <div
            key={String(label)}
            className="flex flex-col rounded-tile border border-border bg-surface px-2.5 py-2"
          >
            <span className="text-[11.5px] text-fg-muted">{label}</span>
            <span className="text-[14px] font-semibold tabular-nums">
              {formatCount(value as number | undefined)}
            </span>
          </div>
        ))}
      </section>
      <footer className="mt-auto flex gap-2">
        <PermissionGate scope="sessions:write" instance={instance}>
          <Button
            size="30"
            variant="outline"
            onClick={() => {
              setName(session.session_name);
              setRenaming(true);
            }}
          >
            Rename
          </Button>
        </PermissionGate>
        <PermissionGate scope="sessions:delete" instance={instance}>
          <Button
            size="30"
            variant="destructive-outline"
            onClick={() => {
              setDeleting(true);
            }}
          >
            Delete session
          </Button>
        </PermissionGate>
      </footer>

      <Dialog open={renaming} onOpenChange={setRenaming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename session</DialogTitle>
            <DialogDescription>The name shows in the session list and in Sessions.</DialogDescription>
          </DialogHeader>
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              actions.rename.mutate(
                { sessionId: session.session_id, name: name.trim() },
                {
                  onSuccess: () => {
                    setRenaming(false);
                  },
                },
              );
            }}
          >
            <Input
              aria-label="Session name"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
            {actions.rename.isError && (
              <p className="text-[12px] text-danger">{describeError(actions.rename.error).reason}</p>
            )}
            <DialogFooter>
              <Button
                type="submit"
                variant="primary"
                size="32"
                disabled={!name.trim() || actions.rename.isPending}
              >
                Rename
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={deleting} onOpenChange={setDeleting}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this session?</DialogTitle>
            <DialogDescription>
              Its {String(runs.length)} {runs.length === 1 ? "run" : "runs"} are deleted on the instance. This
              can't be undone.
            </DialogDescription>
          </DialogHeader>
          {actions.remove.isError && (
            <p className="text-[12px] text-danger">{describeError(actions.remove.error).reason}</p>
          )}
          <DialogFooter>
            <Button
              variant="ghost"
              size="32"
              onClick={() => {
                setDeleting(false);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="destructive-outline"
              size="32"
              disabled={actions.remove.isPending}
              onClick={() => {
                actions.remove.mutate(
                  { sessionId: session.session_id },
                  {
                    onSuccess: () => {
                      setDeleting(false);
                      onDeleted();
                    },
                  },
                );
              }}
            >
              Delete session
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  );
}
