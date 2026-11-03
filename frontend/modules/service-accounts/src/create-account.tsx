// "New service account": name → principal, instances, scopes from an access role (plus extras) or a custom
// checklist with per-component entries, token kinds, expiry, user_id forwarding, a privileged-scope confirmation
// and the CLI equivalent kept in sync by the server's preview. Then each new token, shown once.
import {
  accessListRolesOptions,
  accessListScopesOptions,
  describeError,
  problemCode,
  serviceAccountsCreateAccountMutation,
  serviceAccountsPreviewAccount,
  type CreatedOut,
  type ScopeOut,
  type ServiceAccountIn,
  type ServiceAccountPreviewOut,
} from "@agnostic/api";
import { isReauthRequired, useInstances, useReauth, withQueryFn, withReauth } from "@agnostic/core";
import {
  Button,
  Callout,
  CodeBlock,
  EnvBadge,
  Field,
  Input,
  LoadingRows,
  SegmentedControl,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Switch,
  cn,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import { ReauthNotice, ShowOnce } from "./parts";
import {
  EXPIRY_OPTIONS,
  KIND_HINTS,
  KIND_LABELS,
  PER_COMPONENT_SCOPE,
  expiryDate,
  formatDate,
  isPrivileged,
  privilegedFromError,
  refreshAccounts,
  scopeFamilies,
  type Expiry,
  type TokenKind,
} from "./service-accounts-api";

type Source = "custom" | "role";

type Draft = {
  name: string;
  description: string;
  instances: string[];
  source: Source;
  roleId: string;
  scopes: string[];
  kinds: TokenKind[];
  expires: Expiry;
  forwards: boolean;
};

const EMPTY: Draft = {
  name: "",
  description: "",
  instances: [],
  source: "custom",
  roleId: "",
  scopes: [],
  kinds: ["native"],
  expires: "90d",
  forwards: false,
};

const KINDS: readonly TokenKind[] = ["native", "gateway"];

function toggle<T>(list: readonly T[], item: T): T[] {
  return list.includes(item) ? list.filter((value) => value !== item) : [...list, item];
}

function bodyOf(draft: Draft): ServiceAccountIn {
  const description = draft.description.trim();
  return {
    name: draft.name.trim(),
    ...(description ? { description } : {}),
    instances: draft.instances,
    role_id: draft.source === "role" && draft.roleId ? draft.roleId : null,
    scopes: draft.scopes,
    expires_in: draft.expires,
    kinds: draft.kinds,
    forwards_user_id: draft.forwards,
  };
}

function useSettled<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSettled(value);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [value, delay]);
  return settled;
}

/** `POST /service-accounts/preview` for the form as it stands (debounced): principal, privileged scopes, CLI. */
function usePreview(body: ServiceAccountIn) {
  const key = useSettled(JSON.stringify(body), 300);
  return useQuery({
    queryKey: ["org", "service-accounts", "preview", key],
    queryFn: async (): Promise<ServiceAccountPreviewOut> =>
      (
        await serviceAccountsPreviewAccount({
          body: JSON.parse(key) as ServiceAccountIn,
          throwOnError: true,
        })
      ).data,
    staleTime: 60_000,
    retry: false,
    placeholderData: (previous) => previous,
  });
}

function ScopeRow({
  scope,
  description,
  checked,
  onToggle,
}: {
  scope: string;
  description: ReactNode;
  checked: boolean;
  onToggle: () => void;
}) {
  const hintId = useId();
  const privileged = isPrivileged(scope);
  return (
    <label className="flex cursor-pointer items-start gap-2 py-0.5 text-[13px]">
      <input
        type="checkbox"
        className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
        aria-label={scope}
        aria-describedby={hintId}
        checked={checked}
        onChange={onToggle}
      />
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
        <code className={cn("font-mono text-[12.5px]", privileged && "text-danger")}>{scope}</code>
        <span id={hintId} className={cn("text-[12px]", privileged ? "text-danger/80" : "text-fg-muted")}>
          {description}
          {privileged && " · privileged"}
        </span>
      </span>
    </label>
  );
}

