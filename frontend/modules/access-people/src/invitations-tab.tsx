// Invitations: pending invitations with the access they carry (roles per instance, groups, when access ends), resend,
// a new link to share, revoke; and the invite dialog (send the link by email, or only create it).
import {
  describeError,
  invitationsCreateInvitationMutation,
  invitationsListInvitationsOptions,
  invitationsRenewInvitationLinkMutation,
  invitationsResendInvitationMutation,
  invitationsRevokeInvitationMutation,
  type InvitationOut,
  type IssuedInvitationOut,
  type MemberOut,
} from "@agnostic/api";
import {
  ORG_ROLE_LABELS,
  PermissionGate,
  formatDate,
  formatRelative,
  useMe,
  useOrg,
  withQueryFn,
} from "@agnostic/core";
import {
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
  ErrorState,
  Field,
  Input,
  LoadingRows,
  RadioCards,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { ConfirmDialog } from "./confirm-dialog";
import {
  ALL,
  endOfDay,
  formatDay,
  instanceSlug,
  memberName,
  refreshDirectory,
  type Directory,
} from "./people-api";

type OrgRole = MemberOut["org_role"];
type Delivery = "email" | "link";

const DELIVERY_OPTIONS = [
  { value: "email", label: "Send by email", description: "They get the link by email; you can copy it too." },
  { value: "link", label: "Create link only", description: "No email: share the link yourself." },
] as const;

export function useInvitations() {
  return useQuery(withQueryFn(invitationsListInvitationsOptions()));
}

/** Whether invitations can go out by email here (SMTP configured). */
function useEmailDelivery(): boolean {
  return useOrg().data?.email_delivery ?? false;
}

/** The link just issued, and what happened to the email. Only the link's hash is stored: it's shown once. */
function IssuedLink({ issued, emailRequested }: { issued: IssuedInvitationOut; emailRequested: boolean }) {
  const { email, expires_at: expiresAt } = issued.invitation;
  const expiry = `It works once and expires on ${formatDate(expiresAt)}.`;
  return (
    <div className="flex flex-col gap-3">
      {issued.email_sent ? (
        <Callout tone="insight" title={`Invited ${email}`}>
          We emailed them the link. {expiry} You can also share it yourself.
        </Callout>
      ) : emailRequested ? (
        <Callout tone="warning" title="The email didn't go out">
          Share the link with {email} yourself. {expiry}
        </Callout>
      ) : (
        <Callout tone="insight" title={`Invitation link for ${email}`}>
          Share it with them yourself; it isn't shown again. {expiry}
        </Callout>
      )}
      <CodeBlock title="Invitation link" code={issued.accept_url} />
    </div>
  );
}

/** "Operator on prod-agentos · via Billing ops · access ends 30 Nov". */
export function accessSummary(invitation: InvitationOut, directory: Directory): string {
  const parts = invitation.bindings.map((binding) => {
    const role = directory.allRoles.find((item) => item.id === binding.role_id)?.name ?? binding.role_id;
    return `${role} on ${instanceSlug(directory.allInstances, binding.instance_id)}`;
  });
  const groups = (invitation.group_ids ?? []).map(
    (id) => directory.allGroups.find((group) => group.id === id)?.name ?? id,
  );
  if (groups.length > 0) parts.push(`joins ${groups.join(", ")}`);
  if (invitation.access_ends_at) parts.push(`access ends ${formatDay(invitation.access_ends_at)}`);
  return parts.length > 0 ? parts.join(" · ") : "No access beyond the org role";
}

type DraftBinding = { key: number; instance: string; role: string };

export function InviteDialog({
  open,
  onOpenChange,
  directory,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  directory: Directory;
}) {
  const client = useQueryClient();
  const me = useMe();
  const { allRoles: roles, allInstances: instances } = directory;
  const groups = directory.allGroups.filter((group) => !group.synced);
  const [email, setEmail] = useState("");
  const [orgRole, setOrgRole] = useState<OrgRole>("member");
  const [drafts, setDrafts] = useState<DraftBinding[]>([]);
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [endsAt, setEndsAt] = useState("");
  const canEmail = useEmailDelivery();
  const [chosen, setChosen] = useState<Delivery>("email");
  const delivery: Delivery = canEmail ? chosen : "link";
  const invite = useMutation({
    ...invitationsCreateInvitationMutation(),
    onSuccess: () => refreshDirectory(client),
  });
  const reset = () => {
    setEmail("");
    setOrgRole("member");
    setDrafts([]);
    setGroupIds([]);
    setEndsAt("");
    setChosen("email");
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
        group_ids: groupIds,
        access_ends_at: endOfDay(endsAt),
        delivery,
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
          <DialogDescription>
            {canEmail
              ? "Send the link by email, or create it and share it yourself."
              : "Email isn't set up here: you get a link to share yourself."}
          </DialogDescription>
        </DialogHeader>
        {invite.data ? (
          <div className="flex flex-col gap-3">
            <IssuedLink issued={invite.data} emailRequested={invite.variables.body.delivery === "email"} />
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
            {groups.length > 0 && (
              <fieldset className="flex flex-col gap-1.5">
                <legend className="mb-1 text-[13px] font-medium text-fg-secondary">Groups</legend>
                <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                  {groups.map((group) => (
                    <label key={group.id} className="flex cursor-pointer items-center gap-2 text-[13px]">
                      <input
                        type="checkbox"
                        className="size-4 accent-[var(--accent)]"
                        checked={groupIds.includes(group.id)}
                        onChange={() => {
                          setGroupIds(
                            groupIds.includes(group.id)
                              ? groupIds.filter((id) => id !== group.id)
                              : [...groupIds, group.id],
                          );
                        }}
                      />
                      {group.name}
                    </label>
                  ))}
                </div>
                <p className="text-[12px] text-fg-muted">Manual groups only; synced groups follow the IdP.</p>
              </fieldset>
            )}
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
            {canEmail && (
              <RadioCards
                legend="Delivery"
                value={delivery}
                onValueChange={setChosen}
                options={DELIVERY_OPTIONS}
              />
            )}
            {invite.error && <Callout tone="danger">{describeError(invite.error).reason}</Callout>}
            <DialogFooter>
              <Button type="submit" variant="primary" disabled={invite.isPending}>
                {delivery === "email" ? "Send invitation" : "Create link"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function InvitationsTab({ directory }: { directory: Directory }) {
  const client = useQueryClient();
  const invitations = useInvitations();
  const canEmail = useEmailDelivery();
  const refresh = () => refreshDirectory(client);
  const [issued, setIssued] = useState<{ value: IssuedInvitationOut; emailRequested: boolean } | null>(null);
  const [renewing, setRenewing] = useState<InvitationOut | null>(null);
  const resend = useMutation({
    ...invitationsResendInvitationMutation(),
    onSuccess: (value) => {
      setIssued({ value, emailRequested: true });
      return refresh();
    },
  });
  const renew = useMutation({
    ...invitationsRenewInvitationLinkMutation(),
    onSuccess: (value) => {
      setIssued({ value, emailRequested: false });
      setRenewing(null);
      return refresh();
    },
  });
  const revoke = useMutation({ ...invitationsRevokeInvitationMutation(), onSuccess: refresh });
  if (invitations.isPending) return <LoadingRows rows={2} label="Loading invitations" />;
  if (invitations.isError)
    return <ErrorState {...describeError(invitations.error)} onRetry={() => void invitations.refetch()} />;
  const pending = invitations.data.filter((invitation) => invitation.status === "pending");
  if (pending.length === 0) {
    return (
      <EmptyState title="No pending invitations">
        Invitations you send appear here until they're accepted.
      </EmptyState>
    );
  }
  const error = resend.error ?? renew.error ?? revoke.error;
  return (
    <div className="flex flex-col gap-3">
      <ul
        aria-label="Invitations"
        className="flex flex-col divide-y divide-divider-row rounded-card border border-border bg-surface"
      >
        {pending.map((invitation) => (
          <li key={invitation.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span className="text-[13.5px] font-medium">{invitation.email}</span>
              <span className="text-[12px] text-fg-muted">
                Invited by {memberName(directory.allMembers, invitation.invited_by)} · expires{" "}
                {formatRelative(invitation.expires_at)} · {ORG_ROLE_LABELS[invitation.org_role]}
              </span>
              <span className="text-[12.5px] text-fg-secondary">{accessSummary(invitation, directory)}</span>
            </div>
            <PermissionGate scope="org:members:write">
              <Button
                size="30"
                variant="outline"
                disabled={renew.isPending}
                onClick={() => {
                  setRenewing(invitation);
                }}
              >
                Copy new link
              </Button>
              {canEmail && (
                <Button
                  size="30"
                  variant="outline"
                  disabled={resend.isPending}
                  onClick={() => {
                    resend.mutate({ path: { invitation_id: invitation.id } });
                  }}
                >
                  Resend
                </Button>
              )}
              <Button
                size="30"
                variant="destructive-text"
                disabled={revoke.isPending}
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
      {issued && <IssuedLink issued={issued.value} emailRequested={issued.emailRequested} />}
      {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
      <ConfirmDialog
        open={renewing !== null}
        onOpenChange={(next) => {
          if (!next) setRenewing(null);
        }}
        title="Create a new invitation link?"
        confirmLabel="Create new link"
        pending={renew.isPending}
        onConfirm={() => {
          if (renewing) renew.mutate({ path: { invitation_id: renewing.id } });
        }}
      >
        The current link for {renewing?.email} stops working. No email is sent: you share the new link
        yourself.
      </ConfirmDialog>
    </div>
  );
}
