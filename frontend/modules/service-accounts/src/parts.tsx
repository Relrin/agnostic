// Small pieces shared by the table, the detail aside and the create sheet: instance chips, the step-up notice
// and the show-once view of freshly issued tokens.
import type { InstanceRefOut, IssuedTokenOut } from "@agnostic/api";
import { useInstances } from "@agnostic/core";
import { Button, Callout, CodeBlock, cn } from "@agnostic/ui";
import { CircleCheck } from "lucide-react";
import { useId, type ReactNode } from "react";

import { envOf, formatDate, KIND_LABELS, type EnvTag } from "./service-accounts-api";

const ENV_DOT: Record<EnvTag, string> = {
  production: "bg-warning",
  staging: "bg-info",
  development: "bg-fg-muted",
};

/** `● prod-agentos`: mono, with a dot in the instance's environment colour. */
export function InstanceChip({ instance, env }: { instance: InstanceRefOut; env: EnvTag | undefined }) {
  return (
    <span
      title={env ? `${instance.display_name} · ${env}` : instance.display_name}
      className="inline-flex items-center gap-1.5 rounded-badge border border-border px-1.5 py-0.5 font-mono text-[11.5px] whitespace-nowrap text-fg-secondary"
    >
      <span
        aria-hidden
        className={cn("size-1.5 shrink-0 rounded-full", env ? ENV_DOT[env] : "bg-fg-muted")}
      />
      {instance.slug}
    </span>
  );
}

export function InstanceChips({ instances }: { instances: readonly InstanceRefOut[] }) {
  const known = useInstances();
  if (instances.length === 0) return <span className="text-fg-muted">—</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {instances.map((instance) => (
        <InstanceChip key={instance.id} instance={instance} env={envOf(known.data, instance)} />
      ))}
    </span>
  );
}

export function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between gap-2">
        <h3 id={id} className="text-[13px] font-semibold">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A 403 `reauth_required` left over when the "Confirm it's you" dialog was dismissed (or isn't mounted). */
export function ReauthNotice() {
  const next = typeof window === "undefined" ? "/" : window.location.pathname + window.location.search;
  return (
    <Callout
      tone="warning"
      title="Confirm it's you"
      action={
        <a
          href={`/login?next=${encodeURIComponent(next)}`}
          className="text-[13px] text-info hover:text-info-hover"
        >
          Sign in again
        </a>
      }
    >
      Changes to service accounts with privileged scopes need a recent sign-in. Confirm it&apos;s you when
      asked, or sign in again, then retry.
    </Callout>
  );
}

function tokenTitle(token: IssuedTokenOut): string {
  return token.kind === "native" && token.instance
    ? `${KIND_LABELS.native} · ${token.instance.slug}`
    : KIND_LABELS[token.kind];
}

/** Tokens returned once by create, issue or rotate, with a curl sample each. */
export function ShowOnce({
  heading,
  tokens,
  note,
  renderTitle = (text) => <h2 className="text-[17px] font-semibold">{text}</h2>,
  onDone,
}: {
  /** "sa:airflow-nightly created". */
  heading: string;
  tokens: readonly IssuedTokenOut[];
  note?: ReactNode;
  /** The heading element (a dialog passes its title). */
  renderTitle?: (text: string) => ReactNode;
  onDone: () => void;
}) {
  return (
    <div role="region" aria-label="New tokens" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <p className="flex items-center gap-1.5 text-[13px] font-medium text-accent">
          <CircleCheck aria-hidden className="size-4" />
          {heading}
        </p>
        {renderTitle(tokens.length === 1 ? "Copy the token now" : "Copy the tokens now")}
      </div>
      <Callout tone="warning" title="They won't be shown again">
        {tokens.length === 1 ? "It's" : "Each is"} shown once. Afterwards only the prefix is visible; the
        token is stored as a hash.
      </Callout>
      {note}
      <ul className="flex flex-col gap-4">
        {tokens.map((token) => (
          <li key={token.id} className="flex flex-col gap-2">
            <CodeBlock title={tokenTitle(token)} code={token.token} className="border-accent/60" />
            <p className="text-[12px] text-fg-muted">
              Prefix <code className="font-mono">{token.prefix}…</code>
              {token.expires_at ? ` · expires ${formatDate(token.expires_at)}` : " · no expiry"}
            </p>
            <CodeBlock title="Use it as a bearer token" code={token.curl} />
          </li>
        ))}
      </ul>
      <div className="flex justify-end">
        <Button variant="primary" size="34" onClick={onDone}>
          I&apos;ve stored it
        </Button>
      </div>
    </div>
  );
}
