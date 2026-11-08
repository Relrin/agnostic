// Artefacts in the app: chips under the run that produced them, a list for a session or an instance, and the sheet
// that previews one with Download, Open and Share.
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  LoadingRows,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  cn,
} from "@agnostic/ui";
import { describeError } from "@agnostic/api";
import {
  Download,
  ExternalLink,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileJson,
  FileSpreadsheet,
  FileText,
  FileVideo,
  Globe,
  Share2,
  type LucideIcon,
} from "lucide-react";
import { createElement, useState, type ReactNode } from "react";

import { formatBytes, formatWhen } from "../format";
import { useCan } from "../permissions";
import {
  artifactContentUrl,
  downloadUrl,
  useSessionArtifacts,
  viewerKind,
  type Artifact,
  type ViewerKind,
} from "./api";
import { ShareDialog } from "./share-dialog";
import { ArtifactPreview } from "./viewer";

const ICONS: Record<ViewerKind, LucideIcon> = {
  markdown: FileText,
  html: Globe,
  svg: FileImage,
  image: FileImage,
  pdf: FileText,
  csv: FileSpreadsheet,
  json: FileJson,
  code: FileCode,
  text: FileText,
  audio: FileAudio,
  video: FileVideo,
  binary: FileArchive,
};

const LABELS: Record<ViewerKind, string> = {
  markdown: "Markdown",
  html: "HTML",
  svg: "SVG",
  image: "Image",
  pdf: "PDF",
  csv: "CSV",
  json: "JSON",
  code: "Code",
  text: "Text",
  audio: "Audio",
  video: "Video",
  binary: "File",
};

export function artifactIcon(artifact: Pick<Artifact, "content_type" | "filename">): LucideIcon {
  return ICONS[viewerKind(artifact.content_type, artifact.filename)];
}

/** The icon of an artefact's kind of file. */
export function ArtifactIcon({
  artifact,
  className,
}: {
  artifact: Pick<Artifact, "content_type" | "filename">;
  className?: string;
}) {
  return createElement(artifactIcon(artifact), { className, "aria-hidden": true });
}

export function artifactLabel(artifact: Pick<Artifact, "content_type" | "filename">): string {
  return LABELS[viewerKind(artifact.content_type, artifact.filename)];
}

/** A file chip: icon, name, size. */
export function ArtifactChip({ artifact, onOpen }: { artifact: Artifact; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="inline-flex max-w-[260px] cursor-pointer items-center gap-2 rounded-control border border-border bg-surface px-2.5 py-1.5 text-left text-[12.5px] hover:border-border-strong hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      aria-label={`Open ${artifact.filename}`}
    >
      <ArtifactIcon artifact={artifact} className="size-4 shrink-0 text-fg-muted" />
      <span className="truncate font-medium">{artifact.title || artifact.filename}</span>
      {artifact.size ? (
        <span className="shrink-0 text-fg-muted tabular-nums">{formatBytes(artifact.size)}</span>
      ) : null}
    </button>
  );
}

/** One artefact: what it is, Download, Open, Share, and its preview. */
export function ArtifactInspector({
  instance,
  artifact,
  heading,
}: {
  instance: string;
  artifact: Artifact;
  heading: (title: string) => ReactNode;
}) {
  const [sharing, setSharing] = useState(false);
  const canShare = useCan("artifacts:share", instance).allowed === true;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-col gap-1 pr-8">
        {heading(artifact.title || artifact.filename)}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-fg-muted">
          <Badge tone="muted">{artifactLabel(artifact)}</Badge>
          {artifact.path && <span className="font-mono">{artifact.path}</span>}
          {artifact.size ? <span>{formatBytes(artifact.size)}</span> : null}
          {artifact.revision > 1 && <span>version {artifact.revision}</span>}
          {artifact.source && <span>from {SOURCES[artifact.source] ?? artifact.source}</span>}
          {artifact.created_at && <span>{formatWhen(artifact.created_at)}</span>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2" role="toolbar" aria-label="File actions">
        <Button
          variant="outline"
          size="30"
          onClick={() => {
            downloadUrl(artifactContentUrl(instance, artifact, "attachment"), artifact.filename);
          }}
        >
          <Download aria-hidden />
          Download
        </Button>
        <Button asChild variant="ghost" size="30">
          <a href={artifactContentUrl(instance, artifact)} target="_blank" rel="noreferrer noopener">
            <ExternalLink aria-hidden />
            Open in a new tab
          </a>
        </Button>
        {canShare && (
          <Button
            variant="ghost"
            size="30"
            onClick={() => {
              setSharing(true);
            }}
          >
            <Share2 aria-hidden />
            Share…
          </Button>
        )}
      </div>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <ArtifactPreview
          key={artifact.storage_key}
          source={{
            url: artifactContentUrl(instance, artifact),
            filename: artifact.filename,
            contentType: artifact.content_type,
            size: artifact.size,
          }}
        />
      </div>
      <ShareDialog instance={instance} artifact={artifact} open={sharing} onOpenChange={setSharing} />
    </div>
  );
}

