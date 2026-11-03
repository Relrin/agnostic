// The group aside: where the group comes from, its role bindings (add and remove), the approval routes that name it,
// its members and owners, editing a manual group's name and description, and deleting it.
import {
  accessCreateBindingMutation,
  accessDeleteBindingMutation,
  approvalsListGroupRoutesOptions,
  describeError,
  directoryAddGroupMemberMutation,
  directoryDeleteGroupMutation,
  directoryGetGroupOptions,
  directoryRemoveGroupMemberMutation,
  directoryUpdateGroupMutation,
  type GroupDetailOut,
} from "@agnostic/api";
import { STALE_TIME, useCan, withQueryFn } from "@agnostic/core";
import {
  Avatar,
  Badge,
  Button,
  Callout,
  EnvBadge,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type ReactNode, type SubmitEvent } from "react";

import { ConfirmDialog } from "./confirm-dialog";
import { GrantFields, draftGrant, draftReady, emptyDraft, type GrantDraft } from "./grant-fields";
import {
  endsLabel,
  findInstance,
  grantName,
  groupBindings,
  instanceSlug,
  refreshDirectory,
  roleColor,
  type Directory,
  type PeopleSearch,
} from "./people-api";

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 id={id} className="text-[13.5px] font-semibold">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function sourceLine(group: GroupDetailOut): string {
  const count = `${String(group.member_count)} member${group.member_count === 1 ? "" : "s"}`;
  if (!group.synced) return `${count} · manual group`;
  return `${count} · synced from ${group.external_name ?? "the IdP"} (${group.sync_label})`;
}

function DetailsForm({ group, onSaved }: { group: GroupDetailOut; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description);
  const update = useMutation({
    ...directoryUpdateGroupMutation(),
    onSuccess: async () => {
      toast.success("Saved the group");
      await onSaved();
    },
  });
  const dirty = name.trim() !== group.name || description.trim() !== group.description;
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    update.mutate({
      path: { group_id: group.id },
      body: { name: name.trim(), description: description.trim() },
    });
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <Field label="Name">
        {({ id }) => (
          <Input
            id={id}
            required
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        )}
      </Field>
      <Field label="Description">
        {({ id }) => (
          <Textarea
            id={id}
            rows={2}
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
          />
        )}
      </Field>
      {update.error && <Callout tone="danger">{describeError(update.error).reason}</Callout>}
      {dirty && (
        <Button type="submit" size="30" variant="primary" className="self-end" disabled={update.isPending}>
          Save details
        </Button>
      )}
    </form>
  );
}

