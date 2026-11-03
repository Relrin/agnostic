// URL state, shared queries and wording for People & groups: which tab and aside are open, the directory every tab
// reads (members, bindings, roles, groups, instances), and each member's effective access by instance.
import {
  accessListBindingsOptions,
  accessListRolesOptions,
  directoryListGroupsOptions,
  membersListMembersOptions,
  type BindingOut,
  type GroupOut,
  type InstanceOut,
  type MemberOut,
  type RoleOut,
} from "@agnostic/api";
import { STALE_TIME, toDate, useInstances, useOrg, withQueryFn } from "@agnostic/core";
import type { QueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";

export const PATH = "/access/people";
/** Select value for "All instances" (bindings with `instance: null`). */
export const ALL = "__all__";

export const TABS = ["members", "groups", "invitations", "requests"] as const;
export type PeopleTab = (typeof TABS)[number];

export type PeopleSearch = {
  tab: PeopleTab;
  /** The member aside (`usr_…`). */
  member?: string | undefined;
  /** The group aside (`grp_…`). */
  group?: string | undefined;
  /** Members filters: an access role id, an instance id and a group id. */
  role?: string | undefined;
  instance?: string | undefined;
  in_group?: string | undefined;
  /** Requests tab: pending only (default) or every status. */
  requests?: "all" | undefined;
};

export function readSearch(search: Record<string, unknown>): PeopleSearch {
  const text = (key: string) => {
    const value = search[key];
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
  };
  const tab = text("tab");
  return {
    tab: TABS.includes(tab as PeopleTab) ? (tab as PeopleTab) : "members",
    member: text("member"),
    group: text("group"),
    role: text("role"),
    instance: text("instance"),
    in_group: text("in_group"),
    requests: text("requests") === "all" ? "all" : undefined,
  };
}

/** Search params as they go in the URL: defaults and empty values left out. */
export function toSearch(state: PeopleSearch): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(state)) {
    if (value === undefined || value === "") continue;
    if (key === "tab" && value === "members") continue;
    out[key] = value;
  }
  return out;
}

/** The page's URL state and a way to change part of it. */
export function usePeopleSearch(): [PeopleSearch, (next: Partial<PeopleSearch>) => void] {
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const state = readSearch(search);
  const go = (next: Partial<PeopleSearch>) => {
    void navigate({ to: PATH, search: toSearch({ ...state, ...next }) });
  };
  return [state, go];
}

/** Everything the tabs share; each list is `[]` until it loads. */
export function useDirectory() {
  const members = useQuery({ ...withQueryFn(membersListMembersOptions()), staleTime: STALE_TIME.list });
  const bindings = useQuery({ ...withQueryFn(accessListBindingsOptions()), staleTime: STALE_TIME.list });
  const roles = useQuery({ ...withQueryFn(accessListRolesOptions()), staleTime: STALE_TIME.list });
  const groups = useQuery({
    ...withQueryFn(directoryListGroupsOptions()),
    staleTime: STALE_TIME.list,
    retry: false,
  });
  const instances = useInstances();
  const org = useOrg();
  return {
    members,
    bindings,
    groupsQuery: groups,
    allMembers: members.data ?? [],
    allBindings: bindings.data ?? [],
    allRoles: roles.data ?? [],
    allGroups: groups.data ?? [],
    allInstances: instances.data ?? [],
    /** Owners and Administrators have Full access everywhere unless the org requires explicit bindings. */
    explicitOnly: org.data?.settings.require_explicit_bindings ?? false,
  };
}

export type Directory = ReturnType<typeof useDirectory>;

/** After a change to members, groups or bindings: every list that shows them. */
export async function refreshDirectory(client: QueryClient): Promise<void> {
  await Promise.all(
    [
      "membersListMembers",
      "accessListBindings",
      "directoryListGroups",
      "directoryGetGroup",
      "invitationsListInvitations",
      "accessListRequests",
    ].map((id) => client.invalidateQueries({ queryKey: [{ _id: id }] })),
  );
}

