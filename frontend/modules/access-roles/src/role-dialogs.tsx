// Dialogs and sheets around the role editor: new role, delete (with the bindings that block it), reset a built-in,
// who holds a role, and its saved versions.
import {
  accessCreateRoleMutation,
  accessDeleteRoleMutation,
  accessListRolesQueryKey,
  accessResetRoleMutation,
  accessRoleHoldersOptions,
  accessRoleVersionsOptions,
  describeError,
  membersListMembersOptions,
  type InstanceOut,
  type RoleOut,
  type RolePreviewOut,
} from "@agnostic/api";
import { formatRelative, withQueryFn } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  ErrorState,
  Field,
  Input,
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
  SheetTrigger,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { History, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useState, type SubmitEvent } from "react";

import {
  BLANK_PERMISSIONS,
  ROLE_COLORS,
  blockingBindings,
  holdersLabel,
  plural,
  type BlockingBinding,
} from "./roles-api";

const BLANK = "__blank__";

function instanceName(instances: readonly InstanceOut[], id: string | null): string {
  if (id === null) return "all instances";
  return instances.find((instance) => instance.id === id)?.slug ?? id;
}

const KIND_LABEL: Record<BlockingBinding["principal_kind"], string> = {
  user: "person",
  group: "group",
  service_account: "service account",
};

