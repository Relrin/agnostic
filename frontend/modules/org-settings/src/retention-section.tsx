// Audit retention & archive: how long events stay searchable in Postgres, and the S3-compatible archive each
// expiring month is written to (with a verified manifest) before its partition is dropped.
import {
  auditCheckPolicyWriteMutation,
  auditGetPolicyOptions,
  auditGetPolicyQueryKey,
  auditListArchivesOptions,
  auditListArchivesQueryKey,
  auditRestoreArchiveMutation,
  auditUpdatePolicyMutation,
  describeError,
  type ArchiveOut,
  type AuditPolicyIn,
  type AuditPolicyOut,
  type ObjectLockMode,
} from "@agnostic/api";
import { formatBytes, formatCount, formatWhen, useReauth, withQueryFn, withReauth } from "@agnostic/core";
import {
  Badge,
  Button,
  Callout,
  DataTable,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  RadioCards,
  Switch,
  toast,
  type Column,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { Facts, Section, optionalNumber, useWritable } from "./shared";

type RetentionForm = {
  hotDays: string;
  archive: boolean;
  endpoint: string;
  bucket: string;
  prefix: string;
  region: string;
  accessKey: string;
  /** `undefined` keeps the saved secret, "" clears it. */
  secret: string | undefined;
  lock: ObjectLockMode;
  archiveDays: string;
  hashChain: boolean;
};

function retentionForm(policy: AuditPolicyOut): RetentionForm {
  return {
    hotDays: String(policy.hot_retention_days),
    archive: policy.archive_enabled,
    endpoint: policy.endpoint ?? "",
    bucket: policy.bucket ?? "",
    prefix: policy.prefix,
    region: policy.region,
    accessKey: policy.access_key_id ?? "",
    secret: undefined,
    lock: policy.object_lock_mode,
    archiveDays: policy.archive_retention_days === null ? "" : String(policy.archive_retention_days),
    hashChain: policy.hash_chain,
  };
}

/** The PUT body: every field the form shows; the secret only when typed (or "" to clear it). */
export function retentionBody(form: RetentionForm): AuditPolicyIn {
  return {
    hot_retention_days: optionalNumber(form.hotDays),
    archive_enabled: form.archive,
    endpoint: form.endpoint.trim() || null,
    bucket: form.bucket.trim() || null,
    prefix: form.prefix.trim(),
    region: form.region.trim(),
    access_key_id: form.accessKey.trim() || null,
    object_lock_mode: form.lock,
    archive_retention_days: optionalNumber(form.archiveDays),
    hash_chain: form.hashChain,
    ...(form.secret !== undefined ? { secret_access_key: form.secret } : {}),
  };
}

function text(
  label: string,
  value: string,
  onChange: (value: string) => void,
  options: { hint?: string; placeholder?: string; type?: string; mono?: boolean } = {},
) {
  return (
    <Field label={label} hint={options.hint}>
      {({ id, describedBy }) => (
        <Input
          id={id}
          mono={options.mono ?? true}
          type={options.type ?? "text"}
          placeholder={options.placeholder}
          aria-describedby={describedBy}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </Field>
  );
}

function PolicyForm({ policy, writable }: { policy: AuditPolicyOut; writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const [form, setForm] = useState(() => retentionForm(policy));
  const saved = retentionForm(policy);
  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const set =
    <K extends keyof RetentionForm>(key: K) =>
    (value: RetentionForm[K]) => {
      setForm((current) => ({ ...current, [key]: value }));
    };
  const save = useMutation({
    ...withReauth(reauth, auditUpdatePolicyMutation()),
    onSuccess: (data) => {
      queryClient.setQueryData(auditGetPolicyQueryKey(), data);
      setForm(retentionForm(data));
      toast("Retention saved");
    },
  });
  const check = useMutation(withReauth(reauth, auditCheckPolicyWriteMutation()));

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate({ body: retentionBody(form) });
  };

  const secretHint =
    form.secret === ""
      ? "The saved secret is cleared when you save."
      : policy.has_secret
        ? "Saved. Leave empty to keep it."
        : "Write-only: stored encrypted.";

  return (
    <form className="flex flex-col gap-5" onSubmit={submit}>
      <Section
        title="Searchable window"
        description="Events stay in Postgres, searchable and exportable, for this many days."
      >
        <fieldset disabled={!writable} className="max-w-xs">
          {text("Keep events for (days)", form.hotDays, set("hotDays"), {
            type: "number",
            hint: "Default 400 days.",
            mono: false,
          })}
        </fieldset>
      </Section>
      <Section
        title="Archive"
        description="Before a month leaves the searchable window it's written to S3-compatible storage (JSONL.zst plus a manifest with the event count, SHA-256 and hash-chain head), verified, and only then dropped."
      >
        <fieldset disabled={!writable} className="flex flex-col gap-4">
          <Switch
            label="Archive expiring months"
            description="Off: months older than the window are deleted."
            checked={form.archive}
            disabled={!writable}
            onCheckedChange={set("archive")}
          />
          {form.archive && (
            <>
              <div className="grid grid-cols-2 gap-3">
                {text("Endpoint", form.endpoint, set("endpoint"), {
                  placeholder: "https://s3.eu-central-1.amazonaws.com",
                  hint: "Empty uses AWS S3. MinIO, R2 and other S3-compatible stores work.",
                })}
                {text("Region", form.region, set("region"), { placeholder: "us-east-1" })}
                {text("Bucket", form.bucket, set("bucket"), { placeholder: "agnostic-audit" })}
                {text("Prefix", form.prefix, set("prefix"), { placeholder: "audit/" })}
                {text("Access key ID", form.accessKey, set("accessKey"))}
                <Field label="Secret access key" hint={secretHint}>
                  {({ id, describedBy }) => (
                    <div className="flex items-center gap-2">
                      <Input
                        id={id}
                        type="password"
                        mono
                        autoComplete="off"
                        placeholder={policy.has_secret && form.secret === undefined ? "•••••• (saved)" : ""}
                        aria-describedby={describedBy}
                        value={form.secret ?? ""}
                        onChange={(event) => {
                          set("secret")(event.target.value === "" ? undefined : event.target.value);
                        }}
                      />
                      {policy.has_secret && form.secret === undefined && (
                        <Button
                          size="30"
                          variant="ghost"
                          onClick={() => {
                            set("secret")("");
                          }}
                        >
                          Clear
                        </Button>
                      )}
                    </div>
                  )}
                </Field>
              </div>
              <RadioCards
                legend="S3 Object Lock"
                value={form.lock}
                onValueChange={set("lock")}
                options={[
                  {
                    value: "off",
                    label: "Off",
                    description: "Archives can be deleted by whoever holds the keys.",
                  },
                  {
                    value: "governance",
                    label: "Governance",
                    description: "Locked until retention ends; special permission can override.",
                  },
                  {
                    value: "compliance",
                    label: "Compliance",
                    description: "Nobody, including the root account, can delete before retention ends.",
                  },
                ]}
              />
              <div className="max-w-xs">
                {text("Keep archives for (days)", form.archiveDays, set("archiveDays"), {
                  type: "number",
                  hint: "Empty keeps them forever (the default).",
                  mono: false,
                })}
              </div>
            </>
          )}
          <Switch
            label="Hash chain"
            description="Each event carries the hash of the previous one, so gaps and edits are detectable."
            checked={form.hashChain}
            disabled={!writable}
            onCheckedChange={set("hashChain")}
          />
        </fieldset>
        <Facts
          rows={[
            ["Last archive", policy.last_archive_at ? formatWhen(policy.last_archive_at) : "None yet"],
            ...(policy.last_archive_error
              ? ([
                  [
                    "Last error",
                    <span key="e" className="text-danger">
                      {policy.last_archive_error}
                    </span>,
                  ],
                ] as const)
              : []),
          ]}
        />
        {check.data && (
          <Callout
            tone={check.data.ok ? "insight" : "danger"}
            title={check.data.ok ? "Test write succeeded" : "Test write failed"}
          >
            {check.data.ok
              ? `Wrote and deleted a test object${check.data.latency_ms != null ? ` in ${String(check.data.latency_ms)} ms` : ""}.`
              : (check.data.error ?? "The store refused the write.")}
          </Callout>
        )}
      </Section>
      {(save.error ?? check.error) && (
        <Callout tone="danger">{describeError(save.error ?? check.error).reason}</Callout>
      )}
      {writable && (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save retention"}
          </Button>
          <Button
            variant="secondary"
            disabled={!form.archive || check.isPending}
            onClick={() => {
              check.mutate({ body: retentionBody(form) });
            }}
          >
            {check.isPending ? "Writing…" : "Test write"}
          </Button>
          {policy.updated_at && (
            <span className="text-[12px] text-fg-muted">Last changed {formatWhen(policy.updated_at)}</span>
          )}
        </div>
      )}
    </form>
  );
}

function ArchivesCard({ writable }: { writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const archives = useQuery(withQueryFn(auditListArchivesOptions()));
  const restore = useMutation({
    ...withReauth(reauth, auditRestoreArchiveMutation()),
    onSuccess: async (data) => {
      toast(
        data.status === "restored"
          ? `${data.month} is searchable again`
          : `Restoring ${data.month}: it becomes searchable in a few minutes`,
      );
      await queryClient.invalidateQueries({ queryKey: auditListArchivesQueryKey() });
    },
  });
  const columns: Column<ArchiveOut>[] = [
    { id: "month", header: "Month", cell: (row) => <span className="font-mono">{row.month}</span> },
    { id: "events", header: "Events", align: "right", cell: (row) => formatCount(row.event_count) },
    { id: "size", header: "Size", align: "right", cell: (row) => formatBytes(row.bytes) },
    {
      id: "sha",
      header: "SHA-256",
      cell: (row) => (
        <span className="font-mono text-[12px] text-fg-secondary" title={row.sha256}>
          {row.sha256.slice(0, 12)}…
        </span>
      ),
    },
    { id: "archived", header: "Archived", cell: (row) => formatWhen(row.archived_at) },
    {
      id: "purge",
      header: "Kept until",
      cell: (row) => (row.purge_after ? formatWhen(row.purge_after) : "Forever"),
    },
    {
      id: "restore",
      header: <span className="sr-only">Restore</span>,
      align: "right",
      cell: (row) =>
        row.restored ? (
          <Badge tone="success" title="Read-only; dropped again automatically">
            Searchable until {row.restore_expires_at ? formatWhen(row.restore_expires_at) : "—"}
          </Badge>
        ) : writable ? (
          <Button
            size="28"
            variant="ghost"
            aria-label={`Restore ${row.month} for search`}
            disabled={restore.isPending}
            onClick={() => {
              restore.mutate({ path: { month: row.month } });
            }}
          >
            Restore for search
          </Button>
        ) : null,
    },
  ];
  return (
    <Section
      title="Archived months"
      description="Restoring loads a month back as a read-only partition for 7 days, then it's dropped again."
    >
      {archives.isPending ? (
        <LoadingRows rows={2} label="Loading archives" />
      ) : archives.isError ? (
        <ErrorState reason={describeError(archives.error).reason} />
      ) : (
        <DataTable
          label="Archived months"
          columns={columns}
          rows={archives.data}
          rowKey={(row) => row.month}
          empty={<p className="text-[13px] text-fg-muted">Nothing archived yet.</p>}
        />
      )}
      {restore.error && <Callout tone="danger">{describeError(restore.error).reason}</Callout>}
    </Section>
  );
}

export function RetentionSection() {
  const { writable, note } = useWritable("settings:write");
  const policy = useQuery(withQueryFn(auditGetPolicyOptions()));
  return (
    <div className="flex flex-col gap-5">
      {note}
      {policy.isPending ? (
        <LoadingRows rows={4} label="Loading retention" />
      ) : policy.isError ? (
        <ErrorState reason={describeError(policy.error).reason} onRetry={() => void policy.refetch()} />
      ) : (
        <PolicyForm key={policy.data.updated_at ?? "initial"} policy={policy.data} writable={writable} />
      )}
      <ArchivesCard writable={writable} />
    </div>
  );
}