function Bindings({ group, directory }: { group: GroupDetailOut; directory: Directory }) {
  const client = useQueryClient();
  const canBind = useCan("org:roles:write").allowed === true;
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<GrantDraft>(() =>
    emptyDraft(directory.allRoles, directory.allInstances),
  );
  const refresh = () => refreshDirectory(client);
  const add = useMutation({
    ...accessCreateBindingMutation(),
    onSuccess: async () => {
      setAdding(false);
      setDraft(emptyDraft(directory.allRoles, directory.allInstances));
      await refresh();
    },
  });
  const remove = useMutation({ ...accessDeleteBindingMutation(), onSuccess: refresh });
  const bindings = groupBindings(group.id, directory.allBindings);
  const error = add.error ?? remove.error;
  return (
    <Section
      title="Role bindings"
      action={
        canBind && !adding ? (
          <Button
            variant="link"
            size="28"
            onClick={() => {
              setAdding(true);
            }}
          >
            Add binding
          </Button>
        ) : undefined
      }
    >
      {bindings.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">
          No role bindings: being in {group.name} doesn't give access yet.
        </p>
      ) : (
        <ul
          aria-label="Role bindings"
          className="flex flex-col divide-y divide-divider-row rounded-tile border border-border"
        >
          {bindings.map((binding) => {
            const instance = findInstance(directory.allInstances, binding.instance_id);
            const color = roleColor(binding.role_id, directory.allRoles);
            const ends = endsLabel(binding.expires_at);
            const name = grantName(binding, directory.allRoles);
            return (
              <li key={binding.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px]">
                <span className="font-mono text-[12.5px]">{instance?.slug ?? "all instances"}</span>
                {instance && <EnvBadge env={instance.env_tag} />}
                <span aria-hidden className="text-fg-muted">
                  →
                </span>
                {color && (
                  <span aria-hidden className="size-2 rounded-full" style={{ backgroundColor: color }} />
                )}
                <span className={binding.role_id ? "font-semibold" : "font-mono text-[12.5px]"}>{name}</span>
                {ends && <span className="text-[12px] text-warning">{ends}</span>}
                {canBind && (
                  <Button
                    className="ml-auto"
                    size="28"
                    variant="destructive-text"
                    aria-label={`Remove ${name} on ${instance?.slug ?? "all instances"}`}
                    disabled={remove.isPending}
                    onClick={() => {
                      remove.mutate({ path: { binding_id: binding.id } });
                    }}
                  >
                    Remove
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {adding && (
        <form
          aria-label="Add binding"
          className="flex flex-col gap-2.5 rounded-tile border border-border-dashed p-3"
          onSubmit={(event) => {
            event.preventDefault();
            add.mutate({
              body: { principal_kind: "group", principal_id: group.id, ...draftGrant(draft) },
            });
          }}
        >
          <GrantFields
            draft={draft}
            onChange={setDraft}
            roles={directory.allRoles}
            instances={directory.allInstances}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="30"
              onClick={() => {
                setAdding(false);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" size="30" disabled={!draftReady(draft) || add.isPending}>
              Add binding
            </Button>
          </div>
        </form>
      )}
      {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
    </Section>
  );
}

function ApprovalRoutes({ group, directory }: { group: GroupDetailOut; directory: Directory }) {
  const routes = useQuery({
    ...withQueryFn(approvalsListGroupRoutesOptions({ path: { group_id: group.id } })),
    staleTime: STALE_TIME.list,
    retry: false,
  });
  return (
    <Section title="Approvals routed here">
      {routes.isPending ? (
        <LoadingRows rows={1} label="Loading approval routes" />
      ) : routes.isError ? (
        <p className="text-[12.5px] text-fg-muted">{describeError(routes.error).reason}</p>
      ) : routes.data.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">No approval routing rules name {group.name}.</p>
      ) : (
        <ul aria-label="Approval routes" className="flex flex-col gap-2">
          {routes.data.map((route) => (
            <li key={route.id} className="flex flex-col gap-0.5 rounded-tile border border-border px-3 py-2">
              <span className="flex flex-wrap items-center gap-2 text-[13px]">
                <code className="font-mono font-semibold">{route.tool_name ?? "every tool"}</code>
                <span className="text-fg-muted">·</span>
                <span className="font-medium">{route.name}</span>
              </span>
              <span className="text-[12px] text-fg-muted">
                on {instanceSlug(directory.allInstances, route.instance_id)}
                {route.component_ids.length > 0 && ` · ${route.component_ids.join(" and ")}`} · any member can
                resolve
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Members({ group, directory }: { group: GroupDetailOut; directory: Directory }) {
  const client = useQueryClient();
  const canWrite = useCan("org:members:write").allowed === true;
  const [adding, setAdding] = useState("");
  const refresh = () => refreshDirectory(client);
  const put = useMutation({ ...directoryAddGroupMemberMutation(), onSuccess: refresh });
  const remove = useMutation({ ...directoryRemoveGroupMemberMutation(), onSuccess: refresh });
  const inGroup = new Set(group.members.map((member) => member.user_id));
  const candidates = directory.allMembers.filter((member) => !inGroup.has(member.user_id));
  const error = put.error ?? remove.error;
  return (
    <Section title="Members">
      {group.synced && (
        <p className="text-[12.5px] text-fg-secondary">
          Membership comes from the IdP and is read-only here; owners can still be set.
        </p>
      )}
      {group.members.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">Nobody is in {group.name} yet.</p>
      ) : (
        <ul aria-label="Group members" className="flex flex-col gap-1.5">
          {group.members.map((member) => {
            const owner = member.role === "owner";
            return (
              <li key={member.user_id} className="flex items-center gap-2.5 text-[13px]">
                <Avatar id={member.user_id} name={member.display_name} size={26} />
                <div className="flex min-w-0 flex-col">
                  <span className="flex items-center gap-1.5 font-medium">
                    {member.display_name}
                    {owner && <Badge tone="success">owner</Badge>}
                  </span>
                  <span className="truncate text-[12px] text-fg-muted">{member.email}</span>
                </div>
                {canWrite && (
                  <span className="ml-auto flex items-center gap-1">
                    <Button
                      size="28"
                      variant="ghost"
                      disabled={put.isPending}
                      onClick={() => {
                        put.mutate({
                          path: { group_id: group.id, user_id: member.user_id },
                          body: { role: owner ? "member" : "owner" },
                        });
                      }}
                    >
                      {owner ? "Make member" : "Make owner"}
                    </Button>
                    {!group.synced && (
                      <Button
                        size="28"
                        variant="destructive-text"
                        aria-label={`Remove ${member.display_name} from ${group.name}`}
                        disabled={remove.isPending}
                        onClick={() => {
                          remove.mutate({ path: { group_id: group.id, user_id: member.user_id } });
                        }}
                      >
                        Remove
                      </Button>
                    )}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {canWrite && !group.synced && candidates.length > 0 && (
        <div className="flex gap-2">
          <Select value={adding} onValueChange={setAdding}>
            <SelectTrigger aria-label="Person to add" className="h-8 flex-1">
              <SelectValue placeholder="Add a person…" />
            </SelectTrigger>
            <SelectContent>
              {candidates.map((member) => (
                <SelectItem key={member.user_id} value={member.user_id}>
                  {member.display_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="32"
            variant="dashed-add"
            disabled={!adding || put.isPending}
            onClick={() => {
              put.mutate(
                { path: { group_id: group.id, user_id: adding }, body: { role: "member" } },
                {
                  onSuccess: () => {
                    setAdding("");
                  },
                },
              );
            }}
          >
            Add member
          </Button>
        </div>
      )}
      {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
    </Section>
  );
}

export function GroupAside({
  groupId,
  directory,
  go,
}: {
  groupId: string;
  directory: Directory;
  go: (next: Partial<PeopleSearch>) => void;
}) {
  const client = useQueryClient();
  const canWrite = useCan("org:members:write").allowed === true;
  const [deleting, setDeleting] = useState(false);
  const detail = useQuery({
    ...withQueryFn(directoryGetGroupOptions({ path: { group_id: groupId } })),
    staleTime: STALE_TIME.list,
  });
  const close = () => {
    go({ group: undefined });
  };
  const remove = useMutation({
    ...directoryDeleteGroupMutation(),
    onSuccess: async () => {
      toast.success(`Deleted ${detail.data?.name ?? "the group"}`);
      setDeleting(false);
      close();
      await refreshDirectory(client);
    },
  });
  const group = detail.data;
  const bindings = group ? groupBindings(group.id, directory.allBindings).length : 0;

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <SheetContent className="w-[min(520px,100%)] overflow-y-auto">
        {detail.isPending ? (
          <>
            <SheetTitle className="sr-only">Group details</SheetTitle>
            <SheetDescription className="sr-only">Loading</SheetDescription>
            <LoadingRows rows={4} label="Loading group" />
          </>
        ) : detail.isError || !group ? (
          <>
            <SheetTitle className="text-[16px] font-semibold">Group</SheetTitle>
            <SheetDescription className="sr-only">Not available</SheetDescription>
            <ErrorState {...describeError(detail.error)} onRetry={() => void detail.refetch()} />
          </>
        ) : (
          <>
            <div className="flex flex-col gap-0.5 pr-8">
              <SheetTitle className="text-[16px] font-semibold">{group.name}</SheetTitle>
              <SheetDescription className="text-[12.5px] text-fg-secondary">
                {sourceLine(group)}
              </SheetDescription>
            </div>
            {canWrite && !group.synced ? (
              <DetailsForm
                key={`${group.name}:${group.description}`}
                group={group}
                onSaved={() => refreshDirectory(client)}
              />
            ) : (
              group.description && <p className="text-[13px] text-fg-secondary">{group.description}</p>
            )}
            <Bindings group={group} directory={directory} />
            <ApprovalRoutes group={group} directory={directory} />
            <Members group={group} directory={directory} />
            {canWrite && (
              <div className="mt-auto flex justify-start border-t border-border-subtle pt-4">
                <Button
                  variant="destructive-text"
                  onClick={() => {
                    setDeleting(true);
                  }}
                >
                  Delete group
                </Button>
              </div>
            )}
            <ConfirmDialog
              open={deleting}
              onOpenChange={setDeleting}
              title={`Delete ${group.name}?`}
              confirmLabel="Delete group"
              pending={remove.isPending}
              onConfirm={() => {
                remove.mutate({ path: { group_id: group.id } });
              }}
            >
              Its {bindings} role binding{bindings === 1 ? " is" : "s are"} removed too, so its{" "}
              {group.member_count} member{group.member_count === 1 ? "" : "s"} lose the access they had
              through it.
              {group.synced && " A synced group comes back on the next sync unless it's removed in the IdP."}
            </ConfirmDialog>
            {remove.error && <Callout tone="danger">{describeError(remove.error).reason}</Callout>}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
