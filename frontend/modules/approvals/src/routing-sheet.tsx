// Routing rules (who gets told about an approval, through which channels) and the instance's expiry policy, in a
// side sheet opened from the inbox header.
import {
  accessListRolesOptions,
  approvalsCreateRouteMutation,
  approvalsDeleteRouteMutation,
  approvalsGetPolicyOptions,
  approvalsListRoutesOptions,
  approvalsPutPolicyMutation,
  approvalsUpdateRouteMutation,
  describeError,
  membersListMembersOptions,
  notificationsListChannelsOptions,
  type PersonalChannelName,
  type PolicyOut,
  type RouteIn,
  type RouteOut,
} from "@agnostic/api";
import { formatRelative, useCan, withQueryFn } from "@agnostic/core";
import {
  Button,
  Callout,
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
  SheetTrigger,
  Switch,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Route as RouteIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

const PERSONAL_CHANNELS: { id: PersonalChannelName; label: string }[] = [
  { id: "in_app", label: "In app" },
  { id: "email", label: "Email" },
  { id: "slack", label: "Slack" },
];
const COMPONENT_KINDS = ["agent", "team", "workflow"] as const;
const ANY = "any";

type Draft = {
  name: string;
  tool: string;
  componentKind: (typeof COMPONENT_KINDS)[number] | typeof ANY;
  componentIds: string;
  memberIds: string[];
  roleIds: string[];
  channels: PersonalChannelName[];
  channelIds: string[];
};

function draftOf(route: RouteOut | undefined): Draft {
  return {
    name: route?.name ?? "",
    tool: route?.tool_name ?? "",
    componentKind: route?.component_kind ?? ANY,
    componentIds: route?.component_ids.join(", ") ?? "",
    memberIds: route?.members.map((member) => member.id) ?? [],
    roleIds: route?.roles.map((role) => role.id) ?? [],
    channels: route?.channels ?? ["in_app"],
    channelIds: route?.channel_ids ?? [],
  };
}

function bodyOf(draft: Draft): RouteIn {
  return {
    name: draft.name.trim(),
    tool_name: draft.tool.trim() || null,
    component_kind: draft.componentKind === ANY ? null : draft.componentKind,
    component_ids: draft.componentIds
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean),
    member_ids: draft.memberIds,
    role_ids: draft.roleIds,
    channels: draft.channels,
    channel_ids: draft.channelIds,
  };
}

function toggle<T>(list: readonly T[], item: T): T[] {
  return list.includes(item) ? list.filter((value) => value !== item) : [...list, item];
}

