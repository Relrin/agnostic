// The member aside: org role, effective access by instance (through groups or direct, with expiry), adding a direct
// role or explicit scopes, temporary access, "Check a permission" with its explanation, and removing the person.
import {
  accessCreateBindingMutation,
  accessDeleteBindingMutation,
  accessExplainMutation,
  accessGrantTemporaryMutation,
  accessListScopesOptions,
  describeError,
  membersRemoveMemberMutation,
  membersUpdateMemberMutation,
  type InstanceOut,
  type MemberOut,
} from "@agnostic/api";
import { ORG_ROLE_LABELS, STALE_TIME, useCan, useMe, useOrg, withQueryFn } from "@agnostic/core";
import {
  Avatar,
  Badge,
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EnvBadge,
  Field,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX } from "lucide-react";
import { useId, useState, type ReactNode, type SubmitEvent } from "react";

import { ConfirmDialog } from "./confirm-dialog";
import { GrantFields, draftGrant, draftReady, emptyDraft, type GrantDraft } from "./grant-fields";
import {
  effectiveGrants,
  endOfDay,
  endsLabel,
  firstName,
  grantsOn,
  hasFullAccess,
  memberGroups,
  refreshDirectory,
  type Directory,
  type Grant,
  type PeopleSearch,
} from "./people-api";

type OrgRole = MemberOut["org_role"];

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

function GrantLine({
  grant,
  member,
  canBind,
  onRemove,
  onOpenGroup,
}: {
  grant: Grant;
  member: MemberOut;
  canBind: boolean;
  onRemove: (bindingId: string) => void;
  onOpenGroup: (groupId: string) => void;
}) {
  const ends = endsLabel(grant.binding?.expires_at);
  const scoped = grant.binding !== null && grant.binding.role_id === null;
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
      {grant.color && (
        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: grant.color }} />
      )}
      <span className={scoped ? "font-mono text-[12.5px]" : "font-semibold"}>{grant.name}</span>
      {grant.key === "full" ? (
        <span className="text-[12.5px] text-fg-muted">as {ORG_ROLE_LABELS[member.org_role]}</span>
      ) : grant.via ? (
        <span className="text-[12.5px] text-fg-muted">
          via{" "}
          <button
            type="button"
            className="cursor-pointer text-info hover:text-info-hover hover:underline"
            onClick={() => {
              if (grant.via) onOpenGroup(grant.via.id);
            }}
          >
            {grant.via.name}
          </button>
        </span>
      ) : (
        <span className="text-[12.5px] text-fg-muted">Direct</span>
      )}
      {grant.instanceId === null && grant.key !== "full" && <Badge tone="outline">all instances</Badge>}
      {ends && <span className="text-[12px] text-warning">{ends}</span>}
      {canBind && grant.binding && !grant.via && (
        <Button
          className="ml-auto"
          size="28"
          variant="destructive-text"
          aria-label={`Remove ${grant.name} from ${member.display_name}`}
          onClick={() => {
            if (grant.binding) onRemove(grant.binding.id);
          }}
        >
          Remove
        </Button>
      )}
    </div>
  );
}

function AddDirectRole({
  member,
  directory,
  onDone,
}: {
  member: MemberOut;
  directory: Directory;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<GrantDraft>(() =>
    emptyDraft(directory.allRoles, directory.allInstances),
  );
  const [expires, setExpires] = useState("");
  const [reason, setReason] = useState("");
  const add = useMutation({
    ...accessCreateBindingMutation(),
    onSuccess: async () => {
      toast.success(`Gave ${member.display_name} access`);
      await refreshDirectory(client);
      onDone();
    },
  });
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    add.mutate({
      body: {
        principal_kind: "user",
        principal_id: member.user_id,
        ...draftGrant(draft),
        expires_at: endOfDay(expires),
        reason: reason.trim() || null,
      },
    });
  };
  return (
    <form
      aria-label="Add direct role"
      onSubmit={submit}
      className="flex flex-col gap-3 rounded-tile border border-border-dashed p-3"
    >
      <GrantFields
        draft={draft}
        onChange={setDraft}
        roles={directory.allRoles}
        instances={directory.allInstances}
      />
      <div className="grid grid-cols-2 gap-2">
        <Field label="Expires (optional)">
          {({ id }) => (
            <Input
              id={id}
              type="date"
              className="h-8"
              value={expires}
              onChange={(event) => {
                setExpires(event.target.value);
              }}
            />
          )}
        </Field>
        <Field label="Reason (optional)">
          {({ id }) => (
            <Input
              id={id}
              className="h-8"
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
              }}
            />
          )}
        </Field>
      </div>
      {add.error && <Callout tone="danger">{describeError(add.error).reason}</Callout>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="30" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="30" disabled={!draftReady(draft) || add.isPending}>
          Add
        </Button>
      </div>
    </form>
  );
}

