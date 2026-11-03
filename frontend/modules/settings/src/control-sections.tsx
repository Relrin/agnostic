// Org notification channels and defaults, and how approvals expire on this instance.
import {
  approvalsGetPolicyOptions,
  approvalsGetPolicyQueryKey,
  approvalsPutPolicyMutation,
  describeError,
  notificationsCreateChannelMutation,
  notificationsDeleteChannelMutation,
  notificationsEventTypesOptions,
  notificationsGetDefaultsOptions,
  notificationsGetDefaultsQueryKey,
  notificationsListChannelsOptions,
  notificationsListChannelsQueryKey,
  notificationsPutDefaultsMutation,
  notificationsTestChannelMutation,
  notificationsUpdateChannelMutation,
  orgGetOrgOptions,
  orgGetOrgQueryKey,
  orgUpdateOrgMutation,
  problemCode,
  type ChannelKindName,
  type ChannelOut,
  type InstanceOut,
  type PersonalChannelName,
} from "@agnostic/api";
import { useCan, withQueryFn } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  Input,
  LoadingRows,
  SegmentedControl,
  StatusPill,
  Switch,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

const PERSONAL: { id: PersonalChannelName; label: string }[] = [
  { id: "in_app", label: "In app" },
  { id: "email", label: "Email" },
  { id: "slack", label: "Slack" },
];

function Block({ title, children, action }: { title: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
      <header className="flex items-center justify-between gap-3">
        <h3 className="text-[13.5px] font-semibold">{title}</h3>
        {action}
      </header>
      {children}
    </section>
  );
}

function blankConfig(kind: ChannelKindName): Record<string, string> {
  if (kind === "slack") return { mode: "bot", token: "", channel: "", webhook_url: "" };
  if (kind === "email") return { to: "" };
  return { url: "", secret: "" };
}

function ChannelDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const events = useQuery(withQueryFn(notificationsEventTypesOptions()));
  const [kind, setKind] = useState<ChannelKindName>("slack");
  const [name, setName] = useState("");
  const [config, setConfig] = useState<Record<string, string>>(blankConfig("slack"));
  const [subscribed, setSubscribed] = useState<string[]>([]);
  const create = useMutation({
    ...notificationsCreateChannelMutation(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: notificationsListChannelsQueryKey() });
      onOpenChange(false);
      setName("");
      setConfig(blankConfig(kind));
      setSubscribed([]);
    },
  });
  const field = (key: string, label: string, hint?: string, secret = false) => (
    <Field label={label} hint={hint}>
      {({ id, describedBy }) => (
        <Input
          id={id}
          aria-describedby={describedBy}
          type={secret ? "password" : "text"}
          mono
          value={config[key] ?? ""}
          onChange={(event) => {
            setConfig({ ...config, [key]: event.target.value });
          }}
        />
      )}
    </Field>
  );
  const body = (): Record<string, unknown> => {
    if (kind === "email") return { to: (config.to ?? "").split(",").map((item) => item.trim()) };
    if (kind === "slack" && config.mode === "webhook")
      return { mode: "webhook", webhook_url: config.webhook_url };
    if (kind === "slack")
      return {
        mode: "bot",
        token: config.token,
        channel: config.channel === "" ? undefined : config.channel,
      };
    return { url: config.url, secret: config.secret === "" ? undefined : config.secret };
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a notification channel</DialogTitle>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ body: { kind, name, config: body(), events: subscribed } });
          }}
        >
          <SegmentedControl
            label="Kind"
            value={kind}
            options={[
              { value: "slack", label: "Slack" },
              { value: "email", label: "Email" },
              { value: "webhook", label: "Webhook" },
            ]}
            onValueChange={(value) => {
              setKind(value);
              setConfig(blankConfig(value));
            }}
          />
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
          {kind === "slack" && (
            <>
              <SegmentedControl
                label="Slack connection"
                value={config.mode ?? "bot"}
                options={[
                  { value: "bot", label: "Bot token" },
                  { value: "webhook", label: "Incoming webhook" },
                ]}
                onValueChange={(value) => {
                  setConfig({ ...config, mode: value });
                }}
              />
              {config.mode === "webhook" ? (
                field("webhook_url", "Webhook URL", "Posts to the channel the webhook was made for.", true)
              ) : (
                <>
                  {field("token", "Bot token", "xoxb-…; the bot can also DM people who turn Slack on.", true)}
                  {field("channel", "Channel", "Channel id (C0…) for org-wide posts; optional.")}
                </>
              )}
            </>
          )}
          {kind === "email" && field("to", "Addresses", "Comma-separated; a shared mailbox, for example.")}
          {kind === "webhook" && (
            <>
              {field("url", "URL")}
              {field(
                "secret",
                "Signing secret",
                "Requests carry X-Agnostic-Signature: sha256=HMAC(body).",
                true,
              )}
            </>
          )}
          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-[12px] text-fg-muted">Post these events here for everyone</legend>
            {(events.data ?? []).map((event) => (
              <label key={event.name} className="flex items-center gap-2 text-[13px]">
                <input
                  type="checkbox"
                  className="size-4 accent-[var(--accent)]"
                  checked={subscribed.includes(event.name)}
                  onChange={(change) => {
                    setSubscribed(
                      change.target.checked
                        ? [...subscribed, event.name]
                        : subscribed.filter((name) => name !== event.name),
                    );
                  }}
                />
                {event.label}
              </label>
            ))}
          </fieldset>
          {create.isError && <Callout tone="danger">{describeError(create.error).reason}</Callout>}
          <DialogFooter>
            <Button type="submit" disabled={create.isPending || !name.trim()}>
              Add channel
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ChannelRow({ channel }: { channel: ChannelOut }) {
  const queryClient = useQueryClient();
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: notificationsListChannelsQueryKey() });
  };
  const update = useMutation({ ...notificationsUpdateChannelMutation(), onSuccess: invalidate });
  const remove = useMutation({ ...notificationsDeleteChannelMutation(), onSuccess: invalidate });
  const test = useMutation({
    ...notificationsTestChannelMutation(),
    onSuccess: (delivery) => {
      invalidate();
      if (delivery.status === "sent") toast.success(`Sent a test message to ${channel.name}.`);
      else toast.error(delivery.error ?? `The test message ${delivery.status}.`);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const last = channel.recent[0];
  return (
    <li className="flex flex-wrap items-center gap-3 py-2.5">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-2 text-[13px] font-medium">
          {channel.name}
          <Badge tone="outline">{channel.kind}</Badge>
          {channel.sends_direct_messages && <Badge tone="info">DMs</Badge>}
        </span>
        <span className="text-[12px] text-fg-muted">
          {channel.events.length
            ? `Posts ${String(channel.events.length)} event types`
            : "Only when an approval route names it"}
          {last ? ` · last delivery ${last.status}${last.error ? `: ${last.error}` : ""}` : ""}
        </span>
      </div>
      {last && <StatusPill status={last.status} />}
      <Switch
        label={`Enable ${channel.name}`}
        hideLabel
        checked={channel.enabled}
        disabled={update.isPending}
        onCheckedChange={(checked) => {
          update.mutate({ path: { channel_id: channel.id }, body: { enabled: checked } });
        }}
      />
      <Button
        variant="outline"
        size="30"
        disabled={test.isPending || !channel.enabled}
        onClick={() => {
          test.mutate({ path: { channel_id: channel.id } });
        }}
      >
        Send test
      </Button>
      <Button
        variant="destructive-text"
        size="30"
        disabled={remove.isPending}
        onClick={() => {
          remove.mutate({ path: { channel_id: channel.id } });
        }}
      >
        Remove
      </Button>
    </li>
  );
}

function Defaults() {
  const queryClient = useQueryClient();
  const events = useQuery(withQueryFn(notificationsEventTypesOptions()));
  const defaults = useQuery(withQueryFn(notificationsGetDefaultsOptions()));
  const save = useMutation({
    ...notificationsPutDefaultsMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(notificationsGetDefaultsQueryKey(), data);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  if (events.isPending || defaults.isPending) return <LoadingRows rows={3} label="Loading defaults" />;
  if (events.isError || defaults.isError) return null;
  return (
    <table className="w-full text-[13px]">
      <caption className="sr-only">Default channels per event</caption>
      <thead>
        <tr className="text-left text-[11.5px] text-fg-muted">
          <th className="py-1.5 font-medium">Event</th>
          {PERSONAL.map((channel) => (
            <th key={channel.id} className="w-20 py-1.5 text-center font-medium">
              {channel.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-divider-row">
        {events.data.map((event) => {
          const current = defaults.data.events[event.name] ?? event.defaults;
          return (
            <tr key={event.name}>
              <td className="py-2 pr-4">{event.label}</td>
              {PERSONAL.map((channel) => {
                const checked = current.includes(channel.id);
                return (
                  <td key={channel.id} className="text-center">
                    <input
                      type="checkbox"
                      aria-label={`Default ${event.label} by ${channel.label}`}
                      className="size-4 accent-[var(--accent)]"
                      checked={checked}
                      disabled={save.isPending}
                      onChange={() => {
                        const next = checked
                          ? current.filter((id) => id !== channel.id)
                          : [...current, channel.id];
                        save.mutate({ body: { events: { [event.name]: next } } });
                      }}
                    />
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Org-wide: Slack, email and webhook channels, and what reaches people who haven't chosen. */
export function NotificationsSection() {
  const [adding, setAdding] = useState(false);
  const channels = useQuery({ ...withQueryFn(notificationsListChannelsOptions()), retry: false });
  if (channels.isError) {
    const forbidden = ["scope_missing", "forbidden"].includes(problemCode(channels.error) ?? "");
    return (
      <Callout tone={forbidden ? "availability" : "danger"}>
        {forbidden
          ? "Org notification channels need notifications:write (Owners and Administrators). Your own channels are in Account › Notifications."
          : describeError(channels.error).reason}
      </Callout>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <Callout tone="info">
        These settings are org-wide: every instance uses the same channels and defaults. Slack buttons open
        the approval in Agnostic, where a signed-in person decides; nothing is approved from Slack itself.
      </Callout>
      <Block
        title="Channels"
        action={
          <Button
            variant="outline"
            size="30"
            onClick={() => {
              setAdding(true);
            }}
          >
            Add channel
          </Button>
        }
      >
        {channels.isPending ? (
          <LoadingRows rows={2} label="Loading channels" />
        ) : channels.data.length === 0 ? (
          <EmptyState title="No channels yet">
            Add Slack, email or a webhook to notify people outside the app.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-divider-row">
            {channels.data.map((channel) => (
              <ChannelRow key={channel.id} channel={channel} />
            ))}
          </ul>
        )}
      </Block>
      <Block title="Defaults for people who haven't chosen">
        <Defaults />
      </Block>
      <ChannelDialog open={adding} onOpenChange={setAdding} />
    </div>
  );
}

/** The org's approval TTL and whether this instance stops runs when approvals expire. */
export function ApprovalsSection({ instance }: { instance: InstanceOut }) {
  const queryClient = useQueryClient();
  const isAdmin = useCan("agent_os:admin", instance.id);
  const canOrg = useCan("settings:write");
  const org = useQuery(withQueryFn(orgGetOrgOptions()));
  const policy = useQuery(withQueryFn(approvalsGetPolicyOptions({ path: { instance: instance.id } })));
  const [ttl, setTtl] = useState<string | undefined>(undefined);
  const saveOrg = useMutation({
    ...orgUpdateOrgMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(orgGetOrgQueryKey(), data);
      setTtl(undefined);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const savePolicy = useMutation({
    ...approvalsPutPolicyMutation(),
    onSuccess: (data) => {
      queryClient.setQueryData(approvalsGetPolicyQueryKey({ path: { instance: instance.id } }), data);
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  if (org.isPending || policy.isPending) return <LoadingRows rows={3} label="Loading approval settings" />;
  if (policy.isError) return <Callout tone="danger">{describeError(policy.error).reason}</Callout>;
  const orgTtl = org.data?.settings.approval_ttl_hours ?? 0;
  const value = ttl ?? String(orgTtl);
  return (
    <div className="flex flex-col gap-4">
      <Block title="Expiry">
        <p className="text-[13px] text-fg-secondary">
          AgentOS sets no expiry on agent and team approvals (workflow review steps can have a timeout).
          Agnostic can give them one: approvals then show a countdown, routed people get a reminder an hour
          before, and the inbox lists them as expired.
        </p>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            saveOrg.mutate({ body: { settings: { approval_ttl_hours: Number(value) || 0 } } });
          }}
        >
          <Field
            label="Expire approvals after (hours, org-wide)"
            hint="0 keeps them open until someone decides."
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                aria-describedby={describedBy}
                type="number"
                min={0}
                max={720}
                className="w-32"
                disabled={!canOrg.allowed}
                value={value}
                onChange={(event) => {
                  setTtl(event.target.value);
                }}
              />
            )}
          </Field>
          <Button
            type="submit"
            variant="outline"
            disabled={!canOrg.allowed || saveOrg.isPending || value === String(orgTtl)}
          >
            Save
          </Button>
        </form>
      </Block>
      <Block title={`On ${instance.display_name}`}>
        <Switch
          label="Stop runs when their approval expires"
          description="Off by default, like AgentOS: expired approvals are only shown. On: agent and team approvals are rejected as expired and the run continues with the rejection; workflows continue past their step timeout so AgentOS applies on_timeout."
          checked={policy.data.enforce_expiry}
          disabled={!isAdmin.allowed || savePolicy.isPending}
          onCheckedChange={(checked) => {
            savePolicy.mutate({
              path: { instance: instance.id },
              body: { enforce_expiry: checked, ttl_hours: policy.data.ttl_hours ?? null },
            });
          }}
        />
        {!isAdmin.allowed && (
          <p className="text-[12px] text-fg-muted">
            Changing this needs Instance admin on {instance.display_name}.
          </p>
        )}
      </Block>
    </div>
  );
}
