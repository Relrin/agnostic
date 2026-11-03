// Directory sync: SCIM 2.0 (Okta, Entra ID push users and groups), IdP group → Agnostic group mapping rules, what
// happens when someone is removed upstream, and Google Workspace (read-only Directory API sync).
import {
  authListProvidersOptions,
  describeError,
  directoryCreateMappingRuleMutation,
  directoryCreateScimTokenMutation,
  directoryDeleteMappingRuleMutation,
  directoryGetDirectorySettingsOptions,
  directoryGetDirectorySettingsQueryKey,
  directoryGetGoogleSyncOptions,
  directoryGetGoogleSyncQueryKey,
  directoryListGroupsOptions,
  directoryListMappingRulesOptions,
  directoryListMappingRulesQueryKey,
  directoryRevokeScimTokenMutation,
  directoryRotateScimTokenMutation,
  directoryRunGoogleSyncMutation,
  directoryScimStatusOptions,
  directoryScimStatusQueryKey,
  directoryTestGoogleSyncMutation,
  directoryUpdateDirectorySettingsMutation,
  directoryUpdateGoogleSyncMutation,
  type GoogleSyncIn,
  type GoogleSyncOut,
  type IssuedScimTokenOut,
  type MappingRuleOut,
  type RuleSourceOut,
  type ScimStatusOut,
  type ScimTokenOut,
} from "@agnostic/api";
import { formatRelative, formatWhen, useReauth, withQueryFn, withReauth } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  CodeBlock,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
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
  StatusPill,
  Switch,
  Textarea,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ChangeEvent, type SubmitEvent } from "react";

import { CopyField, Facts, Section, splitList, useWritable } from "./shared";

const SOURCE_LABELS: Record<RuleSourceOut, string> = {
  scim: "SCIM group",
  oidc_claim: "SSO groups claim",
  google_directory: "Google group",
};

const TOKEN_TONES = {
  active: "success",
  rotating: "warning",
  expired: "muted",
  revoked: "danger",
} as const;

function countsText(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  return entries.length === 0
    ? "—"
    : entries.map(([key, value]) => `${String(value)} ${key.replace(/_/g, " ")}`).join(" · ");
}

/** "Okta SCIM · synced 4 min ago", or why it isn't syncing. */
function ScimPill({ status }: { status: ScimStatusOut }) {
  const live = status.tokens.find((token) => token.state === "active" || token.state === "rotating");
  const name = live ? live.label : "SCIM";
  if (!status.healthy && status.last_error)
    return (
      <Badge tone="danger" title={status.last_error}>
        {name} · failing {status.last_error_at ? formatRelative(status.last_error_at) : ""}
      </Badge>
    );
  if (!status.last_request_at) return <Badge tone="muted">{name} · no requests yet</Badge>;
  return (
    <Badge tone={status.healthy ? "success" : "warning"}>
      {name} · synced {formatRelative(status.last_request_at)}
    </Badge>
  );
}

