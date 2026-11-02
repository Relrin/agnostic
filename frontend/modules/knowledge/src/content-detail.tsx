import { describeError } from "@agnostic/api";
import { PermissionGate, formatRelative } from "@agnostic/core";
import {
  Button,
  Input,
  KeyValueList,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useId, useState } from "react";

import { useContentActions, type ContentRow } from "./knowledge-api";

function textMetadata(metadata: Record<string, unknown> | null | undefined): Record<string, string> {
  return Object.fromEntries(
    Object.entries(metadata ?? {}).map(([key, value]) => [
      key,
      typeof value === "string" ? value : JSON.stringify(value),
    ]),
  );
}

/** Content drawer: facts, metadata edit (PATCH), re-ingest and delete. */
export function ContentDetail({
  instance,
  kb,
  row,
  onClose,
}: {
  instance: string;
  kb: string;
  row: ContentRow;
  onClose: () => void;
}) {
  const actions = useContentActions(instance, kb);
  const ids = useId();
  const [name, setName] = useState(row.name ?? "");
  const [description, setDescription] = useState(row.description ?? "");
  const [metadata, setMetadata] = useState(() => JSON.stringify(textMetadata(row.metadata), null, 2));
  const [error, setError] = useState<string | undefined>(undefined);
  const [confirming, setConfirming] = useState(false);

  const save = () => {
    let parsed: Record<string, string>;
    try {
      const value = JSON.parse(metadata) as unknown;
      if (typeof value !== "object" || value === null || Array.isArray(value))
        throw new Error("Metadata must be a JSON object.");
      parsed = textMetadata(value as Record<string, unknown>);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Not valid JSON.");
      return;
    }
    setError(undefined);
    actions.update.mutate(
      { id: row.id, name, description, metadata: parsed },
      {
        onSuccess: () => toast.success("Content updated"),
        onError: (problem) => toast.error(describeError(problem).reason),
      },
    );
  };

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent className="w-[min(480px,100%)] overflow-y-auto">
        <div className="flex flex-col gap-1 pr-8">
          <SheetTitle className="font-mono text-[15px] font-semibold break-all">
            {row.name ?? row.id}
          </SheetTitle>
          <SheetDescription className="text-[12.5px] text-fg-muted">
            {row.kind ?? row.type ?? "Content"} · {row.status ?? "completed"}
            {row.status_message ? ` · ${row.status_message}` : ""}
          </SheetDescription>
        </div>
        <KeyValueList
          items={[
            { key: "id", label: "Content id", value: row.id, mono: true },
            { key: "type", label: "MIME type", value: row.type ?? "—", mono: true },
            { key: "access", label: "Read by agents", value: `${String(row.access_count ?? 0)} times` },
            { key: "created", label: "Created", value: formatRelative(row.created_at) },
            { key: "updated", label: "Updated", value: formatRelative(row.updated_at) },
          ]}
        />
        <PermissionGate
          scope="knowledge:write"
          instance={instance}
          fallback={<p className="text-[12.5px] text-fg-muted">Editing needs knowledge:write.</p>}
        >
          <div className="flex flex-col gap-3">
            <label
              htmlFor={`${ids}-name`}
              className="flex flex-col gap-1.5 text-[13px] font-medium text-fg-secondary"
            >
              Name
              <Input
                id={`${ids}-name`}
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            </label>
            <label
              htmlFor={`${ids}-description`}
              className="flex flex-col gap-1.5 text-[13px] font-medium text-fg-secondary"
            >
              Description
              <Input
                id={`${ids}-description`}
                value={description}
                onChange={(event) => {
                  setDescription(event.target.value);
                }}
              />
            </label>
            <label
              htmlFor={`${ids}-metadata`}
              className="flex flex-col gap-1.5 text-[13px] font-medium text-fg-secondary"
            >
              Metadata
              <Textarea
                id={`${ids}-metadata`}
                rows={5}
                value={metadata}
                aria-invalid={error ? true : undefined}
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
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" size="30" disabled={actions.update.isPending} onClick={save}>
                {actions.update.isPending ? "Saving…" : "Save"}
              </Button>
              <Button
                variant="outline"
                size="30"
                disabled={actions.reingest.isPending}
                onClick={() => {
                  actions.reingest.mutate(
                    { id: row.id },
                    {
                      onSuccess: () => toast.success("Re-ingesting; the status updates as it runs"),
                      onError: (problem) => toast.error(describeError(problem).reason),
                    },
                  );
                }}
              >
                Refresh (re-ingest)
              </Button>
            </div>
          </div>
        </PermissionGate>
        <PermissionGate scope="knowledge:delete" instance={instance}>
          <div className="mt-auto flex flex-col gap-2 border-t border-border-subtle pt-4">
            {confirming ? (
              <>
                <p className="text-[12.5px] text-fg-secondary">
                  Delete {row.name ?? row.id} and its chunks? Agents stop finding it. This can&apos;t be
                  undone.
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="30"
                    onClick={() => {
                      setConfirming(false);
                    }}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="destructive-outline"
                    size="30"
                    disabled={actions.remove.isPending}
                    onClick={() => {
                      actions.remove.mutate(
                        { id: row.id },
                        {
                          onSuccess: () => {
                            toast.success("Content deleted");
                            onClose();
                          },
                          onError: (problem) => toast.error(describeError(problem).reason),
                        },
                      );
                    }}
                  >
                    Delete content
                  </Button>
                </div>
              </>
            ) : (
              <Button
                variant="destructive-text"
                size="30"
                className="self-start"
                onClick={() => {
                  setConfirming(true);
                }}
              >
                Delete…
              </Button>
            )}
          </div>
        </PermissionGate>
      </SheetContent>
    </Sheet>
  );
}
