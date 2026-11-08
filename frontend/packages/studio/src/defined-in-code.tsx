// Agents, teams and workflows defined in the runtime's code: opened read-only (`?source=code`), with where they are
// defined, and duplicated into Studio to get an editable copy.
import {
  describeError,
  studioCreateComponent,
  studioListComponentsQueryKey,
  type CodeComponentOut,
} from "@agnostic/api";
import {
  Button,
  Callout,
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
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Copy, Lock } from "lucide-react";
import { useState } from "react";

import type { EditableKind } from "./config";

export type ComponentOrigin = "studio" | "code";

export type DuplicateSource = { id: string; name: string; origin: ComponentOrigin };

const NOUN: Record<EditableKind, string> = { agent: "agent", team: "team", workflow: "workflow" };

/** The editor was opened on a component defined in code (`?source=code`). */
export function useDefinedInCode(): boolean {
  const raw = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  return raw.source === "code";
}

/** Where the component is defined: `app.agents.billing_agent:8`, else the file, else nothing. */
export function definedAt(definition: CodeComponentOut | undefined): string | undefined {
  const source = definition?.source;
  if (!source) return undefined;
  const where = source.module ?? source.file;
  if (!where) return undefined;
  return source.line ? `${where}:${String(source.line)}` : where;
}

/** The header chip in place of the draft chip. */
export function DefinedInCodeChip({ definition }: { definition: CodeComponentOut | undefined }) {
  const where = definedAt(definition);
  return (
    <span
      className="inline-flex h-7 items-center gap-2 rounded-full border border-border-strong px-3 text-[12px] text-fg-secondary"
      title={definition?.source?.file ?? undefined}
    >
      <Lock aria-hidden className="size-3.5" />
      {where ? `Defined in code · ${where} · read-only` : "Defined in code · read-only"}
    </span>
  );
}

/** What the person can and can't do here, with the way to an editable copy. */
export function DefinedInCodeCallout({
  kind,
  definition,
  canDuplicate,
  onDuplicate,
}: {
  kind: EditableKind;
  definition: CodeComponentOut | undefined;
  canDuplicate: boolean;
  onDuplicate: () => void;
}) {
  if (!definition) return null;
  const name = definition.component.name;
  if (definition.unavailable) {
    return (
      <Callout tone="warning" title="The config can't be shown">
        {definition.unavailable}
      </Callout>
    );
  }
  return (
    <Callout
      tone="info"
      title="Locked: defined in code"
      action={
        canDuplicate ? (
          <Button variant="primary" size="30" onClick={onDuplicate}>
            <Copy aria-hidden />
            Duplicate to edit
          </Button>
        ) : undefined
      }
    >
      {`${name} is defined in the runtime's code, so it can't be changed here. Duplicate it to get an editable ${NOUN[kind]} stored in Studio; the original keeps running as it is.`}
    </Callout>
  );
}

function suggestedName(id: string): string {
  return `${id}-copy`;
}

function DuplicateForm({
  instance,
  kind,
  source,
  onDone,
}: {
  instance: string;
  kind: EditableKind;
  source: DuplicateSource;
  onDone: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState(() => suggestedName(source.id));
  const create = useMutation({
    mutationFn: async () =>
      (
        await studioCreateComponent({
          path: { instance },
          body: {
            kind,
            name: name.trim(),
            mode: "duplicate",
            source_id: source.id,
            source_origin: source.origin,
          },
          throwOnError: true,
        })
      ).data,
    onSuccess: (created) => {
      toast.success(`${created.component.name} is ready as draft v${String(created.draft?.version ?? 1)}.`);
      void queryClient.invalidateQueries({
        queryKey: studioListComponentsQueryKey({ path: { instance }, query: { kind } }),
      });
      onDone();
      void navigate({
        to: `/i/${encodeURIComponent(instance)}/studio/${kind}s/${encodeURIComponent(created.component.id)}`,
      });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const ready = name.trim().length > 0;
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready && !create.isPending) create.mutate();
      }}
    >
      <label
        htmlFor="duplicate-component-name"
        className="flex flex-col gap-1 text-[12.5px] text-fg-secondary"
      >
        Name of the copy
        <Input
          id="duplicate-component-name"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
      </label>
      <DialogFooter>
        <Button type="button" variant="secondary" size="32" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="32" disabled={!ready || create.isPending}>
          <Copy aria-hidden />
          {`Duplicate ${NOUN[kind]}`}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** "Duplicate billing-agent": a new component stored in Studio, starting as draft v1 with the source's config. */
export function DuplicateDialog({
  instance,
  kind,
  source,
  onOpenChange,
}: {
  instance: string;
  kind: EditableKind;
  /** The component to copy; the dialog is open while it is set. */
  source: DuplicateSource | undefined;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={source !== undefined} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{`Duplicate ${source?.name ?? NOUN[kind]}`}</DialogTitle>
          <DialogDescription>
            {source?.origin === "code"
              ? `The copy starts as draft v1 stored in Studio, with the config ${source.id} has in code. The original stays defined in code, unchanged.`
              : `The copy starts as draft v1 with the current version of ${source?.id ?? "it"} (or its newest version). The original is unchanged.`}
          </DialogDescription>
        </DialogHeader>
        {source && (
          <DuplicateForm
            key={`${source.origin}:${source.id}`}
            instance={instance}
            kind={kind}
            source={source}
            onDone={() => {
              onOpenChange(false);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
