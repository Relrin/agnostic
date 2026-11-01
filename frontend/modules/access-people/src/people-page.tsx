import {
  accessCreateBindingMutation,
  accessDeleteBindingMutation,
  accessExplainMutation,
  accessListBindingsOptions,
  accessListBindingsQueryKey,
  accessListRolesOptions,
  describeError,
  invitationsCreateInvitationMutation,
  invitationsListInvitationsOptions,
  invitationsListInvitationsQueryKey,
  invitationsResendInvitationMutation,
  invitationsRevokeInvitationMutation,
  membersListMembersOptions,
  membersListMembersQueryKey,
  membersRemoveMemberMutation,
  membersUpdateMemberMutation,
  type BindingOut,
  type InstanceOut,
  type MemberOut,
  type RoleOut,
} from "@agnostic/api";
import { ORG_ROLE_LABELS, PermissionGate, useCan, useInstances, useMe, withQueryFn } from "@agnostic/core";
import {
  Avatar,
  Badge,
  Button,
  Callout,
  CodeBlock,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  EnvBadge,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  PageIntro,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, UserPlus } from "lucide-react";
import { useState, type SubmitEvent } from "react";

type OrgRole = MemberOut["org_role"];
const ALL = "__all__";

function instanceLabel(instances: readonly InstanceOut[], id: string | null): string {
  if (id === null) return "all";
  return instances.find((instance) => instance.id === id)?.slug ?? id;
}

function bindingLabel(binding: BindingOut, roles: readonly RoleOut[]): string {
  const role = roles.find((item) => item.id === binding.role_id);
  return role ? role.name : binding.scopes.join(", ");
}

function useDirectory() {
  const members = useQuery(withQueryFn(membersListMembersOptions()));
  const bindings = useQuery(withQueryFn(accessListBindingsOptions()));
  const roles = useQuery(withQueryFn(accessListRolesOptions()));
  const instances = useInstances();
  return { members, bindings, roles, instances };
}

function AccessChips({
  member,
  bindings,
  roles,
  instances,
}: {
  member: MemberOut;
  bindings: readonly BindingOut[];
  roles: readonly RoleOut[];
  instances: readonly InstanceOut[];
}) {
  const mine = bindings.filter((binding) => binding.principal_id === member.user_id);
  const chips = [
    ...(member.org_role === "member" ? [] : [{ key: "full", label: "Full access", where: "all" }]),
    ...mine.map((binding) => ({
      key: binding.id,
      label: bindingLabel(binding, roles),
      where: instanceLabel(instances, binding.instance_id),
    })),
  ];
  if (chips.length === 0) return <span className="text-[12.5px] text-fg-muted">No access</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex h-[22px] items-center gap-1.5 rounded-control border border-border-strong px-1.5 text-[12px]"
        >
          {chip.label}
          <span className="font-mono text-[11px] text-fg-muted">{chip.where}</span>
        </span>
      ))}
    </div>
  );
}

function CheckPermission({ member, instances }: { member: MemberOut; instances: readonly InstanceOut[] }) {
  const [scope, setScope] = useState("");
  const [instance, setInstance] = useState(instances[0]?.id ?? ALL);
  const explain = useMutation(accessExplainMutation());
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    explain.mutate({
      body: { user_id: member.user_id, scope: scope.trim(), instance: instance === ALL ? null : instance },
    });
  };
  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <h3 className="text-[13.5px] font-semibold">Check a permission</h3>
      <div className="flex gap-2">
        <Input
          aria-label={`Scope to check for ${member.display_name}`}
          mono
          placeholder="components:write"
          value={scope}
          onChange={(event) => {
            setScope(event.target.value);
          }}
        />
        <Select value={instance} onValueChange={setInstance}>
          <SelectTrigger aria-label="Instance" className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {instances.map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.slug}
              </SelectItem>
            ))}
            <SelectItem value={ALL}>Org-wide</SelectItem>
          </SelectContent>
        </Select>
        <Button type="submit" size="34" disabled={!scope.trim() || explain.isPending}>
          Check
        </Button>
      </div>
      {explain.data && (
        <div className="flex gap-2 rounded-tile border border-border bg-inset px-3 py-2.5 text-[13px]">
          {explain.data.allowed ? (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-label="Allowed" />
          ) : (
            <CircleX className="mt-0.5 size-4 shrink-0 text-danger" aria-label="Not allowed" />
          )}
          <span>
            <strong>{explain.data.allowed ? "Yes. " : "No. "}</strong>
            {explain.data.explanation}
          </span>
        </div>
      )}
      {explain.error && <Callout tone="danger">{describeError(explain.error).reason}</Callout>}
    </form>
  );
}

