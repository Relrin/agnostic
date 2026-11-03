// "Export view": the current filters as CSV or JSONL. Up to 10 000 rows download straight away; a larger range (the
// API answers 413) or the "large range" choice runs as a background export that's kept for 24 hours.
import {
  apiUrl,
  auditGetExportOptions,
  auditListExportsOptions,
  auditListExportsQueryKey,
  auditRequestExportMutation,
  describeError,
  isProblem,
  type ExportOut,
} from "@agnostic/api";
import { formatBytes, formatCount, formatRelative, withQueryFn } from "@agnostic/core";
import {
  Button,
  Callout,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  SegmentedControl,
  StatusPill,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { eventsQuery, exportPath, type AuditFilters } from "./audit-api";

type Format = "csv" | "jsonl";
const FORMATS = [
  { value: "csv", label: "CSV" },
  { value: "jsonl", label: "JSONL" },
] as const;
const POLL_MS = 1500;
const SYNC_LIMIT = "10,000";

export function downloadHref(job: Pick<ExportOut, "id" | "download_url">): string {
  const url = job.download_url ?? `/api/v1/audit/exports/${encodeURIComponent(job.id)}/download`;
  return url.startsWith("/") ? apiUrl(url) : url;
}

function filenameOf(disposition: string | null, fallback: string): string {
  const match = disposition ? /filename="?([^";]+)"?/.exec(disposition) : null;
  return match?.[1] ?? fallback;
}

/** Saves a fetched body as a file (the anchor's own download can't tell a 413 from a file). */
function saveBlob(blob: Blob, name: string): void {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = name;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

function JobStatus({ job }: { job: ExportOut }) {
  const running = job.status === "queued" || job.status === "running";
  return (
    <div
      role="status"
      aria-label="Background export"
      className="flex flex-col gap-1.5 rounded-tile border border-border px-3.5 py-3 text-[12.5px]"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          {running && <LoaderCircle className="size-3.5 animate-spin text-fg-muted" aria-hidden />}
          <span className="font-mono">{job.id}</span>
        </span>
        <StatusPill status={job.status} />
      </div>
      {running && (
        <p className="text-fg-secondary">
          {job.status === "queued" ? "Waiting for a worker…" : "Writing events…"} You can close this; the
          export stays under Recent exports for 24 hours.
        </p>
      )}
      {job.status === "done" && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-fg-secondary">
            {formatCount(job.row_count)} events
            {job.size_bytes !== null ? ` · ${formatBytes(job.size_bytes)}` : ""}
          </span>
          <Button asChild variant="primary" size="30">
            <a href={downloadHref(job)} download>
              <Download aria-hidden />
              Download {job.format.toUpperCase()}
            </a>
          </Button>
        </div>
      )}
      {job.status === "failed" && <p className="text-danger">{job.error ?? "The export failed."}</p>}
    </div>
  );
}

function RecentExports({ exclude }: { exclude: string | undefined }) {
  const exports = useQuery({ ...withQueryFn(auditListExportsOptions()), retry: false });
  const rows = (exports.data ?? []).filter((job) => job.id !== exclude).slice(0, 5);
  if (rows.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12px] text-fg-muted">Recent exports · kept 24 hours</span>
      <ul aria-label="Recent exports" className="flex flex-col divide-y divide-divider-row text-[12.5px]">
        {rows.map((job) => (
          <li key={job.id} className="flex items-center justify-between gap-2 py-1.5">
            <span className="min-w-0 truncate">
              <span className="font-mono">{job.format.toUpperCase()}</span>{" "}
              <span className="text-fg-muted">· {formatRelative(job.created_at)}</span>
            </span>
            {job.status === "done" ? (
              <a href={downloadHref(job)} download className="text-info hover:text-info-hover">
                Download
              </a>
            ) : (
              <StatusPill status={job.status} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ExportDialog({
  open,
  onOpenChange,
  filters,
  summary,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: AuditFilters;
  summary: string;
}) {
  const client = useQueryClient();
  const [format, setFormat] = useState<Format>("csv");
  const [downloading, setDownloading] = useState(false);
  const [tooLarge, setTooLarge] = useState(false);
  const [jobId, setJobId] = useState<string | undefined>(undefined);
  const href = apiUrl(exportPath(format, filters));

  const start = useMutation({
    ...auditRequestExportMutation(),
    onSuccess: async (job) => {
      setJobId(job.id);
      await client.invalidateQueries({ queryKey: auditListExportsQueryKey() });
    },
    onError: (error) => toast.error(describeError(error).reason),
  });
  const job = useQuery({
    ...withQueryFn(auditGetExportOptions({ path: { export_id: jobId ?? "" } })),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "failed" ? false : POLL_MS;
    },
  });

  const downloadNow = async () => {
    setDownloading(true);
    try {
      const response = await fetch(href, { credentials: "same-origin" });
      if (response.status === 413) {
        setTooLarge(true);
        return;
      }
      if (!response.ok) {
        const body: unknown = await response.json().catch(() => undefined);
        toast.error(
          isProblem(body) ? describeError(body).reason : `Export failed (${String(response.status)}).`,
        );
        return;
      }
      saveBlob(
        await response.blob(),
        filenameOf(response.headers.get("Content-Disposition"), `audit.${format}`),
      );
      onOpenChange(false);
    } catch (error) {
      toast.error(describeError(error).reason);
    } finally {
      setDownloading(false);
    }
  };
  const runInBackground = () => {
    start.mutate({ body: { format, filters: eventsQuery(filters) } });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) {
          setTooLarge(false);
          setJobId(undefined);
        }
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Export view</DialogTitle>
          <DialogDescription>
            The events that match the current filters, newest first. Exports are audited.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <p className="rounded-tile border border-border-subtle px-3 py-2 font-mono text-[12px] text-fg-secondary">
            {summary}
          </p>
          <SegmentedControl
            label="Format"
            value={format}
            options={FORMATS}
            onValueChange={(value) => {
              setFormat(value);
            }}
          />
          {tooLarge && !jobId && (
            <Callout tone="warning" title="Too many events to download directly">
              Direct downloads stop at {SYNC_LIMIT} events. Run it in the background; it&apos;s ready to
              download in a minute or two.
            </Callout>
          )}
          {jobId && job.data && <JobStatus job={job.data} />}
          {jobId && !job.data && (
            <p role="status" className="text-[12.5px] text-fg-muted">
              Starting the export…
            </p>
          )}
          {open && <RecentExports exclude={jobId} />}
        </div>
        <DialogFooter className="flex-wrap">
          <DialogClose asChild>
            <Button variant="outline" size="32" className="mr-auto">
              Close
            </Button>
          </DialogClose>
          <Button
            variant={tooLarge ? "primary" : "secondary"}
            size="32"
            disabled={start.isPending || Boolean(jobId)}
            onClick={runInBackground}
          >
            {start.isPending ? "Starting…" : "Run in background (large range)"}
          </Button>
          {!tooLarge && (
            <Button asChild variant="primary" size="32">
              <a
                href={href}
                download
                aria-disabled={downloading || undefined}
                onClick={(click) => {
                  click.preventDefault();
                  if (!downloading) void downloadNow();
                }}
              >
                <Download aria-hidden />
                {downloading ? "Preparing…" : `Download ${format.toUpperCase()}`}
              </a>
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