const DURATIONS = [1, 4, 8, 24, 72, 168] as const;

function hoursLabel(hours: number): string {
  if (hours % 24 === 0) return `${String(hours / 24)} day${hours === 24 ? "" : "s"}`;
  return `${String(hours)} hour${hours === 1 ? "" : "s"}`;
}

function TemporaryAccessDialog({
  member,
  directory,
  open,
  onOpenChange,
}: {
  member: MemberOut;
  directory: Directory;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const client = useQueryClient();
  const org = useOrg();
  const max = org.data?.settings.temporary_access_max_hours ?? 72;
  const durations = DURATIONS.filter((hours) => hours <= max);
  const [draft, setDraft] = useState<GrantDraft>(() =>
    emptyDraft(directory.allRoles, directory.allInstances),
  );
  const [hours, setHours] = useState(String(durations.includes(8) ? 8 : (durations[0] ?? 1)));
  const [reason, setReason] = useState("");
  const grant = useMutation({
    ...accessGrantTemporaryMutation(),
    onSuccess: async (binding) => {
      toast.success(
        `${member.display_name} has access until ${new Date(binding.expires_at ?? "").toLocaleString()}`,
      );
      await refreshDirectory(client);
      onOpenChange(false);
    },
  });
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const { instance, role_id, scopes } = draftGrant(draft);
    grant.mutate({
      body: {
        principal_kind: "user",
        principal_id: member.user_id,
        instance,
        role_id,
        scopes,
        reason: reason.trim(),
        duration_hours: Number(hours),
      },
    });
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Grant temporary access</DialogTitle>
          <DialogDescription>
            {member.display_name} gets this until it expires; the expiry removes it on its own. Both are in
            the audit log.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <GrantFields
            draft={draft}
            onChange={setDraft}
            roles={directory.allRoles}
            instances={directory.allInstances}
          />
          <Field label="For">
            {({ id }) => (
              <Select value={hours} onValueChange={setHours}>
                <SelectTrigger id={id}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {durations.map((value) => (
                    <SelectItem key={value} value={String(value)}>
                      {hoursLabel(value)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Field label="Reason">
            {({ id }) => (
              <Input
                id={id}
                required
                placeholder="Incident 4471: rotate the gateway key"
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
              />
            )}
          </Field>
          {grant.error && <Callout tone="danger">{describeError(grant.error).reason}</Callout>}
          <DialogFooter>
            <Button
              type="submit"
              variant="primary"
              disabled={!draftReady(draft) || !reason.trim() || grant.isPending}
            >
              Grant access
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The explanation with its `scope` spans as code. */
function Explanation({ text }: { text: string }) {
  return (
    <>
      {text.split("`").map((part, index) =>
        index % 2 === 1 ? (
          <code key={index} className="font-mono text-[12px]">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}

const PER_COMPONENT: Record<string, string> = {
  agents: "Agent id",
  teams: "Team id",
  workflows: "Workflow id",
};

function CheckPermission({ member, instances }: { member: MemberOut; instances: readonly InstanceOut[] }) {
  const catalog = useQuery({ ...withQueryFn(accessListScopesOptions()), staleTime: STALE_TIME.config });
  const scopes = (catalog.data ?? []).filter(
    (scope) => !scope.hidden && scope.source === "agentos" && scope.family !== "agent_os",
  );
  const resources = [...new Set(scopes.map((scope) => scope.family))];
  const [resource, setResource] = useState("");
  const [verb, setVerb] = useState("");
  const [component, setComponent] = useState("");
  const [instance, setInstance] = useState(instances[0]?.id ?? "");
  const componentId = useId();
  const explain = useMutation(accessExplainMutation());
  const verbs = [
    ...new Set(scopes.filter((scope) => !resource || scope.family === resource).map((scope) => scope.action)),
  ];
  const componentLabel = PER_COMPONENT[resource];
  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    explain.mutate({
      body: {
        user_id: member.user_id,
        resource,
        verb,
        component: componentLabel && component.trim() ? component.trim() : null,
        instance: instance || null,
      },
    });
  };
  const result = explain.data;
  return (
    <Section title="Check a permission">
      <form onSubmit={submit} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-fg-secondary">
          <span>Can {firstName(member.display_name)}</span>
          <Select
            value={verb}
            onValueChange={(value) => {
              setVerb(value);
              explain.reset();
            }}
          >
            <SelectTrigger aria-label="Action" className="h-8 w-28">
              <SelectValue placeholder="Action" />
            </SelectTrigger>
            <SelectContent>
              {verbs.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={resource}
            onValueChange={(value) => {
              setResource(value);
              const actions = scopes.filter((scope) => scope.family === value).map((scope) => scope.action);
              if (!actions.includes(verb)) setVerb(actions[0] ?? "");
              explain.reset();
            }}
          >
            <SelectTrigger aria-label="Resource" className="h-8 w-36">
              <SelectValue placeholder="Resource" />
            </SelectTrigger>
            <SelectContent>
              {resources.map((item) => (
                <SelectItem key={item} value={item}>
                  {item}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span>on</span>
          <Select
            value={instance}
            onValueChange={(value) => {
              setInstance(value);
              explain.reset();
            }}
          >
            <SelectTrigger aria-label="On instance" className="h-8 w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {instances.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.slug}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-2">
          {componentLabel && (
            <>
              <label htmlFor={componentId} className="sr-only">
                {componentLabel}
              </label>
              <Input
                id={componentId}
                mono
                className="h-8"
                placeholder={`${componentLabel} (optional)`}
                value={component}
                onChange={(event) => {
                  setComponent(event.target.value);
                  explain.reset();
                }}
              />
            </>
          )}
          <Button
            type="submit"
            size="32"
            className="ml-auto"
            disabled={!resource || !verb || explain.isPending}
          >
            Check
          </Button>
        </div>
      </form>
      {result && (
        <div
          role="status"
          className="flex gap-2.5 rounded-tile border border-border bg-inset px-3 py-2.5 text-[13px]"
        >
          {result.allowed ? (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-label="Allowed" />
          ) : (
            <CircleX className="mt-0.5 size-4 shrink-0 text-danger" aria-label="Not allowed" />
          )}
          <div className="flex min-w-0 flex-col gap-1">
            <span>
              <strong>{result.allowed ? "Yes. " : "No. "}</strong>
              <Explanation text={result.explanation} />
            </span>
            {result.via_group && !result.explanation.includes(result.via_group) && (
              <span className="text-[12.5px] text-fg-secondary">Through the group {result.via_group}.</span>
            )}
            {!result.explanation.includes(`\`${result.scope}\``) && (
              <code className="font-mono text-[12px] text-fg-muted">{result.scope}</code>
            )}
            {result.alternatives.length > 0 && (
              <span className="text-[12.5px] text-fg-secondary">
                Would work with: {result.alternatives.map((alternative) => alternative.label).join(", ")}
              </span>
            )}
          </div>
        </div>
      )}
      {explain.error && <Callout tone="danger">{describeError(explain.error).reason}</Callout>}
    </Section>
  );
}

function isolationText(member: MemberOut, isolated: readonly InstanceOut[]): string {
  const where = isolated.map((instance) => instance.slug).join(" and ");
  return `User isolation is on for ${where}. ${firstName(member.display_name)} sees only their own sessions and memories there.`;
}

export function MemberAside({
  member,
  directory,
  go,
}: {
  member: MemberOut;
  directory: Directory;
  go: (next: Partial<PeopleSearch>) => void;
}) {
  const client = useQueryClient();
  const me = useMe();
  const canWrite = useCan("org:members:write").allowed === true;
  const canBind = useCan("org:roles:write").allowed === true;
  const [adding, setAdding] = useState(false);
  const [temporary, setTemporary] = useState(false);
  const [removing, setRemoving] = useState(false);
  const close = () => {
    go({ member: undefined });
  };
  const refresh = () => refreshDirectory(client);
  const updateRole = useMutation({ ...membersUpdateMemberMutation(), onSuccess: refresh });
  const remove = useMutation({
    ...membersRemoveMemberMutation(),
    onSuccess: async () => {
      toast.success(`Removed ${member.display_name} from the org`);
      setRemoving(false);
      close();
      await refresh();
    },
  });
  const deleteBinding = useMutation({ ...accessDeleteBindingMutation(), onSuccess: refresh });
  const grants = effectiveGrants(member, directory.allBindings, directory.allRoles, directory.explicitOnly);
  const groups = memberGroups(member);
  const isolated = directory.allInstances.filter((instance) => instance.user_isolation === true);
  const error = updateRole.error ?? remove.error ?? deleteBinding.error;
  const orgRoles: OrgRole[] =
    me.data?.org_role === "owner" ? ["member", "administrator", "owner"] : ["member", "administrator"];
  const openGroup = (groupId: string) => {
    go({ tab: "groups", group: groupId, member: undefined });
  };

  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <SheetContent className="w-[min(520px,100%)] overflow-y-auto">
        <div className="flex items-center gap-3 pr-8">
          <Avatar id={member.user_id} name={member.display_name} size={40} />
          <div className="flex min-w-0 flex-col">
            <SheetTitle className="text-[16px] font-semibold">{member.display_name}</SheetTitle>
            <SheetDescription className="text-[12.5px] text-fg-secondary">
              {member.email} · joined{" "}
              {new Date(member.joined_at).toLocaleDateString("en-GB", { month: "short", year: "numeric" })}{" "}
              through {member.joined_via}
            </SheetDescription>
          </div>
        </div>

        <Field label="Org role">
          {({ id }) => (
            <Select
              value={member.org_role}
              disabled={!canWrite || updateRole.isPending || !orgRoles.includes(member.org_role)}
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
                  <SelectItem key={role} value={role} disabled={!orgRoles.includes(role)}>
                    {ORG_ROLE_LABELS[role]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>

        {groups.length > 0 && (
          <Section title="Groups">
            <div className="flex flex-wrap gap-1.5">
              {groups.map((group) => (
                <Button
                  key={group.id}
                  variant="outline"
                  size="28"
                  onClick={() => {
                    openGroup(group.id);
                  }}
                >
                  {group.name}
                </Button>
              ))}
            </div>
          </Section>
        )}

        <Section
          title="Access by instance"
          action={
            canBind && !adding ? (
              <Button
                variant="link"
                size="28"
                onClick={() => {
                  setAdding(true);
                }}
              >
                Add direct role
              </Button>
            ) : undefined
          }
        >
          {hasFullAccess(member, directory.explicitOnly) && (
            <p className="text-[12.5px] text-fg-secondary">
              {ORG_ROLE_LABELS[member.org_role]}s have Full access on every instance unless the org requires
              explicit bindings.
            </p>
          )}
          <ul className="flex flex-col divide-y divide-divider-row rounded-tile border border-border">
            {directory.allInstances.map((instance) => {
              const here = grantsOn(grants, instance.id);
              return (
                <li
                  key={instance.id}
                  aria-label={`Access on ${instance.slug}`}
                  className="flex flex-col gap-1.5 px-3 py-2.5"
                >
                  <div className="flex items-center gap-2 text-[13px]">
                    <span className="font-mono">{instance.slug}</span>
                    <EnvBadge env={instance.env_tag} />
                  </div>
                  {here.length === 0 ? (
                    <span className="text-[12.5px] text-fg-muted">No access</span>
                  ) : (
                    here.map((grant) => (
                      <GrantLine
                        key={grant.key}
                        grant={grant}
                        member={member}
                        canBind={canBind}
                        onRemove={(bindingId) => {
                          deleteBinding.mutate({ path: { binding_id: bindingId } });
                        }}
                        onOpenGroup={openGroup}
                      />
                    ))
                  )}
                </li>
              );
            })}
          </ul>
          {adding && (
            <AddDirectRole
              member={member}
              directory={directory}
              onDone={() => {
                setAdding(false);
              }}
            />
          )}
          {canBind && (
            <Button
              variant="outline"
              size="30"
              className="self-start"
              onClick={() => {
                setTemporary(true);
              }}
            >
              Grant temporary access…
            </Button>
          )}
        </Section>

        <CheckPermission member={member} instances={directory.allInstances} />

        {isolated.length > 0 && <Callout tone="info">{isolationText(member, isolated)}</Callout>}
        {error && <Callout tone="danger">{describeError(error).reason}</Callout>}

        {canWrite && member.user_id !== me.data?.id && (
          <div className="mt-auto flex justify-start border-t border-border-subtle pt-4">
            <Button
              variant="destructive-text"
              onClick={() => {
                setRemoving(true);
              }}
            >
              Remove from org
            </Button>
          </div>
        )}
        {temporary && (
          <TemporaryAccessDialog
            member={member}
            directory={directory}
            open={temporary}
            onOpenChange={setTemporary}
          />
        )}
        <ConfirmDialog
          open={removing}
          onOpenChange={setRemoving}
          title={`Remove ${member.display_name} from the org?`}
          confirmLabel="Remove from org"
          pending={remove.isPending}
          onConfirm={() => {
            remove.mutate({ path: { user_id: member.user_id } });
          }}
        >
          They're signed out everywhere and lose every role binding, direct or through a group.
        </ConfirmDialog>
      </SheetContent>
    </Sheet>
  );
}