/** The AgentOS scopes by family, plus typed per-component scopes (`agents:<id>:run`). */
function ScopeChecklist({
  legend,
  catalog,
  value,
  onChange,
  covered = [],
}: {
  legend: string;
  catalog: readonly ScopeOut[];
  value: readonly string[];
  onChange: (next: string[]) => void;
  /** Scopes the role already gives (shown checked and fixed). */
  covered?: readonly string[];
}) {
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | undefined>();
  const inputId = useId();
  const families = scopeFamilies(catalog);
  const known = new Set(catalog.map((scope) => scope.scope));
  const custom = value.filter((scope) => !known.has(scope));
  const add = () => {
    const scope = typed.trim();
    if (!PER_COMPONENT_SCOPE.test(scope)) {
      setError("Use kind:id:action, e.g. agents:support-triage:run (agents, teams or workflows).");
      return;
    }
    setError(undefined);
    setTyped("");
    if (!value.includes(scope)) onChange([...value, scope]);
  };

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-[13px] font-medium text-fg-secondary">{legend}</legend>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={inputId} className="text-[12px] text-fg-muted">
          One component&apos;s scope
        </label>
        <div className="flex gap-2">
          <Input
            id={inputId}
            mono
            placeholder="agents:support-triage:run"
            aria-invalid={error ? true : undefined}
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value);
              setError(undefined);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
          />
          <Button variant="outline" size="34" disabled={!typed.trim()} onClick={add}>
            Add scope
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-[12px] text-danger">
            {error}
          </p>
        )}
        {custom.length > 0 && (
          <ul aria-label="Per-component scopes" className="flex flex-wrap gap-1.5 pt-1">
            {custom.map((scope) => (
              <li
                key={scope}
                className={cn(
                  "inline-flex items-center gap-1 rounded-badge border py-0.5 pr-0.5 pl-1.5 font-mono text-[11.5px]",
                  isPrivileged(scope) ? "border-danger/40 text-danger" : "border-border text-fg-secondary",
                )}
              >
                {scope}
                <button
                  type="button"
                  aria-label={`Remove ${scope}`}
                  className="grid size-4 cursor-pointer place-items-center rounded-control text-fg-muted hover:bg-surface-hover hover:text-fg"
                  onClick={() => {
                    onChange(value.filter((item) => item !== scope));
                  }}
                >
                  <X aria-hidden className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex max-h-72 flex-col gap-3 overflow-y-auto rounded-tile border border-border bg-surface px-3 py-2.5">
        {families.map(({ family, scopes }) => (
          <div key={family} className="flex flex-col gap-0.5">
            <span className="font-mono text-[10.5px] tracking-[0.08em] text-fg-muted uppercase">
              {family}
            </span>
            {scopes.map((scope) =>
              covered.includes(scope.scope) ? (
                <p
                  key={scope.scope}
                  className="flex items-baseline gap-2 py-0.5 pl-6 text-[12px] text-fg-muted"
                >
                  <code className="font-mono text-[12.5px]">{scope.scope}</code> from the role
                </p>
              ) : (
                <ScopeRow
                  key={scope.scope}
                  scope={scope.scope}
                  description={scope.description}
                  checked={value.includes(scope.scope)}
                  onToggle={() => {
                    onChange(toggle(value, scope.scope));
                  }}
                />
              ),
            )}
          </div>
        ))}
      </div>
    </fieldset>
  );
}

function Form({ onCreated, onCancel }: { onCreated: (created: CreatedOut) => void; onCancel: () => void }) {
  const client = useQueryClient();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [confirmedFor, setConfirmedFor] = useState<string | undefined>();
  const instances = useInstances();
  const roles = useQuery(withQueryFn(accessListRolesOptions()));
  const catalog = useQuery(withQueryFn(accessListScopesOptions()));
  const reauth = useReauth();
  const create = useMutation({
    ...withReauth(reauth, serviceAccountsCreateAccountMutation()),
    onSuccess: async (data) => {
      onCreated(data);
      await refreshAccounts(client);
    },
  });
  const set = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }));
  };

  const body = bodyOf(draft);
  const preview = usePreview(body);
  const role = draft.source === "role" ? roles.data?.find((item) => item.id === draft.roleId) : undefined;
  const roleScopes = role?.scopes ?? [];
  const all = [...new Set([...roleScopes, ...draft.scopes])];
  const fromServer = [
    ...(preview.data?.privileged_scopes ?? []),
    ...(privilegedFromError(create.error) ?? []),
  ];
  const privileged = [
    ...new Set([...all.filter(isPrivileged), ...fromServer.filter((scope) => all.includes(scope))]),
  ].sort();
  const privilegedKey = privileged.join(",");
  const confirmed = privileged.length === 0 || confirmedFor === privilegedKey;
  const name = draft.name.trim();
  const principal = `sa:${name || "<name>"}`;
  const problems = name ? (preview.data?.problems ?? []) : [];
  const expiresAt = expiryDate(draft.expires);
  const valid =
    name !== "" &&
    draft.instances.length > 0 &&
    draft.kinds.length > 0 &&
    (draft.source === "role" ? Boolean(draft.roleId) : draft.scopes.length > 0) &&
    confirmed;
  const tokenCount =
    (draft.kinds.includes("native") ? draft.instances.length : 0) + (draft.kinds.includes("gateway") ? 1 : 0);
  const confirmId = useId();
  const kindsId = useId();
  const code = problemCode(create.error);

  return (
    <form
      aria-label="New service account"
      className="flex flex-col gap-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid) return;
        create.mutate({ body: { ...body, confirm_privileged: privileged.length > 0 } });
      }}
    >
      <Field
        label="Name"
        hint={
          <>
            Runs show up as <code className="font-mono text-fg-secondary">{principal}</code>
          </>
        }
        error={code === "conflict" ? describeError(create.error).reason : undefined}
      >
        {({ id, describedBy, invalid }) => (
          <Input
            id={id}
            mono
            autoComplete="off"
            placeholder="airflow-nightly"
            aria-describedby={describedBy}
            aria-invalid={invalid || undefined}
            value={draft.name}
            onChange={(event) => {
              set({ name: event.target.value });
            }}
          />
        )}
      </Field>
      <Field
        label="Description"
        hint="What calls with it, so the next person knows whether it's still needed."
      >
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            placeholder="Runs the nightly triage summary from Airflow"
            value={draft.description}
            onChange={(event) => {
              set({ description: event.target.value });
            }}
          />
        )}
      </Field>

      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-[13px] font-medium text-fg-secondary">Instances</legend>
        {instances.isPending ? (
          <LoadingRows rows={2} label="Loading instances" />
        ) : (
          (instances.data ?? []).map((instance) => (
            <label key={instance.id} className="flex cursor-pointer items-center gap-2 text-[13px]">
              <input
                type="checkbox"
                className="size-4 accent-[var(--accent)]"
                aria-label={instance.slug}
                checked={draft.instances.includes(instance.id)}
                onChange={() => {
                  set({ instances: toggle(draft.instances, instance.id) });
                }}
              />
              <code className="font-mono text-[12.5px]">{instance.slug}</code>
              <EnvBadge env={instance.env_tag} />
            </label>
          ))
        )}
      </fieldset>

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[13px] font-medium text-fg-secondary">Scopes</span>
          <SegmentedControl
            label="Scope source"
            value={draft.source}
            onValueChange={(source) => {
              set({ source });
            }}
            options={[
              { value: "role", label: "From an access role" },
              { value: "custom", label: "Custom scopes" },
            ]}
          />
        </div>
        {draft.source === "role" && (
          <Field
            label="Access role"
            hint={
              role ? (
                <>
                  Gives{" "}
                  <code className="font-mono">
                    {role.scopes.length ? role.scopes.join(", ") : "no scopes"}
                  </code>
                  . Role changes reach the account too.
                </>
              ) : (
                "The account gets the role's scopes; add extras below."
              )
            }
          >
            {({ id, describedBy }) => (
              <Select
                value={draft.roleId}
                onValueChange={(roleId) => {
                  set({ roleId });
                }}
              >
                <SelectTrigger id={id} aria-describedby={describedBy}>
                  <SelectValue placeholder="Choose a role" />
                </SelectTrigger>
                <SelectContent>
                  {(roles.data ?? []).map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
        )}
        {catalog.isError ? (
          <Callout tone="danger" title="The scope catalog didn't load">
            {describeError(catalog.error).reason}
          </Callout>
        ) : catalog.isPending ? (
          <LoadingRows rows={4} label="Loading scopes" />
        ) : (
          <ScopeChecklist
            legend={draft.source === "role" ? "Extra scopes" : "Custom scopes"}
            catalog={catalog.data}
            value={draft.scopes}
            covered={roleScopes}
            onChange={(scopes) => {
              set({ scopes });
            }}
          />
        )}
      </div>

      {privileged.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <Callout tone="danger" title="Privileged scopes">
            <code className="font-mono">{privileged.join(", ")}</code>{" "}
            {privileged.some((scope) => scope.startsWith("service_accounts:"))
              ? "lets this token mint new tokens. "
              : "lets this token change or delete data. "}
            Owners are notified and the grant is flagged in the audit log.
          </Callout>
          <label htmlFor={confirmId} className="flex cursor-pointer items-start gap-2 text-[13px]">
            <input
              id={confirmId}
              type="checkbox"
              className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
              checked={confirmed}
              onChange={(event) => {
                setConfirmedFor(event.target.checked ? privilegedKey : undefined);
              }}
            />
            I understand this account gets privileged scopes
          </label>
        </div>
      )}

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-[13px] font-medium text-fg-secondary">Tokens</legend>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-2">
          {KINDS.map((kind) => {
            const checked = draft.kinds.includes(kind);
            return (
              <label
                key={kind}
                className={cn(
                  "flex cursor-pointer gap-2 rounded-radio border px-3 py-2.5",
                  checked ? "border-accent bg-accent/6" : "border-border hover:bg-surface-hover",
                )}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 shrink-0 accent-[var(--accent)]"
                  aria-label={KIND_LABELS[kind]}
                  aria-describedby={`${kindsId}-${kind}`}
                  checked={checked}
                  onChange={() => {
                    set({ kinds: toggle(draft.kinds, kind) });
                  }}
                />
                <span className="flex flex-col gap-0.5">
                  <span className="text-[13px] font-medium">{KIND_LABELS[kind]}</span>
                  <span id={`${kindsId}-${kind}`} className="text-[12px] text-fg-muted">
                    {KIND_HINTS[kind]}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <Field label="Expires">
        {({ id }) => (
          <Select
            value={draft.expires}
            onValueChange={(value) => {
              set({ expires: value as Expiry });
            }}
          >
            <SelectTrigger id={id}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {EXPIRY_OPTIONS.map((option) => {
                const date = expiryDate(option.value);
                return (
                  <SelectItem key={option.value} value={option.value}>
                    {date ? `${option.label} · ${formatDate(date)}` : option.label}
                  </SelectItem>
                );
              })}
            </SelectContent>
          </Select>
        )}
      </Field>
      {!expiresAt && (
        <p className="-mt-3 text-[12px] text-warning">
          Tokens that never expire are flagged amber in the list.
        </p>
      )}

      <Switch
        label="Forward user_id"
        description={`Gateway calls pass the caller's user_id through, so per-user isolation applies to each of its users. Off: runs are owned by ${principal} and a user_id it sends is dropped.`}
        checked={draft.forwards}
        onCheckedChange={(forwards) => {
          set({ forwards });
        }}
      />

      {problems.length > 0 && (
        <ul aria-label="Problems" className="flex flex-col gap-1 text-[12.5px] text-warning">
          {problems.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}

      <CodeBlock
        title="CLI equivalent"
        code={preview.data?.cli_command ?? `agnostic tokens create ${name || "<name>"}`}
      />

      {create.error && isReauthRequired(create.error) ? (
        <ReauthNotice />
      ) : create.error && code !== "conflict" && !privilegedFromError(create.error) ? (
        <Callout
          tone="danger"
          title={
            code === "native_token_failed"
              ? "An instance refused the native token"
              : "The account wasn't created"
          }
        >
          {describeError(create.error).reason}
        </Callout>
      ) : null}

      <div className="sticky bottom-0 -mx-5 -mb-5 flex justify-end gap-2 border-t border-border-subtle bg-rail px-5 py-3">
        <Button variant="ghost" size="34" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="34" disabled={!valid || create.isPending}>
          {tokenCount === 1 ? "Create and show token" : "Create and show tokens"}
        </Button>
      </div>
    </form>
  );
}

/** The sheet: the form, then the tokens it created (once). */
export function CreateAccountSheet({
  open,
  onOpenChange,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** After "I've stored it": the new account's name. */
  onDone: (name: string) => void;
}) {
  const [created, setCreated] = useState<CreatedOut | undefined>();
  const close = (next: boolean) => {
    if (!next) setCreated(undefined);
    onOpenChange(next);
  };
  return (
    <Sheet open={open} onOpenChange={close}>
      <SheetContent
        className="w-[min(600px,100%)] overflow-y-auto"
        onInteractOutside={(event) => {
          event.preventDefault();
        }}
      >
        {created ? (
          <ShowOnce
            heading={`${created.account.principal} created`}
            tokens={created.tokens}
            renderTitle={(text) => <SheetTitle className="text-[17px] font-semibold">{text}</SheetTitle>}
            onDone={() => {
              const name = created.account.name;
              close(false);
              onDone(name);
            }}
          />
        ) : (
          <>
            <div className="flex flex-col gap-1 pr-8">
              <SheetTitle className="text-[16px] font-semibold">New service account</SheetTitle>
              <SheetDescription className="text-[12.5px] text-fg-secondary">
                A machine identity for CI, chat bridges and bots. Its tokens are shown once when it&apos;s
                created.
              </SheetDescription>
            </div>
            <Form
              onCreated={setCreated}
              onCancel={() => {
                close(false);
              }}
            />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