/** A labelled group of checkboxes (members, roles, channels). */
function CheckList<T extends string>({
  legend,
  options,
  value,
  onChange,
  empty,
}: {
  legend: string;
  options: readonly { id: T; label: ReactNode }[];
  value: readonly T[];
  onChange: (next: T[]) => void;
  empty?: ReactNode;
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1 text-[13px] font-medium text-fg-secondary">{legend}</legend>
      {options.length === 0 && empty}
      <div className="flex max-h-40 flex-col gap-1 overflow-y-auto">
        {options.map((option) => (
          <label key={option.id} className="flex cursor-pointer items-center gap-2 text-[13px]">
            <input
              type="checkbox"
              className="size-4 accent-[var(--accent)]"
              checked={value.includes(option.id)}
              onChange={() => {
                onChange(toggle(value, option.id));
              }}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function RouteForm({
  instance,
  route,
  onDone,
}: {
  instance: string;
  route: RouteOut | undefined;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState(() => draftOf(route));
  const members = useQuery(withQueryFn(membersListMembersOptions()));
  const roles = useQuery(withQueryFn(accessListRolesOptions()));
  const channels = useQuery({ ...withQueryFn(notificationsListChannelsOptions()), retry: false });
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: [{ _id: "approvalsListRoutes" }] });
    onDone();
  };
  const create = useMutation({ ...approvalsCreateRouteMutation(), onSuccess: refresh });
  const update = useMutation({ ...approvalsUpdateRouteMutation(), onSuccess: refresh });
  const saving = create.isPending || update.isPending;
  const error = create.error ?? update.error;
  const set = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }));
  };
  const valid = draft.name.trim() !== "" && (draft.memberIds.length > 0 || draft.roleIds.length > 0);

  return (
    <form
      aria-label={route ? `Edit route ${route.name}` : "New route"}
      className="flex flex-col gap-4 rounded-card border border-border bg-surface p-4"
      onSubmit={(event) => {
        event.preventDefault();
        const body = bodyOf(draft);
        if (route) update.mutate({ path: { route_id: route.id }, body });
        else create.mutate({ path: { instance }, body });
      }}
    >
      <Field label="Route name" hint="Usually the team it reaches, e.g. Billing ops.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            value={draft.name}
            onChange={(event) => {
              set({ name: event.target.value });
            }}
          />
        )}
      </Field>
      <Field label="Tool" hint="Leave empty for every tool marked @approval.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            mono
            aria-describedby={describedBy}
            placeholder="Every tool"
            value={draft.tool}
            onChange={(event) => {
              set({ tool: event.target.value });
            }}
          />
        )}
      </Field>
      <div className="grid grid-cols-[140px_1fr] gap-3">
        <Field label="Component">
          {({ id }) => (
            <Select
              value={draft.componentKind}
              onValueChange={(value) => {
                set({ componentKind: value as Draft["componentKind"] });
              }}
            >
              <SelectTrigger id={id}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Any</SelectItem>
                {COMPONENT_KINDS.map((kind) => (
                  <SelectItem key={kind} value={kind}>
                    {kind}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
        <Field label="Component ids" hint="Comma-separated; empty for all.">
          {({ id, describedBy }) => (
            <Input
              id={id}
              mono
              aria-describedby={describedBy}
              placeholder="billing-agent"
              value={draft.componentIds}
              onChange={(event) => {
                set({ componentIds: event.target.value });
              }}
            />
          )}
        </Field>
      </div>
      {members.isError ? (
        <p className="text-[12px] text-fg-muted">
          Members didn&apos;t load: {describeError(members.error).reason}
        </p>
      ) : (
        <CheckList
          legend="Members"
          options={(members.data ?? []).map((member) => ({ id: member.user_id, label: member.display_name }))}
          value={draft.memberIds}
          onChange={(memberIds) => {
            set({ memberIds });
          }}
        />
      )}
      {!roles.isError && (
        <CheckList
          legend="Roles"
          options={(roles.data ?? []).map((role) => ({ id: role.id, label: role.name }))}
          value={draft.roleIds}
          onChange={(roleIds) => {
            set({ roleIds });
          }}
        />
      )}
      <CheckList
        legend="Personal channels"
        options={PERSONAL_CHANNELS}
        value={draft.channels}
        onChange={(next) => {
          set({ channels: next });
        }}
      />
      {channels.isSuccess && (
        <CheckList
          legend="Org channels"
          options={channels.data.map((channel) => ({
            id: channel.id,
            label: (
              <>
                {channel.name} <span className="text-fg-muted">· {channel.kind}</span>
              </>
            ),
          }))}
          value={draft.channelIds}
          onChange={(channelIds) => {
            set({ channelIds });
          }}
          empty={<p className="text-[12px] text-fg-muted">No org channels yet.</p>}
        />
      )}
      {error && (
        <Callout tone="danger" title="The route wasn't saved">
          {describeError(error).reason}
        </Callout>
      )}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="32" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="32" disabled={!valid || saving}>
          {route ? "Save route" : "Add route"}
        </Button>
      </div>
    </form>
  );
}

function RouteItem({ route, canEdit, onEdit }: { route: RouteOut; canEdit: boolean; onEdit: () => void }) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const remove = useMutation({
    ...approvalsDeleteRouteMutation(),
    onSuccess: () => client.invalidateQueries({ queryKey: [{ _id: "approvalsListRoutes" }] }),
    onError: (error) => toast.error(describeError(error).reason),
  });
  const who = [
    ...route.members.map((member) => member.name),
    ...route.roles.map((role) => `${role.name} (role)`),
  ];
  const component = route.component_kind
    ? `${route.component_kind}${route.component_ids.length ? ` ${route.component_ids.join(", ")}` : ""}`
    : route.component_ids.join(", ");
  return (
    <li className="flex flex-col gap-1.5 border-b border-divider-row py-3 last:border-0">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="text-[13.5px] font-semibold">{route.name}</span>
          <span className="text-[12px] text-fg-muted">
            <code className="font-mono">{route.tool_name ?? "every tool"}</code>
            {component && <> on {component}</>}
            {" · "}
            {route.instance_id ? "this instance" : "all instances"}
          </span>
        </div>
        {canEdit && (
          <div className="flex shrink-0 gap-1">
            {confirming ? (
              <>
                <Button
                  variant="destructive-text"
                  size="28"
                  disabled={remove.isPending}
                  onClick={() => {
                    remove.mutate({ path: { route_id: route.id } });
                  }}
                >
                  Delete route
                </Button>
                <Button
                  variant="ghost"
                  size="28"
                  onClick={() => {
                    setConfirming(false);
                  }}
                >
                  Keep
                </Button>
              </>
            ) : (
              <>
                <Button variant="ghost" size="28" aria-label={`Edit ${route.name}`} onClick={onEdit}>
                  Edit
                </Button>
                <Button
                  variant="ghost"
                  size="28"
                  aria-label={`Delete ${route.name}`}
                  onClick={() => {
                    setConfirming(true);
                  }}
                >
                  Delete
                </Button>
              </>
            )}
          </div>
        )}
      </div>
      <span className="text-[12.5px] text-fg-secondary">
        Tells {who.length ? who.join(", ") : "nobody"} via{" "}
        {[
          ...route.channels.map(
            (channel) => PERSONAL_CHANNELS.find((item) => item.id === channel)?.label ?? channel,
          ),
          ...(route.channel_ids.length
            ? [`${String(route.channel_ids.length)} org channel${route.channel_ids.length > 1 ? "s" : ""}`]
            : []),
        ].join(" + ") || "no channel"}
        <span className="text-fg-muted"> · updated {formatRelative(route.updated_at)}</span>
      </span>
    </li>
  );
}

function ExpiryPolicy({ instance, policy }: { instance: string; policy: PolicyOut }) {
  const client = useQueryClient();
  const admin = useCan("agent_os:admin", instance).allowed === true;
  const [ttl, setTtl] = useState(policy.ttl_hours === null ? "" : String(policy.ttl_hours));
  const save = useMutation({
    ...approvalsPutPolicyMutation(),
    onSuccess: () => client.invalidateQueries({ queryKey: [{ _id: "approvalsGetPolicy" }] }),
    onError: (error) => toast.error(describeError(error).reason),
  });
  const hours = ttl.trim() === "" ? null : Number(ttl);
  const valid = hours === null || (Number.isInteger(hours) && hours > 0);
  const put = (enforce: boolean, ttlHours: number | null) => {
    save.mutate({ path: { instance }, body: { enforce_expiry: enforce, ttl_hours: ttlHours } });
  };
  const ttlId = useId();
  return (
    <section aria-label="Expiry" className="flex flex-col gap-3">
      <h3 className="text-[13.5px] font-semibold">Expiry</h3>
      <Switch
        label="Expiry stops the run"
        description="When on, a request past its expiry is rejected and the run cancelled. When off, it shows as expired and the run stays paused."
        checked={policy.enforce_expiry}
        disabled={!admin || save.isPending}
        onCheckedChange={(checked) => {
          put(checked, policy.ttl_hours);
        }}
      />
      <div className="flex items-end gap-2">
        <label htmlFor={ttlId} className="flex flex-col gap-1 text-[12.5px] text-fg-secondary">
          Expire after (hours)
          <Input
            id={ttlId}
            type="number"
            min={1}
            className="w-32"
            placeholder="Never"
            disabled={!admin}
            aria-invalid={!valid || undefined}
            value={ttl}
            onChange={(event) => {
              setTtl(event.target.value);
            }}
          />
        </label>
        {admin && (
          <Button
            variant="outline"
            size="32"
            disabled={!valid || save.isPending || hours === policy.ttl_hours}
            onClick={() => {
              put(policy.enforce_expiry, hours);
            }}
          >
            Save expiry
          </Button>
        )}
      </div>
      {!admin && (
        <p className="text-[12px] text-fg-muted">Only an Instance admin changes the expiry policy.</p>
      )}
    </section>
  );
}

/** The "Routing" header button and its sheet. */
export function RoutingSheet({ instance }: { instance: string }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<RouteOut | "new" | undefined>();
  const canWrite = useCan("approvals:write", instance).allowed === true;
  const canWriteOrg = useCan("settings:write").allowed === true;
  const routes = useQuery({
    ...withQueryFn(approvalsListRoutesOptions({ path: { instance } })),
    enabled: open && Boolean(instance),
  });
  const policy = useQuery({
    ...withQueryFn(approvalsGetPolicyOptions({ path: { instance } })),
    enabled: open && Boolean(instance),
  });

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setEditing(undefined);
      }}
    >
      <SheetTrigger asChild>
        <Button variant="outline" size="34">
          <RouteIcon aria-hidden />
          Routing
        </Button>
      </SheetTrigger>
      <SheetContent className="w-[min(520px,100%)] overflow-y-auto">
        <div className="flex flex-col gap-1 pr-8">
          <SheetTitle className="text-[16px] font-semibold">Approval routing</SheetTitle>
          <SheetDescription className="text-[12.5px] text-fg-secondary">
            Routing is advisory: it decides who gets told about a request, not who may resolve it. Anyone with{" "}
            <code className="font-mono">approvals:write</code> on {instance} can still resolve. Without a
            matching route, everyone who can resolve is told.
          </SheetDescription>
        </div>

        {editing ? (
          <RouteForm
            key={editing === "new" ? "new" : editing.id}
            instance={instance}
            route={editing === "new" ? undefined : editing}
            onDone={() => {
              setEditing(undefined);
            }}
          />
        ) : (
          canWrite && (
            <Button
              variant="dashed-add"
              size="32"
              onClick={() => {
                setEditing("new");
              }}
            >
              <Plus aria-hidden />
              Add route
            </Button>
          )
        )}

        {routes.isError ? (
          <ErrorState {...describeError(routes.error)} onRetry={() => void routes.refetch()} />
        ) : routes.isPending ? (
          <LoadingRows rows={3} label="Loading routes" />
        ) : routes.data.length === 0 ? (
          <p className="text-[13px] text-fg-muted">
            No routes yet: requests go to everyone who can resolve them.
          </p>
        ) : (
          <ul aria-label="Routes" className="flex flex-col">
            {routes.data.map((route) => (
              <RouteItem
                key={route.id}
                route={route}
                canEdit={route.instance_id ? canWrite : canWriteOrg}
                onEdit={() => {
                  setEditing(route);
                }}
              />
            ))}
          </ul>
        )}

        {policy.isSuccess && (
          <ExpiryPolicy key={policy.data.updated_at ?? "default"} instance={instance} policy={policy.data} />
        )}
      </SheetContent>
    </Sheet>
  );
}