/** "+ New role": name, color, and a start (blank, or a copy of another role). */
export function NewRoleDialog({
  roles,
  onCreated,
}: {
  roles: readonly RoleOut[];
  onCreated: (id: string) => void;
}) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState<string>(ROLE_COLORS[0]?.value ?? "#C5F25C");
  const [from, setFrom] = useState(BLANK);
  const create = useMutation({
    ...accessCreateRoleMutation(),
    onSuccess: async (role) => {
      await client.invalidateQueries({ queryKey: accessListRolesQueryKey() });
      toast.success(`${role.name} created`);
      setOpen(false);
      onCreated(role.id);
    },
  });
  const reset = () => {
    setName("");
    setFrom(BLANK);
    setColor(ROLE_COLORS[0]?.value ?? "#C5F25C");
    create.reset();
  };
  const source = roles.find((role) => role.id === from);
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    create.mutate({
      body: {
        name: name.trim(),
        color,
        description: source?.description ?? "",
        permissions: source?.permissions ?? BLANK_PERMISSIONS,
        run_scope: source?.run_scope ?? {},
        bindable_instance_ids: source?.bindable_instance_ids ?? null,
      },
    });
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="dashed-add" size="30" className="w-full justify-start">
          <Plus aria-hidden />
          New role
        </Button>
      </DialogTrigger>
      <DialogContent className="w-[min(460px,100%)]">
        <DialogHeader>
          <DialogTitle>New access role</DialogTitle>
          <DialogDescription>
            Access roles apply per AgentOS instance. You pick the permissions in the matrix after it&apos;s
            created.
          </DialogDescription>
        </DialogHeader>
        <form aria-label="New access role" className="flex flex-col gap-4" onSubmit={submit}>
          <Field label="Name">
            {({ id }) => (
              <Input
                id={id}
                placeholder="Support lead"
                maxLength={80}
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                }}
              />
            )}
          </Field>
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-[13px] font-medium text-fg-secondary">Color</legend>
            <div role="radiogroup" aria-label="Color" className="flex flex-wrap gap-2">
              {ROLE_COLORS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={color === option.value}
                  aria-label={option.label}
                  className={cn(
                    "grid size-7 cursor-pointer place-items-center rounded-full border border-transparent",
                    color === option.value && "border-fg",
                  )}
                  onClick={() => {
                    setColor(option.value);
                  }}
                >
                  <span
                    aria-hidden
                    className="size-4 rounded-full"
                    style={{ backgroundColor: option.value }}
                  />
                </button>
              ))}
            </div>
          </fieldset>
          <Field
            label="Start from"
            hint={
              from === BLANK
                ? "A role needs at least one permission, so a blank role starts with agents:read."
                : "Permissions, run scope and instances are copied; the copy is yours to change."
            }
          >
            {({ id, describedBy }) => (
              <Select value={from} onValueChange={setFrom}>
                <SelectTrigger id={id} aria-describedby={describedBy}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={BLANK}>Blank role</SelectItem>
                  {roles.map((role) => (
                    <SelectItem key={role.id} value={role.id}>
                      Copy of {role.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          {create.error && (
            <Callout tone="danger" title="The role wasn't created">
              {describeError(create.error).reason}
            </Callout>
          )}
          <DialogFooter>
            <Button
              variant="ghost"
              size="32"
              onClick={() => {
                setOpen(false);
                reset();
              }}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" size="32" disabled={!name.trim() || create.isPending}>
              Create role
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Delete a custom role; while it is still bound the control plane refuses and lists the bindings. */
export function DeleteRoleDialog({
  role,
  instances,
  onDeleted,
}: {
  role: RoleOut;
  instances: readonly InstanceOut[];
  onDeleted: () => void;
}) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const remove = useMutation({
    ...accessDeleteRoleMutation(),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: accessListRolesQueryKey() });
      toast.success(`${role.name} deleted`);
      setOpen(false);
      onDeleted();
    },
  });
  const bindings = blockingBindings(remove.error);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) remove.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="destructive-text" size="30">
          <Trash2 aria-hidden />
          Delete
        </Button>
      </DialogTrigger>
      <DialogContent className="w-[min(480px,100%)]">
        <DialogHeader>
          <DialogTitle>{bindings ? `${role.name} is still bound` : `Delete ${role.name}?`}</DialogTitle>
          <DialogDescription>
            {bindings
              ? `Remove ${bindings.length === 1 ? "this binding" : `these ${String(bindings.length)} bindings`} in People & groups or Service accounts first; then delete the role.`
              : "The role and its version history go away. This is recorded in the audit log."}
          </DialogDescription>
        </DialogHeader>
        {bindings ? (
          <ul
            aria-label="Bindings"
            className="flex flex-col divide-y divide-divider-row rounded-tile border border-border"
          >
            {bindings.map((binding) => (
              <li key={binding.id} className="flex items-center gap-2 px-3 py-2 text-[13px]">
                <span className="min-w-0 truncate font-medium">
                  {binding.principal_name ?? binding.principal_id}
                </span>
                <Badge tone="outline">{KIND_LABEL[binding.principal_kind]}</Badge>
                <span className="ml-auto font-mono text-[12px] text-fg-muted">
                  {instanceName(instances, binding.instance_id)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          remove.error && <Callout tone="danger">{describeError(remove.error).reason}</Callout>
        )}
        <DialogFooter>
          {bindings ? (
            <>
              <Button asChild variant="outline" size="32">
                <Link to="/access/people">Open People & groups</Link>
              </Button>
              <Button
                variant="primary"
                size="32"
                onClick={() => {
                  setOpen(false);
                  remove.reset();
                }}
              >
                Close
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                size="32"
                onClick={() => {
                  setOpen(false);
                }}
              >
                Keep role
              </Button>
              <Button
                variant="destructive-outline"
                size="32"
                disabled={remove.isPending}
                onClick={() => {
                  remove.mutate({ path: { role_id: role.id } });
                }}
              >
                Delete role
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Put a built-in role back to its defaults (saved as a new version). */
export function ResetRoleDialog({
  role,
  onReset,
}: {
  role: RoleOut;
  onReset: (result: RolePreviewOut) => void;
}) {
  const [open, setOpen] = useState(false);
  const reset = useMutation({
    ...accessResetRoleMutation(),
    onSuccess: (result) => {
      setOpen(false);
      onReset(result);
    },
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" size="30">
          <RotateCcw aria-hidden />
          Reset to default
        </Button>
      </DialogTrigger>
      <DialogContent className="w-[min(440px,100%)]">
        <DialogHeader>
          <DialogTitle>Reset {role.name} to default?</DialogTitle>
          <DialogDescription>
            Its name, description, permissions and instances go back to the built-in defaults, saved as a new
            version. Everyone holding it gets the default scopes on their next request.
          </DialogDescription>
        </DialogHeader>
        {reset.error && <Callout tone="danger">{describeError(reset.error).reason}</Callout>}
        <DialogFooter>
          <Button
            variant="ghost"
            size="32"
            onClick={() => {
              setOpen(false);
            }}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="32"
            disabled={reset.isPending}
            onClick={() => {
              reset.mutate({ path: { role_id: role.id } });
            }}
          >
            Reset role
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** "9 people · 2 groups": the bindings behind that count. */
export function HoldersSheet({ role, instances }: { role: RoleOut; instances: readonly InstanceOut[] }) {
  const [open, setOpen] = useState(false);
  const holders = useQuery({
    ...withQueryFn(accessRoleHoldersOptions({ path: { role_id: role.id } })),
    enabled: open,
  });
  const members = useQuery({ ...withQueryFn(membersListMembersOptions()), enabled: open });
  const name = (kind: string, id: string) => {
    if (kind === "user") return members.data?.find((member) => member.user_id === id)?.display_name ?? id;
    if (kind === "group") return holders.data?.reach.groups.find((group) => group.id === id)?.name ?? id;
    return id;
  };
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="link" size="30">
          {holdersLabel(role)}
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[min(480px,100%)] overflow-y-auto">
        <div className="flex flex-col gap-1 pr-8">
          <SheetTitle className="text-[16px] font-semibold">Who holds {role.name}</SheetTitle>
          <SheetDescription className="text-[12.5px] text-fg-secondary">
            {holders.data
              ? `${holders.data.reach.sentence}.`
              : "People, groups and service accounts bound to it."}
          </SheetDescription>
        </div>
        {holders.isError ? (
          <ErrorState {...describeError(holders.error)} onRetry={() => void holders.refetch()} />
        ) : holders.isPending ? (
          <LoadingRows rows={3} label="Loading holders" />
        ) : holders.data.bindings.length === 0 ? (
          <p className="text-[13px] text-fg-muted">Nobody is bound to {role.name} yet.</p>
        ) : (
          <ul
            aria-label="Holders"
            className="flex flex-col divide-y divide-divider-row rounded-tile border border-border"
          >
            {holders.data.bindings.map((binding) => (
              <li key={binding.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px]">
                <span className="min-w-0 truncate font-medium">
                  {name(binding.principal_kind, binding.principal_id)}
                </span>
                <Badge tone="outline">{KIND_LABEL[binding.principal_kind]}</Badge>
                {binding.expires_at && (
                  <span className="text-[12px] text-warning">ends {formatRelative(binding.expires_at)}</span>
                )}
                <span className="ml-auto font-mono text-[12px] text-fg-muted">
                  {instanceName(instances, binding.instance_id)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {holders.data && holders.data.reach.direct_people.length > 0 && (
          <p className="text-[12px] text-fg-muted">
            {plural(holders.data.reach.direct_people.length, "person", "people")} hold it directly; the rest
            through groups.
          </p>
        )}
        <Button asChild variant="outline" size="32" className="self-start">
          <Link to="/access/people">Open People & groups</Link>
        </Button>
      </SheetContent>
    </Sheet>
  );
}

/** Saved versions, newest first, each with its scope diff against the one before. */
export function VersionsSheet({ role }: { role: RoleOut }) {
  const [open, setOpen] = useState(false);
  const versions = useQuery({
    ...withQueryFn(accessRoleVersionsOptions({ path: { role_id: role.id } })),
    enabled: open,
  });
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="30">
          <History aria-hidden />
          Version {role.version}
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[min(480px,100%)] overflow-y-auto">
        <div className="flex flex-col gap-1 pr-8">
          <SheetTitle className="text-[16px] font-semibold">{role.name} versions</SheetTitle>
          <SheetDescription className="text-[12.5px] text-fg-secondary">
            Every save is a version; the audit log has the same diff under roles.update.
          </SheetDescription>
        </div>
        {versions.isError ? (
          <ErrorState {...describeError(versions.error)} onRetry={() => void versions.refetch()} />
        ) : versions.isPending ? (
          <LoadingRows rows={3} label="Loading versions" />
        ) : (
          <ol aria-label="Versions" className="flex flex-col gap-3">
            {versions.data.map((version, index) => {
              const previous = versions.data[index + 1];
              const added = previous
                ? version.scopes.filter((scope) => !previous.scopes.includes(scope))
                : [];
              const removed = previous
                ? previous.scopes.filter((scope) => !version.scopes.includes(scope))
                : [];
              return (
                <li
                  key={version.version}
                  className="flex flex-col gap-1.5 rounded-tile border border-border p-3"
                >
                  <div className="flex flex-wrap items-center gap-2 text-[13px]">
                    <span className="font-semibold">Version {version.version}</span>
                    {version.version === role.version && <Badge tone="success">current</Badge>}
                    <span className="text-fg-muted">
                      {version.changed_by_name} · {formatRelative(version.changed_at)}
                    </span>
                    <span className="ml-auto text-[12px] text-fg-muted">
                      {plural(version.scopes.length, "scope")}
                    </span>
                  </div>
                  {version.name !== role.name && (
                    <span className="text-[12px] text-fg-muted">Named {version.name}</span>
                  )}
                  {previous ? (
                    <ScopeDiff
                      label={`Version ${String(version.version)} changes`}
                      empty="No scope changes."
                      lines={[
                        ...added.map((text) => ({ op: "add" as const, text })),
                        ...removed.map((text) => ({ op: "remove" as const, text })),
                      ]}
                    />
                  ) : (
                    <span className="text-[12px] text-fg-muted">First version.</span>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </SheetContent>
    </Sheet>
  );
}
