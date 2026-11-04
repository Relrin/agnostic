// Roles & permissions: org roles (built in, read-only) and access roles (a permission matrix per role) in a nav,
// the selected role's editor, and what the draft does to token scopes. `?role=<id>` selects.
import {
  accessListRolesOptions,
  accessListScopesOptions,
  describeError,
  membersListMembersOptions,
  type MemberOut,
  type RoleOut,
} from "@agnostic/api";
import { ORG_ROLE_LABELS, STALE_TIME, useCan, useInstances, withQueryFn } from "@agnostic/core";
import { Avatar, EmptyState, ErrorState, LoadingRows, PageIntro, cn } from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Lock } from "lucide-react";
import type { ReactNode } from "react";

import { NewRoleDialog } from "./role-dialogs";
import { RoleEditor } from "./role-editor";
import { ORG_ROLE_IDS, ORG_ROLE_SCOPES, ORG_ROLE_SUMMARY, plural, type OrgRoleId } from "./roles-api";

const PATH = "/access/roles";

function isOrgRole(value: string | undefined): value is OrgRoleId {
  return (ORG_ROLE_IDS as readonly (string | undefined)[]).includes(value);
}

function NavLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="px-2 pt-3 pb-1 font-mono text-[10.5px] font-medium tracking-[0.08em] text-fg-muted uppercase">
      {children}
    </h2>
  );
}

function NavItem({
  id,
  selected,
  icon,
  name,
  count,
  countLabel,
}: {
  id: string;
  selected: boolean;
  icon: ReactNode;
  name: string;
  count: number | undefined;
  countLabel: string;
}) {
  return (
    <li>
      <Link
        to={PATH}
        search={{ role: id }}
        aria-current={selected ? "page" : undefined}
        aria-label={count === undefined ? name : `${name}, ${String(count)} ${countLabel}`}
        className={cn(
          "flex h-7 items-center gap-2 rounded-control px-2 text-[13px] text-fg-secondary hover:bg-surface-hover hover:text-fg",
          selected && "bg-surface-hover text-fg-active",
        )}
      >
        {icon}
        <span className="min-w-0 flex-1 truncate">{name}</span>
        {count !== undefined && (
          <span aria-hidden className="font-mono text-[11.5px] text-fg-muted tabular-nums">
            {count}
          </span>
        )}
      </Link>
    </li>
  );
}

function RolesNav({
  roles,
  members,
  selected,
  canWrite,
  onCreated,
}: {
  roles: readonly RoleOut[];
  members: readonly MemberOut[] | undefined;
  selected: string | undefined;
  canWrite: boolean;
  onCreated: (id: string) => void;
}) {
  const orgCount = (id: OrgRoleId) => members?.filter((member) => member.org_role === id).length;
  return (
    <nav
      aria-label="Roles"
      className="flex w-full shrink-0 flex-col gap-0.5 overflow-y-auto border-border-subtle p-3 lg:w-[230px] lg:border-r"
    >
      <NavLabel>Org roles</NavLabel>
      <ul className="flex flex-col gap-0.5">
        {ORG_ROLE_IDS.map((id) => (
          <NavItem
            key={id}
            id={id}
            selected={selected === id}
            icon={<Lock aria-hidden className="size-3.5 shrink-0 text-fg-muted" />}
            name={ORG_ROLE_LABELS[id]}
            count={orgCount(id)}
            countLabel={orgCount(id) === 1 ? "member" : "members"}
          />
        ))}
      </ul>
      <NavLabel>Access roles</NavLabel>
      <ul className="flex flex-col gap-0.5">
        {roles.map((role) => (
          <NavItem
            key={role.id}
            id={role.id}
            selected={selected === role.id}
            icon={
              <span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: role.color }}
              />
            }
            name={role.name}
            count={role.people}
            countLabel={role.people === 1 ? "person" : "people"}
          />
        ))}
      </ul>
      {canWrite && (
        <div className="pt-2">
          <NewRoleDialog roles={roles} onCreated={onCreated} />
        </div>
      )}
      <p className="px-2 pt-4 text-[12px] text-fg-muted">
        Org roles are built in and cover the control plane. Access roles are yours and apply per AgentOS
        instance.
      </p>
    </nav>
  );
}

