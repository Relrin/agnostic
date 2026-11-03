// Groups: manual and IdP-synced groups with their members and role bindings, and "New group".
import { describeError, directoryCreateGroupMutation, type GroupOut } from "@agnostic/api";
import { PermissionGate } from "@agnostic/core";
import {
  AccessChip,
  Badge,
  Button,
  Callout,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  Textarea,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type SubmitEvent } from "react";

import {
  endsLabel,
  findInstance,
  grantName,
  groupBindings,
  refreshDirectory,
  roleColor,
  sourceLabel,
  type Directory,
  type PeopleSearch,
} from "./people-api";

export function GroupBindingChips({ group, directory }: { group: GroupOut; directory: Directory }) {
  const bindings = groupBindings(group.id, directory.allBindings);
  if (bindings.length === 0) return <span className="text-[12.5px] text-fg-muted">No role bindings</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {bindings.map((binding) => {
        const instance = findInstance(directory.allInstances, binding.instance_id);
        return (
          <AccessChip
            key={binding.id}
            roleName={grantName(binding, directory.allRoles)}
            color={roleColor(binding.role_id, directory.allRoles)}
            instance={instance?.slug ?? null}
            env={instance?.env_tag ?? null}
            expires={endsLabel(binding.expires_at)}
          />
        );
      })}
    </div>
  );
}

function NewGroupDialog({
  open,
  onOpenChange,
  directory,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  directory: Directory;
  onCreated: (groupId: string) => void;
}) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [owners, setOwners] = useState<string[]>([]);
  const create = useMutation({
    ...directoryCreateGroupMutation(),
    onSuccess: async (group) => {
      toast.success(`Created ${group.name}`);
      await refreshDirectory(client);
      onOpenChange(false);
      onCreated(group.id);
    },
  });
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    create.mutate({
      body: {
        name: name.trim(),
        description: description.trim(),
        member_ids: members.filter((id) => !owners.includes(id)),
        owner_ids: owners,
      },
    });
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New group</DialogTitle>
          <DialogDescription>
            A manual group. Role bindings on the group apply to everyone in it; owners can manage its members.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4">
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
          <fieldset className="flex flex-col gap-1.5">
            <legend className="mb-1 text-[13px] font-medium text-fg-secondary">Members</legend>
            <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
              {directory.allMembers.map((member) => {
                const inGroup = members.includes(member.user_id);
                return (
                  <li key={member.user_id} className="flex items-center gap-2 text-[13px]">
                    <label className="flex flex-1 cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        className="size-4 accent-[var(--accent)]"
                        aria-label={member.display_name}
                        checked={inGroup}
                        onChange={() => {
                          setMembers(
                            inGroup
                              ? members.filter((id) => id !== member.user_id)
                              : [...members, member.user_id],
                          );
                          if (inGroup) setOwners(owners.filter((id) => id !== member.user_id));
                        }}
                      />
                      {member.display_name}
                      <span className="text-[12px] text-fg-muted">{member.email}</span>
                    </label>
                    <label className="flex cursor-pointer items-center gap-1.5 text-[12px] text-fg-secondary">
                      <input
                        type="checkbox"
                        className="size-3.5 accent-[var(--accent)]"
                        aria-label={`${member.display_name} is an owner`}
                        disabled={!inGroup}
                        checked={owners.includes(member.user_id)}
                        onChange={() => {
                          setOwners(
                            owners.includes(member.user_id)
                              ? owners.filter((id) => id !== member.user_id)
                              : [...owners, member.user_id],
                          );
                        }}
                      />
                      Owner
                    </label>
                  </li>
                );
              })}
            </ul>
          </fieldset>
          {create.error && <Callout tone="danger">{describeError(create.error).reason}</Callout>}
          <DialogFooter>
            <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
              Create group
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function GroupsTab({
  directory,
  state,
  go,
}: {
  directory: Directory;
  state: PeopleSearch;
  go: (next: Partial<PeopleSearch>) => void;
}) {
  const [creating, setCreating] = useState(false);
  const groups = directory.groupsQuery;
  const columns: Column<GroupOut>[] = [
    {
      id: "group",
      header: "Group",
      cell: (group) => (
        <div className="flex flex-col gap-0.5">
          <button
            type="button"
            className="cursor-pointer self-start text-left font-medium hover:underline"
            onClick={(event) => {
              event.stopPropagation();
              go({ group: group.id, member: undefined });
            }}
          >
            {group.name}
          </button>
          {group.description && <span className="text-[12px] text-fg-muted">{group.description}</span>}
        </div>
      ),
    },
    {
      id: "members",
      header: "Members",
      align: "right",
      cell: (group) => group.member_count,
    },
    {
      id: "bindings",
      header: "Role bindings",
      cell: (group) => <GroupBindingChips group={group} directory={directory} />,
    },
    {
      id: "source",
      header: "Source",
      cell: (group) =>
        group.synced ? (
          <span className="flex items-center gap-1.5 font-mono text-[12px] text-fg-secondary">
            <Badge tone="info">synced</Badge>
            {sourceLabel(group)}
          </span>
        ) : (
          <span className="text-fg-secondary">Manual</span>
        ),
    },
  ];
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-fg-secondary">
          Role bindings on a group apply to all of its members. Synced groups follow the IdP.
        </p>
        <PermissionGate scope="org:members:write">
          <Button
            variant="outline"
            size="32"
            onClick={() => {
              setCreating(true);
            }}
          >
            <Plus aria-hidden />
            New group
          </Button>
        </PermissionGate>
      </div>
      {groups.isPending ? (
        <LoadingRows rows={3} label="Loading groups" />
      ) : groups.isError ? (
        <ErrorState {...describeError(groups.error)} onRetry={() => void groups.refetch()} />
      ) : (
        <div className="min-w-0 overflow-x-auto">
          <div className="min-w-[760px]">
            <DataTable
              label="Groups"
              columns={columns}
              rows={groups.data}
              rowKey={(group) => group.id}
              selectedKey={state.group ?? ""}
              onRowClick={(group) => {
                go({ group: group.id, member: undefined });
              }}
              empty={
                <EmptyState title="No groups yet.">
                  Create a group to give several people the same access, or connect SCIM to sync them from
                  your IdP.
                </EmptyState>
              }
            />
          </div>
        </div>
      )}
      {creating && (
        <NewGroupDialog
          open={creating}
          onOpenChange={setCreating}
          directory={directory}
          onCreated={(groupId) => {
            go({ group: groupId });
          }}
        />
      )}
    </div>
  );
}