function MemberAside({
  member,
  bindings,
  roles,
  instances,
  onClose,
}: {
  member: MemberOut;
  bindings: readonly BindingOut[];
  roles: readonly RoleOut[];
  instances: readonly InstanceOut[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const canWrite = useCan("org:members:write").allowed === true;
  const canBind = useCan("org:roles:write").allowed === true;
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: membersListMembersQueryKey() });
    await queryClient.invalidateQueries({ queryKey: accessListBindingsQueryKey() });
  };
  const updateRole = useMutation({ ...membersUpdateMemberMutation(), onSuccess: refresh });
  const remove = useMutation({
    ...membersRemoveMemberMutation(),
    onSuccess: async () => {
      await refresh();
      onClose();
    },
  });
  const addBinding = useMutation({ ...accessCreateBindingMutation(), onSuccess: refresh });
  const deleteBinding = useMutation({ ...accessDeleteBindingMutation(), onSuccess: refresh });
  const [newInstance, setNewInstance] = useState(instances[0]?.id ?? ALL);
  const [newRole, setNewRole] = useState(
    roles.find((role) => role.slug === "viewer")?.id ?? roles[0]?.id ?? "",
  );
  const mine = bindings.filter((binding) => binding.principal_id === member.user_id);
  const error = updateRole.error ?? remove.error ?? addBinding.error ?? deleteBinding.error;

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent aria-describedby={undefined} className="w-[min(520px,100%)] overflow-y-auto">
        <div className="flex items-center gap-3 pr-8">
          <Avatar id={member.user_id} name={member.display_name} size={40} />
          <div className="flex min-w-0 flex-col">
            <SheetTitle className="text-[16px] font-semibold">{member.display_name}</SheetTitle>
            <SheetDescription className="text-[12.5px] text-fg-secondary">
              {member.email} · joined {new Date(member.joined_at).toLocaleDateString()} via{" "}
              {member.joined_via}
            </SheetDescription>
          </div>
        </div>

        <Field label="Org role">
          {({ id }) => (
            <Select
              value={member.org_role}
              disabled={!canWrite || updateRole.isPending}
              onValueChange={(value) => {
                updateRole.mutate({
                  path: { user_id: member.user_id },
                  body: { org_role: value as OrgRole },
                });
              }}
            >
              <SelectTrigger id={id}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(["member", "administrator", "owner"] as const).map((role) => (
                  <SelectItem key={role} value={role}>
                    {ORG_ROLE_LABELS[role]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>

        <section className="flex flex-col gap-2">
          <h3 className="text-[13.5px] font-semibold">Access by instance</h3>
          {member.org_role !== "member" && (
            <p className="text-[12.5px] text-fg-secondary">
              {ORG_ROLE_LABELS[member.org_role]}s have Full access on every instance, unless the org requires
              explicit bindings.
            </p>
          )}
          <ul className="flex flex-col divide-y divide-divider-row rounded-tile border border-border">
            {instances.map((instance) => {
              const here = mine.filter(
                (binding) => binding.instance_id === instance.id || binding.instance_id === null,
              );
              return (
                <li key={instance.id} className="flex flex-col gap-1.5 px-3 py-2.5">
                  <div className="flex items-center gap-2 text-[13px]">
                    <span className="font-mono">{instance.slug}</span>
                    <EnvBadge env={instance.env_tag} />
                  </div>
                  {here.length === 0 ? (
                    <span className="text-[12.5px] text-fg-muted">No direct roles</span>
                  ) : (
                    here.map((binding) => (
                      <div key={binding.id} className="flex items-center gap-2 text-[13px]">
                        <span className="font-medium">{bindingLabel(binding, roles)}</span>
                        {binding.instance_id === null && <Badge tone="outline">all instances</Badge>}
                        {binding.expires_at && (
                          <span className="text-[12px] text-fg-muted">
                            until {new Date(binding.expires_at).toLocaleDateString()}
                          </span>
                        )}
                        {canBind && (
                          <Button
                            className="ml-auto"
                            size="28"
                            variant="destructive-text"
                            onClick={() => {
                              deleteBinding.mutate({ path: { binding_id: binding.id } });
                            }}
                          >
                            Remove
                          </Button>
                        )}
                      </div>
                    ))
                  )}
                </li>
              );
            })}
          </ul>
          {canBind && (
            <div className="flex flex-wrap items-end gap-2">
              <Select value={newInstance} onValueChange={setNewInstance}>
                <SelectTrigger aria-label="Instance for the new role" className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {instances.map((instance) => (
                    <SelectItem key={instance.id} value={instance.id}>
                      {instance.slug}
                    </SelectItem>
                  ))}
                  <SelectItem value={ALL}>All instances</SelectItem>
                </SelectContent>
              </Select>
              <Select value={newRole} onValueChange={setNewRole}>
                <SelectTrigger aria-label="Role" className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roles.map((role) => (
                    <SelectItem key={role.id} value={role.id}>
                      {role.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="dashed-add"
                disabled={!newRole || addBinding.isPending}
                onClick={() => {
                  addBinding.mutate({
                    body: {
                      user_id: member.user_id,
                      role_id: newRole,
                      instance: newInstance === ALL ? null : newInstance,
                    },
                  });
                }}
              >
                Add direct role
              </Button>
            </div>
          )}
        </section>

        <CheckPermission member={member} instances={instances} />
        {error && <Callout tone="danger">{describeError(error).reason}</Callout>}

        {canWrite && (
          <div className="mt-auto flex justify-start border-t border-border-subtle pt-4">
            <Button
              variant="destructive-text"
              disabled={remove.isPending}
              onClick={() => {
                remove.mutate({ path: { user_id: member.user_id } });
              }}
            >
              Remove from org
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

type DraftBinding = { key: number; instance: string; role: string };

function InviteDialog({
  open,
  onOpenChange,
  roles,
  instances,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roles: readonly RoleOut[];
  instances: readonly InstanceOut[];
}) {
  const queryClient = useQueryClient();
  const me = useMe();
  const [email, setEmail] = useState("");
  const [orgRole, setOrgRole] = useState<OrgRole>("member");
  const [drafts, setDrafts] = useState<DraftBinding[]>([]);
  const [endsAt, setEndsAt] = useState("");
  const invite = useMutation({
    ...invitationsCreateInvitationMutation(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: invitationsListInvitationsQueryKey() });
    },
  });
  const reset = () => {
    setEmail("");
    setOrgRole("member");
    setDrafts([]);
    setEndsAt("");
    invite.reset();
  };
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    invite.mutate({
      body: {
        email,
        org_role: orgRole,
        bindings: drafts.map((draft) => ({
          role_id: draft.role,
          instance_id: draft.instance === ALL ? null : draft.instance,
        })),
        access_ends_at: endsAt ? new Date(`${endsAt}T23:59:59`).toISOString() : null,
      },
    });
  };
  const orgRoles: OrgRole[] =
    me.data?.org_role === "owner" ? ["member", "administrator", "owner"] : ["member", "administrator"];

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite people</DialogTitle>
          <DialogDescription>They get an email link; you can also copy it.</DialogDescription>
        </DialogHeader>
        {invite.data ? (
          <div className="flex flex-col gap-3">
            <Callout tone="insight" title={`Invited ${invite.data.invitation.email}`}>
              The link works once and expires on{" "}
              {new Date(invite.data.invitation.expires_at).toLocaleDateString()}.
            </Callout>
            <CodeBlock title="Invitation link" code={invite.data.accept_url} />
            <DialogFooter>
              <Button onClick={reset}>Invite someone else</Button>
              <Button
                variant="primary"
                onClick={() => {
                  reset();
                  onOpenChange(false);
                }}
              >
                Done
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-4">
            <Field label="Email">
              {({ id }) => (
                <Input
                  id={id}
                  type="email"
                  required
                  value={email}
                  onChange={(event) => {
                    setEmail(event.target.value);
                  }}
                />
              )}
            </Field>
            <Field label="Org role">
              {({ id }) => (
                <Select
                  value={orgRole}
                  onValueChange={(value) => {
                    setOrgRole(value as OrgRole);
                  }}
                >
                  <SelectTrigger id={id}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {orgRoles.map((role) => (
                      <SelectItem key={role} value={role}>
                        {ORG_ROLE_LABELS[role]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
            <div className="flex flex-col gap-2">
              <span className="text-[13px] font-medium text-fg-secondary">Initial access</span>
              {drafts.map((draft) => (
                <div key={draft.key} className="flex gap-2">
                  <Select
                    value={draft.instance}
                    onValueChange={(value) => {
                      setDrafts(
                        drafts.map((item) => (item.key === draft.key ? { ...item, instance: value } : item)),
                      );
                    }}
                  >
                    <SelectTrigger aria-label="Instance" className="flex-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {instances.map((instance) => (
                        <SelectItem key={instance.id} value={instance.id}>
                          {instance.slug}
                        </SelectItem>
                      ))}
                      <SelectItem value={ALL}>All instances</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select
                    value={draft.role}
                    onValueChange={(value) => {
                      setDrafts(
                        drafts.map((item) => (item.key === draft.key ? { ...item, role: value } : item)),
                      );
                    }}
                  >
                    <SelectTrigger aria-label="Role" className="flex-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {roles.map((role) => (
                        <SelectItem key={role.id} value={role.id}>
                          {role.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      setDrafts(drafts.filter((item) => item.key !== draft.key));
                    }}
                  >
                    Remove
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="dashed-add"
                className="self-start"
                onClick={() => {
                  setDrafts([
                    ...drafts,
                    {
                      key: Date.now(),
                      instance: instances[0]?.id ?? ALL,
                      role: roles.find((role) => role.slug === "viewer")?.id ?? roles[0]?.id ?? "",
                    },
                  ]);
                }}
              >
                Add role binding
              </Button>
            </div>
            <Field
              label="Access ends (optional)"
              hint="Bindings from this invitation expire at the end of that day."
            >
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  type="date"
                  aria-describedby={describedBy}
                  value={endsAt}
                  onChange={(event) => {
                    setEndsAt(event.target.value);
                  }}
                />
              )}
            </Field>
            {invite.error && <Callout tone="danger">{describeError(invite.error).reason}</Callout>}
            <DialogFooter>
              <Button type="submit" variant="primary" disabled={invite.isPending}>
                Send invitation
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Invitations({ roles, instances }: { roles: readonly RoleOut[]; instances: readonly InstanceOut[] }) {
  const queryClient = useQueryClient();
  const invitations = useQuery(withQueryFn(invitationsListInvitationsOptions()));
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: invitationsListInvitationsQueryKey() });
  };
  const resend = useMutation({ ...invitationsResendInvitationMutation(), onSuccess: refresh });
  const revoke = useMutation({ ...invitationsRevokeInvitationMutation(), onSuccess: refresh });
  if (invitations.isPending) return <LoadingRows rows={2} label="Loading invitations" />;
  if (invitations.isError) return <ErrorState reason={describeError(invitations.error).reason} />;
  if (invitations.data.length === 0) {
    return (
      <EmptyState title="No pending invitations">
        Invitations you send appear here until they're accepted.
      </EmptyState>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col divide-y divide-divider-row rounded-card border border-border bg-surface">
        {invitations.data.map((invitation) => (
          <li key={invitation.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-[13.5px] font-medium">{invitation.email}</span>
              <span className="text-[12px] text-fg-muted">
                {ORG_ROLE_LABELS[invitation.org_role]} · expires{" "}
                {new Date(invitation.expires_at).toLocaleDateString()}
                {invitation.bindings.length > 0 &&
                  ` · ${invitation.bindings
                    .map((binding) => {
                      const role = roles.find((item) => item.id === binding.role_id)?.name ?? binding.role_id;
                      return `${role} on ${instanceLabel(instances, binding.instance_id)}`;
                    })
                    .join(", ")}`}
              </span>
            </div>
            <PermissionGate scope="org:members:write">
              <Button
                size="30"
                variant="outline"
                onClick={() => {
                  resend.mutate({ path: { invitation_id: invitation.id } });
                }}
              >
                Resend
              </Button>
              <Button
                size="30"
                variant="destructive-text"
                onClick={() => {
                  revoke.mutate({ path: { invitation_id: invitation.id } });
                }}
              >
                Revoke
              </Button>
            </PermissionGate>
          </li>
        ))}
      </ul>
      {resend.data && (
        <CodeBlock title={`New link for ${resend.data.invitation.email}`} code={resend.data.accept_url} />
      )}
    </div>
  );
}

/** `/access/people`: members with their org roles and access per instance, and invitations. */
export function PeoplePage() {
  const { members, bindings, roles, instances } = useDirectory();
  const [selected, setSelected] = useState<string | undefined>(undefined);
  const [inviting, setInviting] = useState(false);
  const [query, setQuery] = useState("");
  const allRoles = roles.data ?? [];
  const allInstances = instances.data ?? [];
  const allBindings = bindings.data ?? [];
  const visible = (members.data ?? []).filter((member) =>
    `${member.display_name} ${member.email}`.toLowerCase().includes(query.toLowerCase()),
  );
  const current = members.data?.find((member) => member.user_id === selected);

  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro
        title="People"
        actions={
          <PermissionGate scope="org:members:write">
            <Button
              variant="primary"
              onClick={() => {
                setInviting(true);
              }}
            >
              <UserPlus aria-hidden />
              Invite people
            </Button>
          </PermissionGate>
        }
      >
        Org roles govern the control plane; access roles, bound per instance, govern what people can do on
        each AgentOS. Changes apply on the next request.
      </PageIntro>
      <Tabs defaultValue="members">
        <TabsList aria-label="People">
          <TabsTrigger value="members">
            Members {members.data ? `· ${String(members.data.length)}` : ""}
          </TabsTrigger>
          <TabsTrigger value="invitations">Invitations</TabsTrigger>
        </TabsList>
        <TabsContent value="members" className="flex flex-col gap-3 pt-4">
          <Input
            aria-label="Search name or email"
            placeholder="Search name or email"
            className="max-w-[300px]"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
          {members.isPending ? (
            <LoadingRows rows={4} label="Loading members" />
          ) : members.isError ? (
            <ErrorState reason={describeError(members.error).reason} onRetry={() => void members.refetch()} />
          ) : (
            <div className="overflow-x-auto rounded-card border border-border">
              <table className="w-full min-w-[800px] text-left text-[13px]">
                <thead className="border-b border-border-subtle text-[11.5px] tracking-[0.06em] text-fg-muted uppercase">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Member</th>
                    <th className="px-4 py-2.5 font-medium">Org role</th>
                    <th className="px-4 py-2.5 font-medium">Access by instance</th>
                    <th className="px-4 py-2.5 font-medium">Last active</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-divider-row">
                  {visible.map((member) => (
                    <tr key={member.user_id} className="bg-surface">
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2.5">
                          <Avatar id={member.user_id} name={member.display_name} size={30} />
                          <div className="flex min-w-0 flex-col">
                            <button
                              type="button"
                              className="cursor-pointer text-left font-medium hover:underline"
                              onClick={() => {
                                setSelected(member.user_id);
                              }}
                            >
                              {member.display_name}
                            </button>
                            <span className="text-[12px] text-fg-muted">{member.email}</span>
                          </div>
                        </div>
                      </td>
                      <td
                        className={
                          member.org_role === "member" ? "px-4 py-2.5 text-fg-secondary" : "px-4 py-2.5"
                        }
                      >
                        {ORG_ROLE_LABELS[member.org_role]}
                      </td>
                      <td className="px-4 py-2.5">
                        <AccessChips
                          member={member}
                          bindings={allBindings}
                          roles={allRoles}
                          instances={allInstances}
                        />
                      </td>
                      <td className="px-4 py-2.5 text-fg-secondary">
                        {member.last_active_at ? new Date(member.last_active_at).toLocaleString() : "Never"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </TabsContent>
        <TabsContent value="invitations" className="pt-4">
          <Invitations roles={allRoles} instances={allInstances} />
        </TabsContent>
      </Tabs>
      {current && (
        <MemberAside
          member={current}
          bindings={allBindings}
          roles={allRoles}
          instances={allInstances}
          onClose={() => {
            setSelected(undefined);
          }}
        />
      )}
      <InviteDialog open={inviting} onOpenChange={setInviting} roles={allRoles} instances={allInstances} />
    </div>
  );
}