/** Owner, Administrator, Member: what they carry and who has them; changed per person in People & groups. */
function OrgRolePanel({ id, members }: { id: OrgRoleId; members: readonly MemberOut[] | undefined }) {
  const holders = members?.filter((member) => member.org_role === id) ?? [];
  const scopes = ORG_ROLE_SCOPES[id];
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-5 overflow-y-auto px-6 pt-5 pb-8">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-2">
          <Lock aria-hidden className="size-4 text-fg-muted" />
          <h2 className="text-[20px] font-semibold">{ORG_ROLE_LABELS[id]}</h2>
        </div>
        <p className="max-w-[640px] text-[13.5px] text-fg-secondary">{ORG_ROLE_SUMMARY[id]}</p>
        <p className="text-[12.5px] text-fg-muted">
          Built in and read-only. Change someone&apos;s org role in{" "}
          <Link to="/access/people" className="text-info hover:underline">
            People & groups
          </Link>
          .
        </p>
      </div>
      {scopes && (
        <section aria-label="Control-plane scopes" className="flex flex-col gap-2">
          <h3 className="text-[13.5px] font-semibold">Control-plane scopes</h3>
          <div className="flex flex-wrap gap-1.5">
            {scopes.map((scope) => (
              <code
                key={scope}
                className="rounded-control border border-border bg-inset px-1.5 py-0.5 font-mono text-[12px]"
              >
                {scope}
              </code>
            ))}
          </div>
        </section>
      )}
      <section aria-label="Members" className="flex flex-col gap-2">
        <h3 className="text-[13.5px] font-semibold">{plural(holders.length, "member")}</h3>
        {holders.length === 0 ? (
          <p className="text-[13px] text-fg-muted">Nobody has this org role.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-divider-row rounded-tile border border-border">
            {holders.map((member) => (
              <li key={member.user_id} className="flex items-center gap-2.5 px-3 py-2 text-[13px]">
                <Avatar id={member.user_id} name={member.display_name} size={24} />
                <span className="font-medium">{member.display_name}</span>
                <span className="truncate text-fg-muted">{member.email}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** `/access/roles?role=`. */
export function RolesPage() {
  const search = useSearch({ strict: false }) as unknown as Record<string, unknown>;
  const navigate = useNavigate();
  const canWrite = useCan("org:roles:write").allowed === true;
  const roles = useQuery(withQueryFn(accessListRolesOptions()));
  const catalog = useQuery({ ...withQueryFn(accessListScopesOptions()), staleTime: STALE_TIME.config });
  const members = useQuery(withQueryFn(membersListMembersOptions()));
  const instances = useInstances();

  const requested = typeof search.role === "string" && search.role ? search.role : undefined;
  const select = (id: string | undefined) => {
    void navigate({ to: PATH, search: id ? { role: id } : {} });
  };
  const list = roles.data ?? [];
  const role = list.find((item) => item.id === requested || item.slug === requested);
  const selected = isOrgRole(requested) ? requested : (role?.id ?? (requested ? undefined : list[0]?.id));
  const current = role ?? (requested ? undefined : list[0]);

  let body: ReactNode;
  if (roles.isError || catalog.isError) {
    const error = roles.error ?? catalog.error;
    body = (
      <div className="flex-1 p-6">
        <ErrorState
          {...describeError(error)}
          onRetry={() => {
            void roles.refetch();
            void catalog.refetch();
          }}
        />
      </div>
    );
  } else if (isOrgRole(requested)) {
    body = <OrgRolePanel id={requested} members={members.data} />;
  } else if (roles.isPending || catalog.isPending || instances.isPending) {
    body = (
      <div className="flex-1 p-6">
        <LoadingRows label="Loading roles" />
      </div>
    );
  } else if (!current) {
    body = (
      <div className="flex-1 p-6">
        <EmptyState title={requested ? "There is no such role" : "No access roles yet"}>
          {requested
            ? "It may have been deleted. Pick a role on the left."
            : "Create one to grant scopes on AgentOS instances."}
        </EmptyState>
      </div>
    );
  } else {
    body = (
      <RoleEditor
        key={current.id}
        role={current}
        catalog={catalog.data}
        instances={instances.data ?? []}
        onSelect={select}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border-subtle px-6 pt-5 pb-4">
        <PageIntro title="Roles & permissions">
          Access roles grant AgentOS scopes on the instances they are bound on; saving a role updates everyone
          holding it on their next request.
        </PageIntro>
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
        <RolesNav
          roles={list}
          members={members.data}
          selected={selected}
          canWrite={canWrite}
          onCreated={select}
        />
        {body}
      </div>
    </div>
  );
}
