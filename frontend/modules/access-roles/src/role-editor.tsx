// The access-role editor: name and description, instances it can be bound on, the permission matrix and the save
// bar; plus the token-scopes aside, a live server preview of what saving the draft does and for whom.
import {
  accessDuplicateRoleMutation,
  accessListRolesOptions,
  accessListRolesQueryKey,
  accessPreviewRole,
  accessUpdateRoleMutation,
  describeError,
  problemCode,
  type InstanceOut,
  type RoleIn,
  type RoleOut,
  type RolePreviewOut,
  type ScopeOut,
} from "@agnostic/api";
import { useCan, withQueryFn } from "@agnostic/core";
import { Badge, Button, Callout, Input, SaveBar, ScopeDiff, Textarea, cn, toast } from "@agnostic/ui";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";

import { PermissionMatrix } from "./permission-matrix";
import { DeleteRoleDialog, HoldersSheet, ResetRoleDialog, VersionsSheet } from "./role-dialogs";
import {
  bindableOn,
  bodyOf,
  buildMatrix,
  changeCount,
  changedCells,
  draftOf,
  scopeLines,
  toggleInstance,
  type RoleDraft,
} from "./roles-api";

const ENV_DOT: Record<InstanceOut["env_tag"], string> = {
  production: "bg-warning",
  staging: "bg-info",
  development: "bg-fg-muted",
};

/** `value`, once it has stopped changing for `delay` ms. */
function useSettled<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSettled(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return settled;
}

