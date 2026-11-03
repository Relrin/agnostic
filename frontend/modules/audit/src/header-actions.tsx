// The audit log's header: the SIEM streaming pill ("● Streaming to SIEM · HTTPS webhook · last event 2 s ago"),
// and the overflow menu with the hash-chain integrity check.
import {
  auditStreamStatusOptions,
  auditVerifyChainMutation,
  describeError,
  type StreamStatusOut,
  type VerifyOut,
} from "@agnostic/api";
import { formatCount, withQueryFn } from "@agnostic/core";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  cn,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Ellipsis, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { shortAgo } from "./audit-api";

export const SIEM_SETTINGS = "/org/settings/siem";

const SINK_KIND: Record<StreamStatusOut["sinks"][number]["kind"], string> = {
  https_webhook: "HTTPS webhook",
  syslog: "Syslog",
  otlp_logs: "OTLP logs",
};

/** Re-renders every `ms` so "2 s ago" keeps moving. */
function useNow(ms: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date());
    }, ms);
    return () => {
      clearInterval(timer);
    };
  }, [ms]);
  return now;
}

export function streamText(status: StreamStatusOut, now: Date = new Date()): { text: string; tone: string } {
  const enabled = status.sinks.filter((sink) => sink.enabled);
  const failing = enabled.filter((sink) => sink.status === "failing");
  const first = enabled[0] ?? status.sinks[0];
  const kind =
    enabled.length > 1 ? `${String(enabled.length)} sinks` : first ? SINK_KIND[first.kind] : "SIEM";
  const last = shortAgo(status.last_event_at, now);
  if (status.streaming && failing.length === 0)
    return {
      text: ["Streaming to SIEM", kind, last ? `last event ${last}` : undefined].filter(Boolean).join(" · "),
      tone: "bg-accent",
    };
  if (failing.length)
    return {
      text: `SIEM delivery failing · ${failing[0] ? SINK_KIND[failing[0].kind] : kind}`,
      tone: "bg-danger",
    };
  return { text: `SIEM streaming paused · ${kind}`, tone: "bg-fg-muted" };
}

/** Hidden when no sink is configured, or the status can't be read. */
export function SiemPill() {
  const status = useQuery({
    ...withQueryFn(auditStreamStatusOptions()),
    retry: false,
    refetchInterval: 15_000,
  });
  const now = useNow(5_000);
  if (!status.data || status.data.sinks.length === 0) return null;
  const { text, tone } = streamText(status.data, now);
  return (
    <Link
      to={SIEM_SETTINGS}
      className="inline-flex h-[26px] items-center gap-1.5 rounded-full border border-border-strong px-2.5 text-[12px] text-fg-secondary hover:bg-surface-hover hover:text-fg"
    >
      <span aria-hidden className={cn("size-1.5 rounded-full", tone)} />
      {text}
    </Link>
  );
}

function verifyMessage(result: VerifyOut): string {
  return result.ok
    ? `Hash chain intact · ${formatCount(result.checked)} events checked`
    : `Hash chain broken at ${result.first_broken_event_id ?? "an unknown event"} (${formatCount(result.checked)} checked)`;
}

/** "⋯": verify the tamper-evidence chain over the current date range (only shown when events carry hashes). */
export function OverflowMenu({
  since,
  until,
  onOpenEvent,
}: {
  since: string | undefined;
  until: string | undefined;
  onOpenEvent: (id: string) => void;
}) {
  const verify = useMutation({
    ...auditVerifyChainMutation(),
    onSuccess: (result) => {
      if (result.ok) {
        toast.success(verifyMessage(result));
        return;
      }
      const broken = result.first_broken_event_id;
      toast.error(verifyMessage(result), {
        ...(broken
          ? {
              action: {
                label: "Open",
                onClick: () => {
                  onOpenEvent(broken);
                },
              },
            }
          : {}),
      });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="icon" size="34" aria-label="More actions" className="border border-border-strong">
          <Ellipsis aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          disabled={verify.isPending}
          onSelect={() => {
            verify.mutate({ body: { since: since ?? null, until: until ?? null } });
          }}
        >
          <ShieldCheck aria-hidden />
          Verify integrity
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
