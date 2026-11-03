// The event aside: decision, the action and a one-sentence summary, the request's fields, what changed, why a
// denial happened (and, for admins or the person denied, a way to temporary access), and deep links.
import {
  accessExplain,
  auditGetEventOptions,
  describeError,
  type AuditEventOut,
  type ExplanationOut,
  type InstanceOut,
} from "@agnostic/api";
import { useCan, useMe, withQueryFn } from "@agnostic/core";
import {
  ArgsDiff,
  Avatar,
  Badge,
  Button,
  ErrorState,
  JsonView,
  KeyValueList,
  LoadingRows,
  ScopeDiff,
  cn,
} from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { AccessDialog, type AccessMode } from "./access-dialog";
import {
  SOURCE_LABELS,
  avatarKind,
  diffView,
  eventLinks,
  isMachine,
  responseText,
  scopesToGrant,
} from "./audit-api";

const ASIDE =
  "flex w-[460px] max-w-full shrink-0 flex-col gap-5 overflow-y-auto border-l border-border-subtle p-5";

/** Granting temporary access needs the same scope as editing bindings. */
const GRANT_SCOPE = "org:roles:write";

function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("flex flex-col gap-2.5", className)}>
      <h3 id={id} className="text-[13px] font-semibold">
        {title}
      </h3>
      {children}
    </section>
  );
}

export function DecisionBadge({ decision }: { decision: AuditEventOut["decision"] }) {
  if (decision === "allowed") return <Badge tone="success">ALLOWED</Badge>;
  if (decision === "denied") return <Badge tone="danger">DENIED</Badge>;
  return <Badge tone="muted">RECORDED</Badge>;
}

function DiffSection({ event }: { event: AuditEventOut }) {
  const view = diffView(event.diff);
  if (!view) return null;
  return (
    <Section title={view.title ?? "Changes"}>
      <div className="rounded-tile border border-border-subtle bg-surface px-3.5 py-3">
        {view.kind === "lines" ? (
          <ScopeDiff lines={view.lines} label={view.title ?? "Changes"} />
        ) : view.kind === "args" ? (
          <ArgsDiff before={view.before} after={view.after} />
        ) : (
          <JsonView value={view.value} label={view.title ?? "Changes"} />
        )}
      </div>
      {view.kind !== "json" && view.note && <p className="text-[12px] text-fg-muted">{view.note}</p>}
    </Section>
  );
}

/** The explain engine's answer for the scope that was missing, as the actor. */
function useExplanation(event: AuditEventOut, enabled: boolean) {
  const scope = scopesToGrant(event)[0];
  const kind = event.actor.kind;
  const canExplain = enabled && Boolean(scope) && (kind === "user" || kind === "service_account");
  return useQuery<ExplanationOut>({
    queryKey: ["audit", "explain", event.id],
    queryFn: async () =>
      (
        await accessExplain({
          body: {
            user_id: event.actor.id,
            principal_kind: kind === "service_account" ? "service_account" : "user",
            display_name: event.actor.display,
            scope: scope ?? null,
            instance: event.instance_id,
            action: event.action,
          },
          throwOnError: true,
        })
      ).data,
    enabled: canExplain,
    retry: false,
    staleTime: 5 * 60_000,
  });
}

function WhyDenied({ event, instanceName }: { event: AuditEventOut; instanceName: string | undefined }) {
  const me = useMe();
  const canGrant = useCan(GRANT_SCOPE).allowed === true;
  const explanation = useExplanation(event, true);
  const [mode, setMode] = useState<AccessMode | undefined>(undefined);
  const missing = scopesToGrant(event);
  const own = me.data?.id === event.actor.id;
  const offer: AccessMode | undefined = event.can_request_access
    ? canGrant
      ? "grant"
      : own
        ? "request"
        : undefined
    : undefined;
  const alternatives = explanation.data?.alternatives ?? [];
  const reason =
    event.denial_reason ??
    explanation.data?.explanation ??
    (explanation.isPending && explanation.fetchStatus !== "idle"
      ? undefined
      : `${event.resource_display ?? "This request"} needed ${missing.join(", ") || "a scope the caller doesn't hold"}${
          instanceName ? ` on ${instanceName}` : ""
        }.`);

  return (
    <section
      aria-label="Why it was denied"
      className="flex flex-col gap-2 rounded-tile border border-danger/35 bg-danger/5 px-3.5 py-3 text-[13px]"
    >
      <h3 className="font-semibold text-fg">Why it was denied</h3>
      {reason ? (
        <p className="text-fg-secondary">
          {reason.split("`").map((part, index) =>
            index % 2 === 1 ? (
              <code key={index} className="font-mono text-[12px] text-fg">
                {part}
              </code>
            ) : (
              part
            ),
          )}
        </p>
      ) : (
        <LoadingRows rows={1} label="Explaining the denial" />
      )}
      {alternatives.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[12px] text-fg-muted">It would be allowed with</span>
          <ul aria-label="Would be allowed with" className="flex flex-col gap-0.5 text-[12.5px]">
            {alternatives.map((alternative) => (
              <li key={`${alternative.kind}:${alternative.label}`} className="text-fg-secondary">
                {alternative.label}
              </li>
            ))}
          </ul>
        </div>
      )}
      {offer && (
        <div className="pt-1">
          <Button
            variant={offer === "grant" ? "primary" : "secondary"}
            size="32"
            onClick={() => {
              setMode(offer);
            }}
          >
            {offer === "grant" ? "Grant temporary access…" : "Request access"}
          </Button>
        </div>
      )}
      {mode && (
        <AccessDialog
          mode={mode}
          event={event}
          instanceName={instanceName}
          open
          onOpenChange={(open) => {
            if (!open) setMode(undefined);
          }}
        />
      )}
    </section>
  );
}