function SecretOnce({
  issued,
  onClose,
}: {
  issued: { title: string; secret: string; note?: string } | null;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={issued !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{issued?.title}</DialogTitle>
          <DialogDescription>
            Copy it now and paste it into your identity provider's SCIM settings. It won't be shown again.
          </DialogDescription>
        </DialogHeader>
        {issued && <CodeBlock title="Bearer token" code={issued.secret} />}
        {issued?.note && <Callout tone="availability">{issued.note}</Callout>}
        <DialogFooter>
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ScimCard({ writable }: { writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const status = useQuery(withQueryFn(directoryScimStatusOptions()));
  const [label, setLabel] = useState("");
  const [issued, setIssued] = useState<{ title: string; secret: string; note?: string } | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: directoryScimStatusQueryKey() });
  const create = useMutation({
    ...withReauth(reauth, directoryCreateScimTokenMutation()),
    onSuccess: async (data: IssuedScimTokenOut) => {
      setLabel("");
      setIssued({ title: `SCIM token · ${data.token.label}`, secret: data.secret });
      await refresh();
    },
  });
  const rotate = useMutation({
    ...withReauth(reauth, directoryRotateScimTokenMutation()),
    onSuccess: async (data: IssuedScimTokenOut) => {
      setIssued({
        title: `New SCIM token · ${data.token.label}`,
        secret: data.secret,
        note: "The previous token keeps working for 24 hours, so you can update the IdP without a gap.",
      });
      await refresh();
    },
  });
  const revoke = useMutation({
    ...withReauth(reauth, directoryRevokeScimTokenMutation()),
    onSuccess: async () => {
      toast("Token revoked");
      await refresh();
    },
  });

  if (status.isPending) return <LoadingRows rows={3} label="Loading SCIM status" />;
  if (status.isError)
    return <ErrorState reason={describeError(status.error).reason} onRetry={() => void status.refetch()} />;

  const columns: Column<ScimTokenOut>[] = [
    {
      id: "label",
      header: "Token",
      cell: (row) => (
        <div className="flex flex-col">
          <span className="font-medium">{row.label}</span>
          <span className="font-mono text-[12px] text-fg-muted">{row.prefix}…</span>
        </div>
      ),
    },
    {
      id: "state",
      header: "State",
      cell: (row) => <StatusPill status={row.state} tone={TOKEN_TONES[row.state]} />,
    },
    {
      id: "used",
      header: "Last used",
      cell: (row) => (row.last_used_at ? formatRelative(row.last_used_at) : "Never"),
    },
    {
      id: "expires",
      header: "Expires",
      cell: (row) => (row.expires_at ? formatWhen(row.expires_at) : "—"),
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        writable && (row.state === "active" || row.state === "rotating") ? (
          <span className="inline-flex gap-1">
            {row.state === "active" && (
              <Button
                size="28"
                variant="ghost"
                aria-label={`Rotate ${row.label}`}
                disabled={rotate.isPending}
                onClick={() => {
                  rotate.mutate({ path: { token_id: row.id } });
                }}
              >
                Rotate
              </Button>
            )}
            <Button
              size="28"
              variant="destructive-text"
              aria-label={`Revoke ${row.label}`}
              disabled={revoke.isPending}
              onClick={() => {
                if (window.confirm(`Revoke ${row.label}? The IdP's SCIM requests fail from now on.`))
                  revoke.mutate({ path: { token_id: row.id } });
              }}
            >
              Revoke
            </Button>
          </span>
        ) : null,
    },
  ];

  const error = create.error ?? rotate.error ?? revoke.error;
  return (
    <Section
      title="SCIM provisioning"
      description="Okta and Microsoft Entra ID push people and groups here. Give the IdP the endpoint and a bearer token."
      action={<ScimPill status={status.data} />}
    >
      <Field label="SCIM base URL">
        {() => <CopyField label="SCIM base URL" value={status.data.endpoint_url} />}
      </Field>
      <Facts
        rows={[
          ["Synced", countsText(status.data.counts)],
          [
            "Last request",
            status.data.last_request_at ? formatWhen(status.data.last_request_at) : "None yet",
          ],
          ...(status.data.last_error
            ? ([
                [
                  "Last error",
                  <span key="error" className="text-danger">
                    {status.data.last_error}
                    {status.data.last_error_at ? ` · ${formatWhen(status.data.last_error_at)}` : ""}
                  </span>,
                ],
              ] as const)
            : []),
        ]}
      />
      <DataTable
        label="SCIM tokens"
        columns={columns}
        rows={status.data.tokens}
        rowKey={(row) => row.id}
        empty={<p className="text-[13px] text-fg-muted">No tokens yet. Create one for your IdP.</p>}
      />
      <p className="text-[12.5px] text-fg-muted">
        One token is active at a time. Rotating issues a new one; the old one keeps working for 24 hours.
      </p>
      {writable && (
        <form
          className="flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate({ body: { label: label.trim() } });
          }}
        >
          <Field label="New token label" className="w-64">
            {({ id }) => (
              <Input
                id={id}
                required
                placeholder="Okta"
                value={label}
                onChange={(event) => {
                  setLabel(event.target.value);
                }}
              />
            )}
          </Field>
          <Button type="submit" disabled={create.isPending || label.trim() === ""}>
            Create token
          </Button>
        </form>
      )}
      {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
      <SecretOnce
        issued={issued}
        onClose={() => {
          setIssued(null);
        }}
      />
    </Section>
  );
}

function MappingCard({ writable }: { writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const rules = useQuery(withQueryFn(directoryListMappingRulesOptions()));
  const groups = useQuery({ ...withQueryFn(directoryListGroupsOptions()), enabled: writable });
  const providers = useQuery({ ...withQueryFn(authListProvidersOptions()), enabled: writable, retry: false });
  const [source, setSource] = useState<RuleSourceOut>("scim");
  const [idpGroup, setIdpGroup] = useState("");
  const [groupId, setGroupId] = useState("");
  const [providerId, setProviderId] = useState("__any__");
  const refresh = () => queryClient.invalidateQueries({ queryKey: directoryListMappingRulesQueryKey() });
  const create = useMutation({
    ...withReauth(reauth, directoryCreateMappingRuleMutation()),
    onSuccess: async () => {
      setIdpGroup("");
      toast("Mapping rule added");
      await refresh();
    },
  });
  const remove = useMutation({
    ...withReauth(reauth, directoryDeleteMappingRuleMutation()),
    onSuccess: refresh,
  });

  const columns: Column<MappingRuleOut>[] = [
    { id: "source", header: "Source", cell: (row) => SOURCE_LABELS[row.source] },
    {
      id: "idp",
      header: "IdP group",
      cell: (row) => <span className="font-mono text-[12.5px]">{row.idp_group}</span>,
    },
    { id: "group", header: "Agnostic group", cell: (row) => row.group_name },
    {
      id: "provider",
      header: "Provider",
      cell: (row) => row.provider_id ?? <span className="text-fg-muted">Any</span>,
    },
    {
      id: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) =>
        writable ? (
          <Button
            size="28"
            variant="destructive-text"
            aria-label={`Remove rule ${row.idp_group}`}
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate({ path: { rule_id: row.id } });
            }}
          >
            Remove
          </Button>
        ) : null,
    },
  ];

  return (
    <Section
      title="Group mapping"
      description="Membership in an IdP group puts people in an Agnostic group, and that group's role bindings give them access."
    >
      {rules.isPending ? (
        <LoadingRows rows={2} label="Loading mapping rules" />
      ) : rules.isError ? (
        <ErrorState reason={describeError(rules.error).reason} />
      ) : (
        <DataTable
          label="Group mapping rules"
          columns={columns}
          rows={rules.data}
          rowKey={(row) => row.id}
          empty={
            <p className="text-[13px] text-fg-muted">
              No rules: synced groups appear under People › Groups as they are.
            </p>
          }
        />
      )}
      {writable && (
        <form
          className="grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] items-end gap-2"
          onSubmit={(event: SubmitEvent<HTMLFormElement>) => {
            event.preventDefault();
            create.mutate({
              body: {
                source,
                idp_group: idpGroup.trim(),
                group_id: groupId,
                provider_id: source === "oidc_claim" && providerId !== "__any__" ? providerId : null,
              },
            });
          }}
        >
          <Field label="Source">
            {({ id }) => (
              <Select
                value={source}
                onValueChange={(value) => {
                  setSource(value as RuleSourceOut);
                }}
              >
                <SelectTrigger id={id} aria-label="Source">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(SOURCE_LABELS) as RuleSourceOut[]).map((value) => (
                    <SelectItem key={value} value={value}>
                      {SOURCE_LABELS[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Field label="IdP group">
            {({ id }) => (
              <Input
                id={id}
                mono
                required
                placeholder="eng-oncall"
                value={idpGroup}
                onChange={(event) => {
                  setIdpGroup(event.target.value);
                }}
              />
            )}
          </Field>
          <Field label="Agnostic group">
            {({ id }) => (
              <Select value={groupId} onValueChange={setGroupId}>
                <SelectTrigger id={id} aria-label="Agnostic group">
                  <SelectValue placeholder="Choose a group" />
                </SelectTrigger>
                <SelectContent>
                  {(groups.data ?? []).map((group) => (
                    <SelectItem key={group.id} value={group.id}>
                      {group.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          {source === "oidc_claim" && (
            <Field label="Provider">
              {({ id }) => (
                <Select value={providerId} onValueChange={setProviderId}>
                  <SelectTrigger id={id} aria-label="Provider">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__any__">Any provider</SelectItem>
                    {(providers.data ?? []).map((provider) => (
                      <SelectItem key={provider.id} value={provider.id}>
                        {provider.display_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          )}
          <Button type="submit" disabled={create.isPending || idpGroup.trim() === "" || groupId === ""}>
            Add rule
          </Button>
        </form>
      )}
      {(create.error ?? remove.error) && (
        <Callout tone="danger">{describeError(create.error ?? remove.error).reason}</Callout>
      )}
    </Section>
  );
}

function DeprovisionCard({ writable }: { writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const settings = useQuery(withQueryFn(directoryGetDirectorySettingsOptions()));
  const save = useMutation({
    ...withReauth(reauth, directoryUpdateDirectorySettingsMutation()),
    onSuccess: (data) => {
      queryClient.setQueryData(directoryGetDirectorySettingsQueryKey(), data);
      toast("Deprovisioning behaviour saved");
    },
  });
  return (
    <Section
      title="When someone is removed upstream"
      description="Applies when SCIM deactivates or deletes a person, or Google Workspace suspends or removes them. Either way their sessions, tokens and bindings stop working immediately."
    >
      {settings.isPending ? (
        <LoadingRows rows={1} label="Loading deprovisioning" />
      ) : settings.isError ? (
        <ErrorState reason={describeError(settings.error).reason} />
      ) : (
        <fieldset disabled={!writable || save.isPending}>
          <RadioCards
            legend="Deprovisioning"
            value={save.variables?.body.deprovision ?? settings.data.deprovision}
            onValueChange={(value) => {
              save.mutate({ body: { deprovision: value } });
            }}
            options={[
              {
                value: "disable",
                label: "Disable the account",
                description:
                  "Recommended. They can't sign in; their history, audit trail and group memberships are kept, and re-activating restores them.",
              },
              {
                value: "remove",
                label: "Remove from the org",
                description:
                  "They leave the org: memberships and bindings are deleted. The audit trail keeps their name. Re-provisioning starts from scratch.",
              },
            ]}
          />
        </fieldset>
      )}
      {save.error && <Callout tone="danger">{describeError(save.error).reason}</Callout>}
    </Section>
  );
}

type GoogleForm = { json: string; subject: string; customer: string; filter: string; enabled: boolean };

function googleForm(google: GoogleSyncOut): GoogleForm {
  return {
    json: "",
    subject: google.admin_subject ?? "",
    customer: google.customer_id ?? "",
    filter: google.group_filter.join(", "),
    enabled: google.enabled,
  };
}

function GoogleCard({ google, writable }: { google: GoogleSyncOut; writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const [form, setForm] = useState(() => googleForm(google));
  const [jsonError, setJsonError] = useState<string | undefined>(undefined);
  const apply = (data: GoogleSyncOut) => {
    queryClient.setQueryData(directoryGetGoogleSyncQueryKey(), data);
  };
  const save = useMutation({
    ...withReauth(reauth, directoryUpdateGoogleSyncMutation()),
    onSuccess: (data) => {
      apply(data);
      setForm(googleForm(data));
      toast("Google Workspace sync saved");
    },
  });
  const test = useMutation(withReauth(reauth, directoryTestGoogleSyncMutation()));
  const sync = useMutation({
    ...withReauth(reauth, directoryRunGoogleSyncMutation()),
    onSuccess: (data) => {
      apply(data);
      toast(data.last_error ? "Sync finished with an error" : "Google Workspace synced");
    },
  });

  const upload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    void file.text().then((text) => {
      setForm((current) => ({ ...current, json: text }));
    });
  };

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setJsonError(undefined);
    if (form.json.trim()) {
      try {
        JSON.parse(form.json);
      } catch {
        setJsonError("That isn't valid JSON: paste the key file Google downloaded.");
        return;
      }
    }
    const body: GoogleSyncIn = {
      admin_subject: form.subject.trim() || null,
      customer_id: form.customer.trim() || null,
      group_filter: splitList(form.filter),
      enabled: form.enabled,
      ...(form.json.trim() ? { service_account_json: form.json.trim() } : {}),
    };
    save.mutate({ body });
  };

  const error = save.error ?? sync.error ?? test.error;
  return (
    <Section
      title="Google Workspace"
      description="Google doesn't push SCIM to custom apps, so Agnostic reads groups and people with a read-only service account every 15 minutes."
      action={
        google.configured ? (
          <StatusPill status={google.enabled ? (google.last_error ? "error" : "active") : "paused"} />
        ) : (
          <Badge tone="muted">Not set up</Badge>
        )
      }
    >
      <Callout tone="info" title="Setting it up">
        Create a service account in Google Cloud, enable domain-wide delegation for it in the Admin console
        with only the read-only scopes <code className="font-mono">admin.directory.group.readonly</code> and{" "}
        <code className="font-mono">admin.directory.user.readonly</code>, and enter an admin it can act as.
        Without it, Google users sign in with OIDC and groups are managed by hand.
      </Callout>
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <fieldset disabled={!writable} className="flex flex-col gap-4">
          <Field
            label="Service account key (JSON)"
            hint={
              google.client_email
                ? `Saved for ${google.client_email}. Paste or upload a new key to replace it; it's never shown.`
                : "Write-only: stored encrypted, never shown again."
            }
            error={jsonError}
          >
            {({ id, describedBy, invalid }) => (
              <div className="flex flex-col gap-2">
                <Textarea
                  id={id}
                  aria-describedby={describedBy}
                  aria-invalid={invalid || undefined}
                  placeholder={google.client_email ? "•••••• (saved)" : '{ "type": "service_account", … }'}
                  value={form.json}
                  onChange={(event) => {
                    setForm({ ...form, json: event.target.value });
                  }}
                />
                <label className="w-fit cursor-pointer text-[12.5px] text-info hover:underline">
                  Upload key file
                  <input type="file" accept="application/json,.json" className="sr-only" onChange={upload} />
                </label>
              </div>
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Admin to act as" hint="A Workspace admin's email (domain-wide delegation subject).">
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  type="email"
                  aria-describedby={describedBy}
                  value={form.subject}
                  onChange={(event) => {
                    setForm({ ...form, subject: event.target.value });
                  }}
                />
              )}
            </Field>
            <Field label="Customer ID" hint="Empty uses my_customer.">
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  mono
                  aria-describedby={describedBy}
                  value={form.customer}
                  onChange={(event) => {
                    setForm({ ...form, customer: event.target.value });
                  }}
                />
              )}
            </Field>
          </div>
          <Field
            label="Group filter"
            hint="Comma-separated group emails or prefixes. Empty syncs every group."
          >
            {({ id, describedBy }) => (
              <Input
                id={id}
                mono
                aria-describedby={describedBy}
                placeholder="eng-*@localhost.company"
                value={form.filter}
                onChange={(event) => {
                  setForm({ ...form, filter: event.target.value });
                }}
              />
            )}
          </Field>
          <Switch
            label="Sync every 15 minutes"
            checked={form.enabled}
            disabled={!writable}
            onCheckedChange={(checked) => {
              setForm({ ...form, enabled: checked });
            }}
          />
        </fieldset>
        <Facts
          rows={[
            ["Last run", google.last_run_at ? formatWhen(google.last_run_at) : "Never"],
            ["Synced", countsText(google.counts)],
            ...(google.last_error
              ? ([
                  [
                    "Last error",
                    <span key="e" className="text-danger">
                      {google.last_error}
                    </span>,
                  ],
                ] as const)
              : []),
          ]}
        />
        {test.data && (
          <Callout
            tone={test.data.ok ? "insight" : "danger"}
            title={test.data.ok ? "Connected" : "Connection failed"}
          >
            {test.data.detail}
          </Callout>
        )}
        {error && <Callout tone="danger">{describeError(error).reason}</Callout>}
        {writable && (
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </Button>
            <Button
              variant="secondary"
              disabled={!google.configured || test.isPending}
              onClick={() => {
                test.mutate({});
              }}
            >
              {test.isPending ? "Testing…" : "Test connection"}
            </Button>
            <Button
              variant="secondary"
              disabled={!google.configured || sync.isPending}
              onClick={() => {
                sync.mutate({});
              }}
            >
              {sync.isPending ? "Syncing…" : "Sync now"}
            </Button>
          </div>
        )}
      </form>
    </Section>
  );
}

function GoogleSection({ writable }: { writable: boolean }) {
  const google = useQuery(withQueryFn(directoryGetGoogleSyncOptions()));
  if (google.isPending) return <LoadingRows rows={3} label="Loading Google Workspace sync" />;
  if (google.isError) return <ErrorState reason={describeError(google.error).reason} />;
  return <GoogleCard key={String(google.data.configured)} google={google.data} writable={writable} />;
}

export function DirectorySection() {
  const { writable, note } = useWritable("org:members:write");
  return (
    <div className="flex flex-col gap-5">
      {note}
      <ScimCard writable={writable} />
      <MappingCard writable={writable} />
      <DeprovisionCard writable={writable} />
      <GoogleSection writable={writable} />
      <Section
        title="Keycloak"
        description="Keycloak has no native SCIM. Add a “Group Membership” mapper (claim name groups, full group path off) to the Agnostic client; groups then sync at each sign-in, and SSO groups claim rules above map them."
      >
        <p className="text-[12.5px] text-fg-muted">
          Other OIDC providers that send a groups claim work the same way.
        </p>
      </Section>
    </div>
  );
}
