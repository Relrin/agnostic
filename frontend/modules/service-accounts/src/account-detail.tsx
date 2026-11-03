// The service-account aside: scopes and where they come from, the instances it applies on, how its runs are
// attributed, and its tokens (native per instance, gateway) with rotate, revoke and issue; plus deleting the account.
import {
  describeError,
  serviceAccountsDeleteAccountMutation,
  serviceAccountsGetAccountOptions,
  serviceAccountsGetAccountQueryKey,
  serviceAccountsIssueTokenMutation,
  serviceAccountsRevokeTokenMutation,
  type GatewayTokenOut,
  type NativeTokenOut,
  type ScopeItemOut,
  type ServiceAccountDetailOut,
  type TokenIssuedOut,
} from "@agnostic/api";
import {
  formatRelative,
  formatWhen,
  isReauthRequired,
  useCan,
  useInstances,
  useReauth,
  withQueryFn,
  withReauth,
} from "@agnostic/core";
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
  ErrorState,
  LoadingRows,
  RadioCards,
  StatusPill,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, X } from "lucide-react";
import { useState } from "react";

import { InstanceChip, InstanceChips, ReauthNotice, Section, ShowOnce } from "./parts";
import { envOf, expiryState, formatDate, refreshAccounts, type TokenKind } from "./service-accounts-api";

const ASIDE =
  "flex w-[460px] max-w-full shrink-0 flex-col gap-5 overflow-y-auto border-l border-border-subtle p-5";

type AnyToken = NativeTokenOut | GatewayTokenOut;

function isGateway(token: AnyToken): token is GatewayTokenOut {
  return token.kind === "gateway";
}

/** A gateway token replaced by a rotation, still valid until `grace_until`. */
function inGrace(token: AnyToken): boolean {
  return isGateway(token) && token.status === "active" && token.grace_until !== null;
}

function MutationError({ error }: { error: unknown }) {
  if (!error) return null;
  if (isReauthRequired(error)) return <ReauthNotice />;
  return (
    <Callout tone="danger" title="That didn't work">
      {describeError(error).reason}
    </Callout>
  );
}

/** "Created 12 Aug 2026 · last used 2 s ago from 10.0.4.12" (or when and why it stopped). */
function tokenMeta(token: AnyToken): string {
  const parts: string[] = [];
  if (token.status === "revoked") {
    const rotated = isGateway(token) && token.revoke_reason === "rotated";
    parts.push(`Revoked ${formatDate(token.revoked_at)}${rotated ? " when rotated" : ""}`);
  } else if (token.status === "expired") {
    parts.push(`Expired ${formatDate(token.revoked_at ?? (isGateway(token) ? null : token.expires_at))}`);
  } else {
    parts.push(`Created ${formatDate(token.created_at)}`);
  }
  if (token.last_used_at) {
    const ip = isGateway(token) && token.last_used_ip ? ` from ${token.last_used_ip}` : "";
    parts.push(`last used ${formatRelative(token.last_used_at)}${ip}`);
  } else if (token.status === "active") {
    parts.push("never used");
  }
  if (!isGateway(token) && token.status === "active" && token.expires_at)
    parts.push(`expires ${formatDate(token.expires_at)}`);
  return parts.join(" · ");
}

function RevokeButton({
  account,
  token,
  label,
}: {
  account: ServiceAccountDetailOut;
  token: AnyToken;
  label: string;
}) {
  const client = useQueryClient();
  const reauth = useReauth();
  const [confirming, setConfirming] = useState(false);
  const revoke = useMutation({
    ...withReauth(reauth, serviceAccountsRevokeTokenMutation()),
    onSuccess: async (data) => {
      client.setQueryData(serviceAccountsGetAccountQueryKey({ path: { account: account.name } }), data);
      toast.success(`${token.prefix}… revoked`);
      await refreshAccounts(client);
    },
  });
  if (!confirming)
    return (
      <Button
        variant="destructive-outline"
        size="28"
        aria-label={`Revoke ${token.prefix}`}
        onClick={() => {
          setConfirming(true);
        }}
      >
        {label}
      </Button>
    );
  return (
    <div className="flex basis-full flex-col gap-2">
      <span className="flex items-center gap-1">
        <Button
          variant="destructive-text"
          size="28"
          disabled={revoke.isPending}
          onClick={() => {
            revoke.mutate({ path: { account: account.name, token: token.id } });
          }}
        >
          Revoke {token.prefix}…
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
      </span>
      <MutationError error={revoke.error} />
    </div>
  );
}