const SOURCES: Record<string, string> = {
  e2b: "E2B sandbox",
  docker: "Docker sandbox",
  sandbox: "sandbox checkpoint",
  directory: "workspace",
};

/** The sheet that previews one artefact. */
export function ArtifactSheet({
  instance,
  artifact,
  onOpenChange,
}: {
  instance: string;
  artifact: Artifact | undefined;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={artifact !== undefined} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[min(920px,100%)] gap-3">
        <SheetDescription className="sr-only">Preview, download and share this file.</SheetDescription>
        {artifact && (
          <ArtifactInspector
            instance={instance}
            artifact={artifact}
            heading={(title) => (
              <SheetTitle className="truncate text-[15px] font-semibold">{title}</SheetTitle>
            )}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

/** The artefacts of one run, under its response. */
export function RunArtifacts({
  instance,
  sessionId,
  runId,
}: {
  instance: string;
  sessionId: string | undefined;
  runId: string | undefined;
}) {
  const artifacts = useSessionArtifacts(instance, sessionId);
  const [open, setOpen] = useState<Artifact>();
  const own = (artifacts.data ?? []).filter((artifact) => runId !== undefined && artifact.run_id === runId);
  if (own.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11.5px] font-medium text-fg-muted">
        {own.length === 1 ? "1 file" : `${String(own.length)} files`}
      </span>
      <div className="flex flex-wrap gap-1.5" aria-label="Files from this run">
        {own.map((artifact) => (
          <ArtifactChip
            key={artifact.storage_key}
            artifact={artifact}
            onOpen={() => {
              setOpen(artifact);
            }}
          />
        ))}
      </div>
      <ArtifactSheet
        instance={instance}
        artifact={open}
        onOpenChange={(next) => {
          if (!next) setOpen(undefined);
        }}
      />
    </div>
  );
}

/** Rows of artefacts (a session's, or an instance's newest). */
export function ArtifactRows({
  artifacts,
  onOpen,
  selected,
  showSession = false,
}: {
  artifacts: readonly Artifact[];
  onOpen: (artifact: Artifact) => void;
  selected?: string | undefined;
  showSession?: boolean;
}) {
  return (
    <ul className="flex flex-col" aria-label="Files">
      {artifacts.map((artifact) => {
        return (
          <li key={`${artifact.session_id}/${artifact.storage_key}`}>
            <button
              type="button"
              aria-current={selected === artifact.storage_key ? "true" : undefined}
              onClick={() => {
                onOpen(artifact);
              }}
              className={cn(
                "flex w-full cursor-pointer items-center gap-2.5 rounded-control px-2 py-1.5 text-left text-[12.5px] hover:bg-surface-hover",
                selected === artifact.storage_key && "bg-surface-hover",
              )}
            >
              <ArtifactIcon artifact={artifact} className="size-4 shrink-0 text-fg-muted" />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-medium">{artifact.title || artifact.filename}</span>
                <span className="truncate text-[11.5px] text-fg-muted">
                  {[
                    artifact.path ?? artifact.filename,
                    artifact.size ? formatBytes(artifact.size) : undefined,
                    showSession ? artifact.component_id : undefined,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              {artifact.created_at && (
                <span className="shrink-0 text-[11.5px] text-fg-muted">
                  {formatWhen(artifact.created_at)}
                </span>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** A session's artefacts with the viewer: the Files tab of Chat and Sessions. */
export function SessionArtifacts({ instance, sessionId }: { instance: string; sessionId: string }) {
  const artifacts = useSessionArtifacts(instance, sessionId);
  const [open, setOpen] = useState<Artifact>();
  if (artifacts.isPending) return <LoadingRows rows={3} label="Loading files" />;
  if (artifacts.isError) return <ErrorState {...describeError(artifacts.error)} />;
  if (artifacts.data.length === 0)
    return (
      <EmptyState title="No files yet">
        Files the agent writes or publishes show up here, with a preview, a download and a share link.
      </EmptyState>
    );
  return (
    <>
      <ArtifactRows artifacts={artifacts.data} onOpen={setOpen} selected={open?.storage_key} />
      <ArtifactSheet
        instance={instance}
        artifact={open}
        onOpenChange={(next) => {
          if (!next) setOpen(undefined);
        }}
      />
    </>
  );
}
