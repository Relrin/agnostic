// Members: search and filters (access role, instance, group), effective access chips per instance, and bulk actions
// on the selected rows (change org role, add to a group, remove from the org).
import { describeError, membersBulkMembersMutation, type MemberOut } from "@agnostic/api";
import { ORG_ROLE_LABELS, formatRelative, useCan } from "@agnostic/core";
import {
  AccessChip,
  Avatar,
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  cn,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";

import { ConfirmDialog } from "./confirm-dialog";
import { FilterMenu } from "./filter-menu";
import {
  effectiveGrants,
  endsLabel,
  findInstance,
  memberGroups,
  memberName,
  refreshDirectory,
  type Directory,
  type Grant,
  type PeopleSearch,
} from "./people-api";

type OrgRole = MemberOut["org_role"];

export function GrantChip({ grant, directory }: { grant: Grant; directory: Directory }) {
  const instance = findInstance(directory.allInstances, grant.instanceId);
  return (
    <AccessChip
      roleName={grant.name}
      instance={instance?.slug ?? null}
      env={instance?.env_tag ?? null}
      via={grant.via?.name ?? null}
      color={grant.color}
      expires={endsLabel(grant.binding?.expires_at)}
    />
  );
}

function AccessCell({ member, directory }: { member: MemberOut; directory: Directory }) {
  const grants = effectiveGrants(member, directory.allBindings, directory.allRoles, directory.explicitOnly);
  if (grants.length === 0) return <span className="text-[12.5px] text-fg-muted">No access</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {grants.map((grant) => (
        <GrantChip key={grant.key} grant={grant} directory={directory} />
      ))}
    </div>
  );
}