function ActorValue({ event }: { event: AuditEventOut }) {
  const machine = isMachine(event.actor.kind);
  return (
    <span className="flex items-start gap-2">
      <Avatar
        id={event.actor.id}
        name={event.actor.display}
        kind={avatarKind(event.actor.kind)}
        size={20}
        className="mt-px"
      />
      <span className="min-w-0">
        <span className={cn("block", machine && "font-mono text-[12px]")}>{event.actor.display}</span>
        {event.actor.id !== event.actor.display && (
          <span className="block font-mono text-[11.5px] text-fg-muted">{event.actor.id}</span>
        )}
      </span>
    </span>
  );
}

function DetailBody({
  event,
  instance,
  onClose,
}: {
  event: AuditEventOut;
  instance: InstanceOut | undefined;
  onClose: () => void;
}) {
  const instanceName = instance?.slug ?? event.instance_id ?? undefined;
  const links = eventLinks(event, instance?.slug);
  const fields = [
    { key: "time", label: "Time", value: event.occurred_at, mono: true },
    { key: "request", label: "Request id", value: event.request_id ?? "—", mono: true },
    { key: "actor", label: "Actor", value: <ActorValue event={event} /> },
    { key: "via", label: "Via", value: event.via },
    { key: "ip", label: "IP", value: event.ip ?? "—", mono: true },
    { key: "client", label: "Client", value: event.client ?? "—" },
    {
      key: "source",
      label: "Source",
      value: (
        <>
          {SOURCE_LABELS[event.source]}
          {event.source_event_id && (
            <span className="block font-mono text-[11.5px] text-fg-muted">{event.source_event_id}</span>
          )}
        </>
      ),
    },
    {
      key: "resource",
      label: "Resource",
      value: event.resource_display ?? event.resource_id ?? "—",
      mono: true,
    },
    { key: "where", label: "Where", value: instanceName ?? "org", mono: true },
    ...(event.scope_checked
      ? [{ key: "scope", label: "Scope checked", value: event.scope_checked, mono: true }]
      : []),
    ...(event.response_status !== null
      ? [{ key: "response", label: "Response", value: responseText(event.response_status) }]
      : []),
    ...(event.hash ? [{ key: "hash", label: "Hash", value: event.hash, mono: true }] : []),
  ];

  return (
    <>
      <header className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <DecisionBadge decision={event.decision} />
          <Button variant="icon" size="28" aria-label="Close event" onClick={onClose}>
            <X aria-hidden />
          </Button>
        </div>
        <h2 className="font-mono text-[17px] font-semibold break-all">{event.action}</h2>
        <p className="text-[13px] text-fg-secondary">{event.summary}</p>
      </header>

      <KeyValueList
        className="grid-cols-[110px_1fr]"
        items={fields.map((field) => ({ ...field, value: field.value ?? "—" }))}
      />

      <DiffSection event={event} />

      {event.decision === "denied" && <WhyDenied event={event} instanceName={instanceName} />}

      {links.length > 0 && (
        <nav aria-label="Related" className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px]">
          {links.map((link) => (
            <Link
              key={link.key}
              to={link.to}
              search={link.search}
              className="inline-flex items-center gap-1 text-info hover:text-info-hover"
            >
              {link.label}
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          ))}
        </nav>
      )}
    </>
  );
}

/** The aside for `?event=`: from the loaded page when it's there, `GET /audit/events/{id}` otherwise. */
export function EventDetail({
  eventId,
  loaded,
  listSettled,
  instances,
  onClose,
}: {
  eventId: string;
  loaded: AuditEventOut | undefined;
  /** The list has answered: an event that isn't on the loaded pages is fetched on its own. */
  listSettled: boolean;
  instances: readonly InstanceOut[] | undefined;
  onClose: () => void;
}) {
  const fetched = useQuery({
    ...withQueryFn(auditGetEventOptions({ path: { event_id: eventId } })),
    enabled: !loaded && listSettled,
  });
  const event = loaded ?? fetched.data;
  const instance = event?.instance_id ? instances?.find((item) => item.id === event.instance_id) : undefined;
  return (
    <aside aria-label="Event details" aria-busy={!event && fetched.isPending} className={ASIDE}>
      {event ? (
        <DetailBody event={event} instance={instance} onClose={onClose} />
      ) : fetched.isError && listSettled ? (
        <>
          <div className="flex justify-end">
            <Button variant="icon" size="28" aria-label="Close event" onClick={onClose}>
              <X aria-hidden />
            </Button>
          </div>
          <ErrorState {...describeError(fetched.error)} onRetry={() => void fetched.refetch()} />
        </>
      ) : (
        <LoadingRows rows={6} label="Loading event" />
      )}
    </aside>
  );
}