export function findInstance(instances: readonly InstanceOut[], id: string | null): InstanceOut | undefined {
  return id === null ? undefined : instances.find((item) => item.id === id || item.slug === id);
}

export function instanceSlug(instances: readonly InstanceOut[], id: string | null): string {
  if (id === null) return "all instances";
  return findInstance(instances, id)?.slug ?? id;
}

/** "Operator", or the scopes of a granular grant ("agents:billing-agent:run"). */
export function grantName(
  binding: Pick<BindingOut, "role_id" | "scopes">,
  roles: readonly RoleOut[],
): string {
  const role = binding.role_id ? roles.find((item) => item.id === binding.role_id) : undefined;
  if (role) return role.name;
  if (binding.role_id) return binding.role_id;
  if (binding.scopes.length === 1) return binding.scopes[0] ?? "";
  return `${String(binding.scopes.length)} scopes`;
}

export function roleColor(roleId: string | null, roles: readonly RoleOut[]): string | null {
  return roles.find((item) => item.id === roleId)?.color ?? null;
}

const DAY_MONTH = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** "30 Nov". */
export function formatDay(value: string | null | undefined): string {
  const date = toDate(value);
  return date ? DAY_MONTH.format(date) : "—";
}

/** "ends 30 Nov" for a binding that expires. */
export function endsLabel(value: string | null | undefined): string | null {
  return value ? `ends ${formatDay(value)}` : null;
}

/** One line of someone's effective access: Full access, a direct grant, or a grant through a group. */
export type Grant = {
  key: string;
  name: string;
  color: string | null;
  /** `null`: every instance. */
  instanceId: string | null;
  via: { id: string; name: string } | null;
  binding: BindingOut | null;
};

export function memberGroups(member: MemberOut): { id: string; name: string }[] {
  return member.groups ?? [];
}

export function hasFullAccess(member: MemberOut, explicitOnly: boolean): boolean {
  return member.org_role !== "member" && !explicitOnly;
}

/** The union of direct bindings and bindings of the groups the member is in. */
export function effectiveGrants(
  member: MemberOut,
  bindings: readonly BindingOut[],
  roles: readonly RoleOut[],
  explicitOnly: boolean,
): Grant[] {
  const groups = memberGroups(member);
  const grants: Grant[] = hasFullAccess(member, explicitOnly)
    ? [{ key: "full", name: "Full access", color: null, instanceId: null, via: null, binding: null }]
    : [];
  for (const binding of bindings) {
    const direct = binding.principal_kind === "user" && binding.principal_id === member.user_id;
    const via =
      binding.principal_kind === "group"
        ? groups.find((group) => group.id === binding.principal_id)
        : undefined;
    if (!direct && !via) continue;
    grants.push({
      key: binding.id,
      name: grantName(binding, roles),
      color: roleColor(binding.role_id, roles),
      instanceId: binding.instance_id,
      via: via ?? null,
      binding,
    });
  }
  return grants;
}

/** Grants that apply on one instance (including those on every instance). */
export function grantsOn(grants: readonly Grant[], instanceId: string): Grant[] {
  return grants.filter((grant) => grant.instanceId === null || grant.instanceId === instanceId);
}

export function groupBindings(groupId: string, bindings: readonly BindingOut[]): BindingOut[] {
  return bindings.filter((item) => item.principal_kind === "group" && item.principal_id === groupId);
}

/** "SCIM · support-ai" for synced groups, "Manual" otherwise. */
export function sourceLabel(group: Pick<GroupOut, "synced" | "sync_label">): string {
  return group.synced ? group.sync_label || "Synced" : "Manual";
}

export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

export function memberName(members: readonly MemberOut[], id: string): string {
  return members.find((member) => member.user_id === id)?.display_name ?? id;
}

/** Days ahead as a date input value ("2026-11-30") → the end of that day in ISO. */
export function endOfDay(value: string): string | null {
  return value ? new Date(`${value}T23:59:59`).toISOString() : null;
}