function BulkBar({
  selected,
  directory,
  onDone,
}: {
  selected: readonly string[];
  directory: Directory;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const bulk = useMutation({
    ...membersBulkMembersMutation(),
    onSuccess: async (outcomes, variables) => {
      const failed = outcomes.filter((outcome) => !outcome.ok);
      for (const outcome of failed)
        toast.error(
          `${memberName(directory.allMembers, outcome.user_id)}: ${outcome.error ?? "not changed"}`,
        );
      const done = outcomes.length - failed.length;
      if (done > 0) {
        const people = `${String(done)} ${done === 1 ? "person" : "people"}`;
        const group = directory.allGroups.find((item) => item.id === variables.body.group_id);
        toast.success(
          variables.body.operation === "add_to_group"
            ? `Added ${people} to ${group?.name ?? "the group"}`
            : variables.body.operation === "remove"
              ? `Removed ${people} from the org`
              : `Changed the org role of ${people}`,
        );
      }
      setConfirming(false);
      onDone();
      await refreshDirectory(client);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const manualGroups = directory.allGroups.filter((group) => !group.synced);
  const count = `${String(selected.length)} selected`;
  return (
    <div
      role="region"
      aria-label="Bulk actions"
      className="flex flex-wrap items-center gap-2 rounded-tile border border-border bg-surface px-3 py-2"
    >
      <span className="text-[13px] font-medium">{count}</span>
      <Button variant="ghost" size="28" onClick={onDone}>
        Clear
      </Button>
      <span className="flex-1" />
      <Select
        value=""
        disabled={bulk.isPending}
        onValueChange={(value) => {
          bulk.mutate({
            body: { user_ids: [...selected], operation: "change_role", org_role: value as OrgRole },
          });
        }}
      >
        <SelectTrigger aria-label="Change org role" className="h-8 w-44">
          <SelectValue placeholder="Change org role" />
        </SelectTrigger>
        <SelectContent>
          {(["member", "administrator", "owner"] as const).map((role) => (
            <SelectItem key={role} value={role}>
              {ORG_ROLE_LABELS[role]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select
        value=""
        disabled={bulk.isPending || manualGroups.length === 0}
        onValueChange={(value) => {
          bulk.mutate({ body: { user_ids: [...selected], operation: "add_to_group", group_id: value } });
        }}
      >
        <SelectTrigger aria-label="Add to group" className="h-8 w-44">
          <SelectValue placeholder="Add to group" />
        </SelectTrigger>
        <SelectContent>
          {manualGroups.map((group) => (
            <SelectItem key={group.id} value={group.id}>
              {group.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="destructive-text"
        size="30"
        disabled={bulk.isPending}
        onClick={() => {
          setConfirming(true);
        }}
      >
        Remove
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={`Remove ${String(selected.length)} from the org?`}
        confirmLabel="Remove from org"
        pending={bulk.isPending}
        onConfirm={() => {
          bulk.mutate({ body: { user_ids: [...selected], operation: "remove" } });
        }}
      >
        They're signed out and lose every role binding, direct or through a group. People synced by SCIM come
        back on the next sync unless they're removed in the IdP.
      </ConfirmDialog>
    </div>
  );
}

function Checkbox({
  label,
  checked,
  indeterminate = false,
  onChange,
}: {
  label: string;
  checked: boolean;
  indeterminate?: boolean;
  onChange: () => void;
}) {
  return (
    <input
      type="checkbox"
      aria-label={label}
      className="size-4 cursor-pointer align-middle accent-[var(--accent)]"
      checked={checked}
      ref={(node) => {
        if (node) node.indeterminate = indeterminate;
      }}
      onClick={(event) => {
        event.stopPropagation();
      }}
      onChange={onChange}
    />
  );
}

export function MembersTab({
  directory,
  state,
  go,
}: {
  directory: Directory;
  state: PeopleSearch;
  go: (next: Partial<PeopleSearch>) => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const canWrite = useCan("org:members:write").allowed === true;
  const { members } = directory;

  const visible = directory.allMembers.filter((member) => {
    const text = `${member.display_name} ${member.email}`.toLowerCase();
    if (query.trim() && !text.includes(query.trim().toLowerCase())) return false;
    if (state.in_group && !memberGroups(member).some((group) => group.id === state.in_group)) return false;
    if (!state.role && !state.instance) return true;
    const grants = effectiveGrants(member, directory.allBindings, directory.allRoles, directory.explicitOnly);
    return grants.some(
      (grant) =>
        (!state.role || grant.binding?.role_id === state.role) &&
        (!state.instance || grant.instanceId === null || grant.instanceId === state.instance),
    );
  });
  const visibleIds = visible.map((member) => member.user_id);
  const chosen = selected.filter((id) => visibleIds.includes(id));
  const allChosen = visible.length > 0 && chosen.length === visible.length;
  const toggle = (id: string) => {
    setSelected(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);
  };
  const hasFilters = Boolean(state.role ?? state.instance ?? state.in_group) || query.trim() !== "";

  const columns: Column<MemberOut>[] = [
    ...(canWrite
      ? [
          {
            id: "select",
            header: (
              <Checkbox
                label="Select all members"
                checked={allChosen}
                indeterminate={chosen.length > 0 && !allChosen}
                onChange={() => {
                  setSelected(allChosen ? [] : visibleIds);
                }}
              />
            ),
            className: "w-10 pr-0",
            cell: (member: MemberOut) => (
              <Checkbox
                label={`Select ${member.display_name}`}
                checked={selected.includes(member.user_id)}
                onChange={() => {
                  toggle(member.user_id);
                }}
              />
            ),
          },
        ]
      : []),
    {
      id: "member",
      header: "Member",
      cell: (member) => (
        <div className="flex items-center gap-2.5">
          <Avatar id={member.user_id} name={member.display_name} size={30} />
          <div className="flex min-w-0 flex-col">
            <button
              type="button"
              className="cursor-pointer self-start text-left font-medium hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                go({ member: member.user_id, group: undefined });
              }}
            >
              {member.display_name}
            </button>
            <span className="text-[12px] text-fg-muted">{member.email}</span>
          </div>
        </div>
      ),
    },
    {
      id: "org-role",
      header: "Org role",
      cell: (member) => (
        <span className={cn(member.org_role === "member" && "text-fg-secondary")}>
          {ORG_ROLE_LABELS[member.org_role]}
        </span>
      ),
    },
    {
      id: "access",
      header: "Access by instance",
      cell: (member) => <AccessCell member={member} directory={directory} />,
    },
    {
      id: "groups",
      header: "Groups",
      cell: (member) => {
        const groups = memberGroups(member);
        return groups.length === 0 ? (
          <span className="text-fg-muted">Direct</span>
        ) : (
          <span className="text-fg-secondary">{groups.map((group) => group.name).join(", ")}</span>
        );
      },
    },
    {
      id: "active",
      header: "Last active",
      cell: (member) => (
        <span className="whitespace-nowrap text-fg-secondary">
          {member.last_active_at ? formatRelative(member.last_active_at) : "Never"}
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-[300px]">
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-fg-muted"
          />
          <Input
            type="search"
            aria-label="Search name or email"
            placeholder="Search name or email"
            className="h-8 pl-8"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
        </div>
        <FilterMenu
          label="Access role"
          current={state.role}
          options={directory.allRoles.map((role) => ({ value: role.id, label: role.name }))}
          onSelect={(role) => {
            go({ role });
          }}
        />
        <FilterMenu
          label="Instance"
          current={state.instance}
          options={directory.allInstances.map((instance) => ({ value: instance.id, label: instance.slug }))}
          onSelect={(instance) => {
            go({ instance });
          }}
        />
        <FilterMenu
          label="Group"
          current={state.in_group}
          options={directory.allGroups.map((group) => ({ value: group.id, label: group.name }))}
          onSelect={(group) => {
            go({ in_group: group });
          }}
        />
        {hasFilters && (
          <Button
            variant="ghost"
            size="30"
            onClick={() => {
              setQuery("");
              go({ role: undefined, instance: undefined, in_group: undefined });
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      {chosen.length > 0 && (
        <BulkBar
          selected={chosen}
          directory={directory}
          onDone={() => {
            setSelected([]);
          }}
        />
      )}

      {members.isPending ? (
        <LoadingRows rows={4} label="Loading members" />
      ) : members.isError ? (
        <ErrorState {...describeError(members.error)} onRetry={() => void members.refetch()} />
      ) : (
        <div className="min-w-0 overflow-x-auto">
          <div className="min-w-[860px]">
            <DataTable
              label="Members"
              columns={columns}
              rows={visible}
              rowKey={(member) => member.user_id}
              selectedKey={state.member ?? ""}
              onRowClick={(member) => {
                go({ member: member.user_id, group: undefined });
              }}
              empty={
                <EmptyState title={hasFilters ? "No members match" : "No members yet"}>
                  {hasFilters ? "Try another search or clear the filters." : "Invite people to get started."}
                </EmptyState>
              }
              footer={
                <span className="mr-auto">
                  {visible.length === directory.allMembers.length
                    ? `${String(visible.length)} members`
                    : `${String(visible.length)} of ${String(directory.allMembers.length)}`}
                </span>
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}