function Section({ title, hint, children }: { title: string; hint?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h3 id={id} className="text-[13.5px] font-semibold">
          {title}
        </h3>
        {hint && <span className="text-[12px] text-fg-muted">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

/** "Can be bound on": one toggle pill per instance; all on means every instance, present and future. */
function InstancePills({
  roleName,
  instances,
  base,
  draft,
  disabled,
  onChange,
}: {
  roleName: string;
  instances: readonly InstanceOut[];
  base: RoleDraft;
  draft: RoleDraft;
  disabled: boolean;
  onChange: (bindable: string[] | null) => void;
}) {
  const ids = instances.map((instance) => instance.id);
  const onCount = ids.filter((id) => bindableOn(draft.bindable, id)).length;
  return (
    <div role="group" aria-label={`Instances ${roleName} can be bound on`} className="flex flex-wrap gap-2">
      {instances.map((instance) => {
        const on = bindableOn(draft.bindable, instance.id);
        const changed = on !== bindableOn(base.bindable, instance.id);
        return (
          <button
            key={instance.id}
            type="button"
            aria-pressed={on}
            disabled={disabled || (on && onCount === 1)}
            title={on && onCount === 1 ? "A role must be bindable on at least one instance." : undefined}
            className={cn(
              "inline-flex h-[30px] cursor-pointer items-center gap-2 rounded-full border px-3 font-mono text-[12.5px] disabled:cursor-default",
              on ? "border-border-strong bg-surface text-fg" : "border-border text-fg-muted",
              changed && "border-accent/60 bg-accent/9",
            )}
            onClick={() => {
              onChange(toggleInstance(draft.bindable, instance.id, ids));
            }}
          >
            <span
              aria-hidden
              className={cn("size-2 rounded-full", on ? ENV_DOT[instance.env_tag] : "bg-border-strong")}
            />
            {instance.slug}
          </button>
        );
      })}
      {draft.bindable === null && (
        <span className="self-center text-[12px] text-fg-muted">All instances</span>
      )}
    </div>
  );
}

/** The right column: token scopes with the diff of the draft, and what saving does. */
function TokenScopes({
  role,
  dirty,
  preview,
  previewError,
  updating,
}: {
  role: RoleOut;
  dirty: boolean;
  preview: RolePreviewOut | undefined;
  previewError: unknown;
  updating: boolean;
}) {
  const scopes = preview?.role.scopes ?? role.scopes;
  const added = dirty ? (preview?.added ?? []) : [];
  const removed = dirty ? (preview?.removed ?? []) : [];
  const copy = () => {
    const text = JSON.stringify({ scopes: [...scopes].sort() }, null, 2);
    if (typeof navigator !== "undefined" && "clipboard" in navigator) {
      void navigator.clipboard.writeText(text).then(
        () => toast.success("Scopes copied"),
        () => toast.error("Couldn't copy to the clipboard"),
      );
    }
  };
  return (
    <aside
      aria-label="Token scopes"
      className="flex w-full shrink-0 flex-col gap-4 overflow-y-auto border-border-subtle p-5 lg:w-[340px] lg:border-l"
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <h2 className="text-[15px] font-semibold">Token scopes</h2>
          <Badge tone="outline" aria-label={`${String(scopes.length)} scopes`}>
            {scopes.length}
          </Badge>
          {updating && <span className="text-[11.5px] text-fg-muted">Updating…</span>}
        </div>
        <p className="text-[12.5px] text-fg-secondary">
          Added to the JWT of everyone bound to {role.name}, on bound instances.
        </p>
      </div>

      <div className="flex flex-col rounded-tile border border-border bg-inset">
        <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
          <code className="font-mono text-[12px] text-fg-muted">&quot;scopes&quot;: [ … ]</code>
          <Button variant="ghost" size="28" onClick={copy}>
            <Copy aria-hidden />
            Copy JSON
          </Button>
        </div>
        <ScopeDiff
          label="Scopes"
          className="max-h-[420px] overflow-y-auto px-3 py-2"
          empty="No scopes."
          lines={scopeLines(scopes, added, removed)}
        />
      </div>

      {Boolean(previewError) && (
        <Callout tone="danger" title="This draft can't be saved">
          {describeError(previewError).reason}
        </Callout>
      )}

      <section
        aria-label="When you save"
        className="flex flex-col gap-2 rounded-tile border border-border p-3 text-[12.5px]"
      >
        <h3 className="text-[13px] font-semibold">When you save</h3>
        {dirty && (added.length > 0 || removed.length > 0) && (
          <ScopeDiff label="Scope changes" lines={preview?.lines ?? []} />
        )}
        <p className="text-fg-secondary">
          {!dirty && preview
            ? `Held by ${preview.reach.sentence}. A saved change reaches them on their next request.`
            : preview
              ? `${preview.reach.sentence} get the new scopes on their next request.`
              : "Everyone holding the role gets the new scopes on their next request."}{" "}
          <strong className="font-medium text-fg">No redeploy.</strong>
        </p>
        {preview?.warnings.map((warning) => (
          <Callout key={warning} tone="warning">
            {warning.replace(/`/g, "")}
          </Callout>
        ))}
        <p className="text-fg-muted">Recorded in the audit log with this diff.</p>
      </section>
    </aside>
  );
}

export function RoleEditor({
  role,
  catalog,
  instances,
  onSelect,
}: {
  role: RoleOut;
  catalog: readonly ScopeOut[];
  instances: readonly InstanceOut[];
  onSelect: (id: string | undefined) => void;
}) {
  const client = useQueryClient();
  const canWrite = useCan("org:roles:write").allowed === true;
  const canDelete = useCan("org:roles:delete").allowed === true;
  const [base, setBase] = useState(role);
  const [draft, setDraft] = useState(() => draftOf(role));
  const saved = useMemo(() => draftOf(base), [base]);
  const instanceIds = instances.map((instance) => instance.id);
  const dirty = changeCount(saved, draft, instanceIds);

  // A newer version arrived (someone else saved, or a refetch after ours) while nothing is edited: take it.
  if (role.version !== base.version && dirty === 0) {
    setBase(role);
    setDraft(draftOf(role));
  }

  const adopt = (next: RoleOut) => {
    client.setQueryData<RoleOut[]>(accessListRolesQueryKey(), (list) =>
      list?.map((item) => (item.id === next.id ? { ...item, ...next } : item)),
    );
    setBase(next);
    setDraft(draftOf(next));
  };

  const body = useMemo<RoleIn>(() => bodyOf(draft), [draft]);
  const settledBody = useSettled(body, 300);
  const preview = useQuery({
    queryKey: ["accessRolePreview", role.id, settledBody],
    queryFn: async ({ signal }) =>
      (await accessPreviewRole({ path: { role_id: role.id }, body: settledBody, signal, throwOnError: true }))
        .data,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  });
  const updating = body !== settledBody || preview.isPlaceholderData;

  const save = useMutation({
    ...accessUpdateRoleMutation(),
    onSuccess: (result) => {
      adopt(result.role);
      client.setQueryData(["accessRolePreview", role.id, bodyOf(draftOf(result.role))], {
        ...result,
        added: [],
        removed: [],
        lines: [],
      });
      void client.invalidateQueries({ queryKey: [{ _id: "accessRoleVersions" }] });
      void client.invalidateQueries({ queryKey: [{ _id: "accessRoleHolders" }] });
      toast.success(`${result.role.name} saved as version ${String(result.role.version)}`);
    },
  });
  const conflict = problemCode(save.error) === "version_conflict";

  const duplicate = useMutation({
    ...accessDuplicateRoleMutation(),
    onSuccess: async (copy) => {
      await client.invalidateQueries({ queryKey: accessListRolesQueryKey() });
      toast.success(`${copy.name} created`);
      onSelect(copy.id);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });

  const reload = async () => {
    const result = await client.query({ ...withQueryFn(accessListRolesOptions()), staleTime: 0 });
    const fresh = result.find((item) => item.id === role.id);
    save.reset();
    if (fresh) {
      setBase(fresh);
      setDraft(draftOf(fresh));
    }
  };

  const groups = useMemo(
    () => buildMatrix(catalog, { ...saved.permissions, ...draft.permissions }),
    [catalog, saved.permissions, draft.permissions],
  );
  const changed = changedCells(saved, draft);
  const set = (next: Partial<RoleDraft>) => {
    setDraft((current) => ({ ...current, ...next }));
  };

  return (
    <>
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <div className="flex flex-col gap-6 px-6 pt-5 pb-8">
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span aria-hidden className="size-2.5 rounded-full" style={{ backgroundColor: draft.color }} />
              <Input
                aria-label="Role name"
                className="h-9 max-w-[360px] border-transparent bg-transparent px-1 text-[20px] font-semibold hover:border-border focus:border-border-strong"
                readOnly={!canWrite}
                maxLength={80}
                value={draft.name}
                onChange={(event) => {
                  set({ name: event.target.value });
                }}
              />
              {role.kind === "built_in" && <Badge tone="outline">built in</Badge>}
            </div>
            <Textarea
              aria-label="Description"
              rows={2}
              className="max-w-[640px] resize-none border-transparent bg-transparent px-1 text-[13.5px] text-fg-secondary hover:border-border focus:border-border-strong"
              readOnly={!canWrite}
              placeholder="What this role is for"
              value={draft.description}
              onChange={(event) => {
                set({ description: event.target.value });
              }}
            />
            <div className="flex flex-wrap items-center gap-1">
              <HoldersSheet role={base} instances={instances} />
              <VersionsSheet role={base} />
              {canWrite && (
                <Button
                  variant="ghost"
                  size="30"
                  disabled={duplicate.isPending}
                  onClick={() => {
                    duplicate.mutate({ path: { role_id: role.id }, body: {} });
                  }}
                >
                  <Copy aria-hidden />
                  Duplicate
                </Button>
              )}
              {canWrite && role.kind === "built_in" && (
                <ResetRoleDialog
                  role={base}
                  onReset={(result) => {
                    save.reset();
                    adopt(result.role);
                    toast.success(`${result.role.name} reset to its defaults`);
                  }}
                />
              )}
              {canDelete && role.kind === "custom" && (
                <DeleteRoleDialog
                  role={base}
                  instances={instances}
                  onDeleted={() => {
                    onSelect(undefined);
                  }}
                />
              )}
            </div>
          </div>

          <Section title="Can be bound on" hint="Bindings on other instances are refused.">
            <InstancePills
              roleName={base.name}
              instances={instances}
              base={saved}
              draft={draft}
              disabled={!canWrite}
              onChange={(bindable) => {
                set({ bindable });
              }}
            />
          </Section>

          <Section title="Permissions" hint="Scopes are resource:action; tinted cells are unsaved.">
            <PermissionMatrix
              roleName={base.name}
              groups={groups}
              base={saved}
              draft={draft}
              disabled={!canWrite}
              changed={changed}
              onPermissions={(permissions) => {
                set({ permissions });
              }}
              onRunScope={(resource, choice) => {
                setDraft((current) => ({
                  ...current,
                  runScope: { ...current.runScope, [resource]: choice },
                }));
              }}
            />
          </Section>
        </div>

        {canWrite && (
          <div className="sticky bottom-0 mt-auto flex flex-col gap-2">
            {conflict ? (
              <Callout
                tone="warning"
                className="mx-6"
                title={`${base.name} changed since you opened it`}
                action={
                  <Button variant="outline" size="30" onClick={() => void reload()}>
                    Reload
                  </Button>
                }
              >
                {describeError(save.error).reason} Reloading discards your unsaved edits.
              </Callout>
            ) : (
              save.error && (
                <Callout tone="danger" className="mx-6" title="The role wasn't saved">
                  {describeError(save.error).reason}
                </Callout>
              )
            )}
            <SaveBar
              dirty={dirty}
              saving={save.isPending}
              saveLabel="Save role"
              disabled={!draft.name.trim()}
              note={dirty > 0 ? "No redeploy" : undefined}
              className={cn(dirty > 0 && "border-warning/40")}
              onDiscard={() => {
                save.reset();
                setDraft(saved);
              }}
              onSave={() => {
                save.mutate({
                  path: { role_id: role.id },
                  body: { ...bodyOf(draft), version: base.version },
                });
              }}
            />
          </div>
        )}
      </div>
      <TokenScopes
        role={base}
        dirty={dirty > 0}
        preview={preview.data}
        previewError={preview.error}
        updating={updating}
      />
    </>
  );
}
