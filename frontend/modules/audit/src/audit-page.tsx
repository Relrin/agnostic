import { auditListEventsInfiniteOptions, describeError, type AuditEventOut } from "@agnostic/api";
import { useInstances } from "@agnostic/core";
import {
  Badge,
  Button,
  CodeBlock,
  EmptyState,
  ErrorState,
  Input,
  LoadingRows,
  PageIntro,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@agnostic/ui";
import { skipToken, useInfiniteQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

type Decision = AuditEventOut["decision"];
const ANY = "__any__";
const DECISION_TONE = { allowed: "success", denied: "danger", n_a: "muted" } as const;

function DecisionPill({ decision, scope }: { decision: Decision; scope: string | null }) {
  if (decision === "n_a") return <span className="text-fg-muted">—</span>;
  return (
    <span className="flex flex-col gap-0.5">
      <Badge tone={DECISION_TONE[decision]}>{decision}</Badge>
      {scope && <span className="font-mono text-[11px] text-fg-muted">{scope}</span>}
    </span>
  );
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[11.5px] tracking-[0.06em] text-fg-muted uppercase">{label}</dt>
      <dd className="text-[13px] break-words">{children}</dd>
    </div>
  );
}

function EventAside({
  event,
  instance,
  onClose,
}: {
  event: AuditEventOut;
  instance: string | undefined;
  onClose: () => void;
}) {
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent className="w-[min(520px,100%)] overflow-y-auto">
        <SheetTitle className="pr-8 text-[16px] font-semibold">{event.summary}</SheetTitle>
        <SheetDescription className="font-mono text-[12px] text-fg-muted">
          {event.id} · {new Date(event.occurred_at).toLocaleString()}
        </SheetDescription>
        {event.decision === "denied" && (
          <div className="rounded-tile border border-danger/35 bg-danger/5 px-3.5 py-3 text-[13px]">
            <div className="font-semibold">Why it was denied</div>
            <p className="text-fg-secondary">
              {event.resource_display ? `${event.resource_display} ` : ""}needed{" "}
              <code className="font-mono">{event.missing_scopes.join(", ") || event.scope_checked}</code>
              {instance ? ` on ${instance}` : ""}. Ask an Owner or Administrator for a role that includes it.
            </p>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          <Detail label="Actor">
            {event.actor.display}
            <span className="block font-mono text-[11.5px] text-fg-muted">{event.actor.id}</span>
          </Detail>
          <Detail label="Action">
            <span className="font-mono">{event.action}</span>
          </Detail>
          <Detail label="Resource">{event.resource_display ?? event.resource_id ?? "—"}</Detail>
          <Detail label="Instance">{instance ?? "org"}</Detail>
          <Detail label="Decision">
            <DecisionPill decision={event.decision} scope={event.scope_checked} />
          </Detail>
          <Detail label="Status">{event.response_status ?? "—"}</Detail>
          <Detail label="Via">{event.via}</Detail>
          <Detail label="IP">{event.ip ?? "—"}</Detail>
          <Detail label="Request id">
            <span className="font-mono text-[12px]">{event.request_id ?? "—"}</span>
          </Detail>
          <Detail label="Client">{event.client ?? "—"}</Detail>
        </dl>
        {event.diff && <CodeBlock title="Before / after" code={JSON.stringify(event.diff, null, 2)} />}
      </SheetContent>
    </Sheet>
  );
}

/** `/access/audit`: who did what, where, and whether it was allowed. */
export function AuditPage() {
  const instances = useInstances();
  const [action, setAction] = useState("");
  const [decision, setDecision] = useState<string>(ANY);
  const [instance, setInstance] = useState<string>(ANY);
  const [selected, setSelected] = useState<AuditEventOut | undefined>(undefined);

  const options = auditListEventsInfiniteOptions({
    query: {
      limit: 50,
      ...(action.trim() ? { action: action.trim() } : {}),
      ...(decision !== ANY ? { decision: decision as Decision } : {}),
      ...(instance !== ANY ? { instance } : {}),
    },
  });
  const events = useInfiniteQuery({
    ...options,
    queryFn: options.queryFn ?? skipToken,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const nameOf = (id: string | null) =>
    id ? (instances.data?.find((item) => item.id === id)?.display_name ?? id) : undefined;
  const rows = events.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <div className="mx-auto flex w-full max-w-[1320px] flex-col gap-6 px-8 pt-6 pb-10">
      <PageIntro title="Audit log">
        Every change in the control plane and every gateway write or denial, with who, where and why. Reads
        are sampled unless the org logs all reads.
      </PageIntro>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          aria-label="Filter by action"
          mono
          placeholder="Action, e.g. gateway.* or members.update"
          className="max-w-[320px]"
          value={action}
          onChange={(event) => {
            setAction(event.target.value);
          }}
        />
        <Select value={decision} onValueChange={setDecision}>
          <SelectTrigger aria-label="Decision" className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any decision</SelectItem>
            <SelectItem value="allowed">Allowed</SelectItem>
            <SelectItem value="denied">Denied</SelectItem>
          </SelectContent>
        </Select>
        <Select value={instance} onValueChange={setInstance}>
          <SelectTrigger aria-label="Instance" className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any instance</SelectItem>
            {(instances.data ?? []).map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {events.isPending ? (
        <LoadingRows rows={8} label="Loading events" />
      ) : events.isError ? (
        <ErrorState reason={describeError(events.error).reason} onRetry={() => void events.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title="No events match">Try a broader filter.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-card border border-border">
          <table className="w-full min-w-[900px] text-left text-[13px]">
            <thead className="border-b border-border-subtle text-[11.5px] tracking-[0.06em] text-fg-muted uppercase">
              <tr>
                <th className="px-4 py-2.5 font-medium">Time</th>
                <th className="px-4 py-2.5 font-medium">Actor</th>
                <th className="px-4 py-2.5 font-medium">Action</th>
                <th className="px-4 py-2.5 font-medium">Where</th>
                <th className="px-4 py-2.5 font-medium">Decision</th>
                <th className="px-4 py-2.5 font-medium">Summary</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-divider-row">
              {rows.map((event) => (
                <tr
                  key={event.id}
                  className="cursor-pointer bg-surface hover:bg-surface-hover"
                  onClick={() => {
                    setSelected(event);
                  }}
                >
                  <td className="px-4 py-2.5 font-mono text-[12px] whitespace-nowrap">
                    {new Date(event.occurred_at).toLocaleTimeString()}
                    <span className="block text-[11px] text-fg-muted">
                      {new Date(event.occurred_at).toLocaleDateString()}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">{event.actor.display}</td>
                  <td className="px-4 py-2.5 font-mono text-[12px]">{event.action}</td>
                  <td className="px-4 py-2.5">{nameOf(event.instance_id) ?? "org"}</td>
                  <td className="px-4 py-2.5">
                    <DecisionPill
                      decision={event.decision}
                      scope={event.decision === "denied" ? event.missing_scopes.join(", ") : null}
                    />
                  </td>
                  <td className="px-4 py-2.5 text-fg-secondary">
                    <button
                      type="button"
                      className="cursor-pointer text-left hover:underline"
                      onClick={() => {
                        setSelected(event);
                      }}
                    >
                      {event.summary}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {events.hasNextPage && (
        <div>
          <Button disabled={events.isFetchingNextPage} onClick={() => void events.fetchNextPage()}>
            {events.isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
      {selected && (
        <EventAside
          event={selected}
          instance={nameOf(selected.instance_id)}
          onClose={() => {
            setSelected(undefined);
          }}
        />
      )}
    </div>
  );
}