function TokenCard({
  account,
  token,
  canManage,
  onRotate,
}: {
  account: ServiceAccountDetailOut;
  token: AnyToken;
  canManage: boolean;
  onRotate: (token: AnyToken) => void;
}) {
  const instances = useInstances();
  const grace = inGrace(token);
  const active = token.status === "active";
  return (
    <li
      aria-label={`Token ${token.prefix}`}
      className={cn(
        "flex flex-col gap-2 rounded-tile border px-3.5 py-3",
        active ? "border-border" : "border-border-subtle",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <KeyRound aria-hidden className="size-3.5 shrink-0 text-fg-muted" />
          <code className={cn("font-mono text-[12.5px]", !active && "text-fg-muted")}>{token.prefix}…</code>
          {!isGateway(token) && token.instance && (
            <InstanceChip instance={token.instance} env={envOf(instances.data, token.instance)} />
          )}
        </span>
        {grace ? <Badge tone="warning">ROTATING OUT</Badge> : <StatusPill status={token.status} />}
      </div>
      <p className="text-[12px] text-fg-muted">{tokenMeta(token)}</p>
      {grace && isGateway(token) && (
        <p className="text-[12px] text-warning">
          Replaced by a rotation; keeps working until {formatWhen(token.grace_until)}.
        </p>
      )}
      {canManage && active && (
        <div className="flex flex-wrap gap-1.5">
          {!grace && (
            <Button
              variant="outline"
              size="28"
              aria-label={`Rotate ${token.prefix}`}
              onClick={() => {
                onRotate(token);
              }}
            >
              Rotate
            </Button>
          )}
          <RevokeButton account={account} token={token} label={grace ? "Revoke now" : "Revoke"} />
        </div>
      )}
    </li>
  );
}

type TokenChoice = { value: string; kind: TokenKind; instance: string | null; label: string; hint: string };

/** What "Issue token" can add: a native token on each instance without one, a gateway token if there is none. */
function missingTokens(account: ServiceAccountDetailOut): TokenChoice[] {
  const choices: TokenChoice[] = account.instances
    .filter(
      (instance) =>
        !account.native_tokens.some(
          (token) => token.status === "active" && token.instance?.id === instance.id,
        ),
    )
    .map((instance) => ({
      value: `native:${instance.id}`,
      kind: "native",
      instance: instance.slug,
      label: `Native · ${instance.slug}`,
      hint: "An agno_pat_ token created on the instance.",
    }));
  if (!account.gateway_tokens.some((token) => token.status === "active"))
    choices.push({
      value: "gateway",
      kind: "gateway",
      instance: null,
      label: "Gateway",
      hint: "An agn_pat_ token for the Agnostic gateway.",
    });
  return choices;
}

type TokenAction = { mode: "rotate"; token: AnyToken } | { mode: "issue" };

/** Rotate (with what happens to callers spelled out) or issue a token; then the token, once. */
function TokenDialog({
  account,
  action,
  onClose,
}: {
  account: ServiceAccountDetailOut;
  action: TokenAction;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const choices = action.mode === "issue" ? missingTokens(account) : [];
  const [choice, setChoice] = useState(choices[0]?.value ?? "");
  const [result, setResult] = useState<TokenIssuedOut | undefined>();
  const reauth = useReauth();
  const issue = useMutation({
    ...withReauth(reauth, serviceAccountsIssueTokenMutation()),
    onSuccess: async (data) => {
      setResult(data);
      client.setQueryData(
        serviceAccountsGetAccountQueryKey({ path: { account: account.name } }),
        data.account,
      );
      await refreshAccounts(client);
    },
  });

  const submit = () => {
    if (action.mode === "rotate") {
      const token = action.token;
      issue.mutate({
        path: { account: account.name },
        body: isGateway(token)
          ? { kind: "gateway" }
          : { kind: "native", instance: token.instance?.slug ?? token.instance?.id ?? null },
      });
      return;
    }
    const picked = choices.find((item) => item.value === choice);
    if (!picked) return;
    issue.mutate({
      path: { account: account.name },
      body: picked.kind === "gateway" ? { kind: "gateway" } : { kind: "native", instance: picked.instance },
    });
  };

  const rotating = action.mode === "rotate" ? action.token : undefined;
  const title = rotating ? `Rotate ${rotating.prefix}…?` : "Issue a token";

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        className="max-w-xl"
        onInteractOutside={(event) => {
          // A shown token stays until the person says they stored it.
          if (result) event.preventDefault();
        }}
      >
        {result ? (
          <ShowOnce
            heading={
              result.replaced_id ? `${account.principal} token rotated` : `${account.principal} token issued`
            }
            tokens={[result.token]}
            renderTitle={(text) => <DialogTitle className="text-[17px]">{text}</DialogTitle>}
            note={
              result.grace_until ? (
                <p className="text-[12.5px] text-fg-secondary">
                  The old token keeps working until {formatWhen(result.grace_until)}.
                </p>
              ) : undefined
            }
            onDone={onClose}
          />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
              <DialogDescription>
                {rotating
                  ? isGateway(rotating)
                    ? "A new gateway token is issued now and the old one keeps working for 24 h, so callers can switch."
                    : `A native token can't be rotated in place: ${rotating.instance?.slug ?? "the instance"} revokes it and creates a new one, so callers see a brief gap.`
                  : `A new token for ${account.principal}, shown once.`}
              </DialogDescription>
            </DialogHeader>
            {rotating ? (
              <p className="text-[12.5px] text-fg-muted">{account.rotation_note}</p>
            ) : choices.length ? (
              <RadioCards
                legend="Token"
                value={choice}
                onValueChange={setChoice}
                options={choices.map((item) => ({
                  value: item.value,
                  label: item.label,
                  description: item.hint,
                }))}
              />
            ) : (
              <p className="text-[13px] text-fg-secondary">
                Every instance has a native token and there is a gateway token. Rotate one instead.
              </p>
            )}
            <MutationError error={issue.error} />
            <DialogFooter>
              <Button variant="ghost" size="32" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="32"
                disabled={issue.isPending || (!rotating && !choices.length)}
                onClick={submit}
              >
                {rotating ? "Rotate token" : "Issue token"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DeleteDialog({
  account,
  onClose,
  onDeleted,
}: {
  account: ServiceAccountDetailOut;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const client = useQueryClient();
  const reauth = useReauth();
  const remove = useMutation({
    ...withReauth(reauth, serviceAccountsDeleteAccountMutation()),
    onSuccess: async () => {
      toast.success(`${account.principal} deleted`);
      onDeleted();
      await refreshAccounts(client);
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {account.principal}?</DialogTitle>
          <DialogDescription>
            Its native tokens are revoked on{" "}
            {account.instances.map((item) => item.slug).join(", ") || "every instance"} and its gateway tokens
            stop working at once. Runs it already made stay attributed to {account.principal} in traces and
            the audit log.
          </DialogDescription>
        </DialogHeader>
        <MutationError error={remove.error} />
        <DialogFooter>
          <Button variant="ghost" size="32" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive-outline"
            size="32"
            disabled={remove.isPending}
            onClick={() => {
              remove.mutate({ path: { account: account.name } });
            }}
          >
            Delete account
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function sourceHeading(
  source: string,
  scopeSource: ServiceAccountDetailOut["scope_source"],
): string | undefined {
  if (source.startsWith("role:")) return `From the ${source.slice(5)} role`;
  return scopeSource === "role" ? "Extra scopes" : undefined;
}

function ScopeList({ detail }: { detail: ServiceAccountDetailOut }) {
  const groups = new Map<string, ScopeItemOut[]>();
  for (const item of detail.scope_items) groups.set(item.source, [...(groups.get(item.source) ?? []), item]);
  if (groups.size === 0) return <p className="text-[12.5px] text-fg-muted">No scopes.</p>;
  return (
    <div className="flex flex-col gap-2.5">
      {[...groups].map(([source, items]) => {
        const heading = sourceHeading(source, detail.scope_source);
        return (
          <div key={source} className="flex flex-col gap-1.5">
            {heading && <span className="text-[12px] text-fg-muted">{heading}</span>}
            <ul aria-label={heading ?? "Scopes"} className="flex flex-wrap gap-1.5">
              {items.map((item) => (
                <li
                  key={item.scope}
                  title={item.privileged ? "Privileged scope" : undefined}
                  className={cn(
                    "rounded-badge border px-1.5 py-0.5 font-mono text-[11.5px]",
                    item.privileged ? "border-danger/40 text-danger" : "border-border text-fg-secondary",
                  )}
                >
                  {item.scope}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function TokenGroup({
  title,
  tokens,
  empty,
  ...props
}: {
  title: string;
  tokens: readonly AnyToken[];
  empty: string;
  account: ServiceAccountDetailOut;
  canManage: boolean;
  onRotate: (token: AnyToken) => void;
}) {
  // Active first (rotating-out after current), then revoked and expired, newest first within each.
  const order = (token: AnyToken) => (token.status === "active" ? (inGrace(token) ? 1 : 0) : 2);
  const sorted = [...tokens].sort((a, b) => order(a) - order(b) || b.created_at.localeCompare(a.created_at));
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[12px] font-medium text-fg-muted">{title}</span>
      {sorted.length === 0 ? (
        <p className="text-[12.5px] text-fg-muted">{empty}</p>
      ) : (
        <ul aria-label={title} className="flex flex-col gap-2">
          {sorted.map((token) => (
            <TokenCard key={token.id} token={token} {...props} />
          ))}
        </ul>
      )}
    </div>
  );
}

function DetailBody({
  detail,
  onClose,
  onDeleted,
}: {
  detail: ServiceAccountDetailOut;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const canManage = useCan("service_accounts:manage").allowed === true;
  const [action, setAction] = useState<TokenAction | undefined>();
  const [deleting, setDeleting] = useState(false);
  const expiry = expiryState(detail);
  const canIssue = canManage && !detail.expired && missingTokens(detail).length > 0;
  const onRotate = (token: AnyToken) => {
    setAction({ mode: "rotate", token });
  };

  return (
    <>
      <header className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <Avatar id={detail.id} name={detail.name} kind="machine" size={32} />
            <div className="flex min-w-0 flex-col">
              <h2 className="truncate text-[17px] font-semibold">{detail.name}</h2>
              <code className="font-mono text-[12px] text-fg-muted">{detail.principal}</code>
            </div>
          </div>
          <Button variant="icon" size="28" aria-label="Close service account" onClick={onClose}>
            <X aria-hidden />
          </Button>
        </div>
        {detail.description && <p className="text-[13px] text-fg-secondary">{detail.description}</p>}
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[12px] text-fg-muted">
          {detail.privileged && <Badge tone="danger">PRIVILEGED</Badge>}
          <span>
            Created {formatDate(detail.created_at)} by {detail.created_by.name}
          </span>
          <span aria-hidden>·</span>
          <span
            className={cn(
              expiry.tone === "danger" && "text-danger",
              expiry.tone === "warning" && "text-warning",
            )}
          >
            {expiry.tone === "danger" || expiry.text === "No expiry" ? expiry.text : `Expires ${expiry.text}`}
          </span>
        </p>
      </header>

      {detail.expired && (
        <Callout tone="danger" title="This account has expired">
          Its tokens no longer work. Create a new service account to keep calling these instances.
        </Callout>
      )}

      <Section
        title="Scopes"
        action={<span className="text-[12px] text-fg-muted">{detail.source_label}</span>}
      >
        <ScopeList detail={detail} />
      </Section>

      <Section title="Applies on">
        <InstanceChips instances={detail.instances} />
        <p className="text-[12.5px] text-fg-secondary">{detail.isolation_note}</p>
      </Section>

      <Section
        title="Tokens"
        action={
          canIssue ? (
            <Button
              variant="ghost"
              size="28"
              onClick={() => {
                setAction({ mode: "issue" });
              }}
            >
              <Plus aria-hidden />
              Issue token
            </Button>
          ) : undefined
        }
      >
        <TokenGroup
          title="Native · per instance"
          tokens={detail.native_tokens}
          empty="No native tokens."
          account={detail}
          canManage={canManage}
          onRotate={onRotate}
        />
        <TokenGroup
          title="Gateway"
          tokens={detail.gateway_tokens}
          empty="No gateway token."
          account={detail}
          canManage={canManage}
          onRotate={onRotate}
        />
        <p className="text-[12px] text-fg-muted">{detail.rotation_note}</p>
      </Section>

      {canManage && (
        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border-subtle pt-4">
          <code className="font-mono text-[11.5px] text-fg-muted">delete → service_accounts:manage</code>
          <Button
            variant="destructive-text"
            size="30"
            onClick={() => {
              setDeleting(true);
            }}
          >
            Delete account
          </Button>
        </div>
      )}

      {action && (
        <TokenDialog
          key={action.mode === "rotate" ? action.token.id : "issue"}
          account={detail}
          action={action}
          onClose={() => {
            setAction(undefined);
          }}
        />
      )}
      {deleting && (
        <DeleteDialog
          account={detail}
          onClose={() => {
            setDeleting(false);
          }}
          onDeleted={onDeleted}
        />
      )}
    </>
  );
}

/** `GET /service-accounts/{account}`, then the detail. */
export function AccountDetail({
  account,
  onClose,
  onDeleted,
}: {
  account: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const detail = useQuery(withQueryFn(serviceAccountsGetAccountOptions({ path: { account } })));
  return (
    <aside aria-label="Service account details" aria-busy={detail.isPending} className={ASIDE}>
      {detail.isPending ? (
        <LoadingRows rows={6} label="Loading service account" />
      ) : detail.isError ? (
        <>
          <div className="flex justify-end">
            <Button variant="icon" size="28" aria-label="Close service account" onClick={onClose}>
              <X aria-hidden />
            </Button>
          </div>
          <ErrorState {...describeError(detail.error)} onRetry={() => void detail.refetch()} />
        </>
      ) : (
        <DetailBody detail={detail.data} onClose={onClose} onDeleted={onDeleted} />
      )}
    </aside>
  );
}
