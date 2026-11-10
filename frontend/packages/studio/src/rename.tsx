// Renaming an agent, team or workflow stored in Studio. Only the display name changes: the id, and with it the
// component's URLs, sessions and traces, stays as it is.
import { describeError, studioPatchComponentMutation, type ComponentDetailOut } from "@agnostic/api";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  toast,
} from "@agnostic/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

export type RenameTarget = { id: string; name: string; kind: string };

const NAME_MAX = 200;

function RenameForm({
  instance,
  target,
  before,
  onRenamed,
  onClose,
}: {
  instance: string;
  target: RenameTarget;
  before: (() => Promise<unknown>) | undefined;
  onRenamed: ((detail: ComponentDetailOut) => void) | undefined;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const field = useId();
  const [name, setName] = useState(target.name);
  const next = name.trim();
  const rename = useMutation({
    ...studioPatchComponentMutation(),
    onSuccess: (detail) => {
      // Lists, the open component and the registry's "used by" all show the name.
      for (const id of [
        "studioListComponents",
        "studioGetComponent",
        "studioRegistry",
        "studioRegistryEntry",
      ])
        void client.invalidateQueries({ queryKey: [{ _id: id }] });
      onRenamed?.(detail);
      toast.success(`Renamed to ${detail.component.name}`);
      onClose();
    },
  });
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        void (async () => {
          await before?.();
          rename.mutate({ path: { instance, component_id: target.id }, body: { name: next } });
        })();
      }}
    >
      <div className="flex flex-col gap-1.5">
        <label htmlFor={field} className="text-[12.5px] text-fg-secondary">
          Name
        </label>
        <Input
          id={field}
          maxLength={NAME_MAX}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <p className="text-[12px] text-fg-muted">
          The id stays <code className="font-mono break-all">{target.id}</code>, so links, sessions and traces
          keep working.
        </p>
      </div>
      {rename.isError && <p className="text-[12px] text-danger">{describeError(rename.error).reason}</p>}
      <DialogFooter>
        <Button type="button" variant="outline" size="32" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="32"
          disabled={!next || next === target.name || rename.isPending}
        >
          Rename
        </Button>
      </DialogFooter>
    </form>
  );
}

/**
 * Rename `target` (closed while it is `undefined`). `before` runs ahead of the request, for an editor to save what
 * it holds; `onRenamed` gets the component as the server now has it.
 */
export function RenameComponentDialog({
  instance,
  target,
  onClose,
  before,
  onRenamed,
}: {
  instance: string;
  target: RenameTarget | undefined;
  onClose: () => void;
  before?: () => Promise<unknown>;
  onRenamed?: (detail: ComponentDetailOut) => void;
}) {
  return (
    <Dialog
      open={target !== undefined}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{target ? `Rename ${target.name}` : "Rename"}</DialogTitle>
          <DialogDescription>
            The new name shows in Studio right away. Chat, sessions and traces show it once the next version
            of this {target?.kind ?? "component"} is published.
          </DialogDescription>
        </DialogHeader>
        {target && (
          <RenameForm
            key={target.id}
            instance={instance}
            target={target}
            before={before}
            onRenamed={onRenamed}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
