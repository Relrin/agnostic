// The artefact viewer: one preview per kind of file, plus its source where that helps.
//
// - Markdown, code, CSV, JSON and text are read as text and rendered by the app (Markdown without raw HTML).
// - Images and SVG are shown with <img>: an SVG loaded as an image cannot run script.
// - Audio and video play from the artefact URL.
// - PDFs are drawn to canvases by pdf.js.
// - HTML is the only kind that runs anything: in a sandboxed frame with an opaque origin, from a response whose
//   own policy forbids every network request, so it can neither read the app's cookies nor call its API.
import { Callout, LoadingRows, MarkdownView, SegmentedControl, JsonView } from "@agnostic/ui";
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { formatBytes } from "../format";
import { codeLanguage, fetchArtifact, viewerKind, type ViewerKind } from "./api";
import { parseCsv } from "./csv";

const PdfView = lazy(() => import("./pdf-view").then((module) => ({ default: module.PdfView })));

/** Text previews stop here; the full file is one click away (Download). */
const MAX_TEXT = 2 * 1024 * 1024;

export type ArtifactSource = {
  /** Serves the bytes for viewing (the isolated `inline` route). */
  url: string;
  filename: string;
  contentType: string;
  size?: number | null | undefined;
};

type Mode = "preview" | "source";

const WITH_SOURCE: ReadonlySet<ViewerKind> = new Set(["markdown", "html", "svg", "csv", "json"]);

function useBlob(url: string, enabled: boolean) {
  return useQuery({
    queryKey: ["artifact-bytes", url],
    queryFn: ({ signal }) => fetchArtifact(url, signal),
    enabled,
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
    retry: false,
  });
}

function useText(blob: Blob | undefined) {
  return useQuery({
    queryKey: ["artifact-text", blob],
    queryFn: async () => {
      if (!blob) return { text: "", truncated: false };
      const truncated = blob.size > MAX_TEXT;
      return { text: await (truncated ? blob.slice(0, MAX_TEXT) : blob).text(), truncated };
    },
    enabled: blob !== undefined,
    staleTime: Infinity,
  });
}

function useObjectUrl(blob: Blob | undefined): string | undefined {
  const url = useMemo(() => (blob ? URL.createObjectURL(blob) : undefined), [blob]);
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );
  return url;
}

function CsvTable({ text }: { text: string }) {
  const [header, ...rows] = parseCsv(text);
  if (!header) return <p className="text-[12.5px] text-fg-muted">Empty file.</p>;
  return (
    <div className="overflow-auto rounded-tile border border-border">
      <table className="w-full border-collapse font-mono text-[11.5px]" aria-label="CSV preview">
        <thead>
          <tr className="bg-surface text-left text-fg-muted">
            {header.map((cell, index) => (
              <th key={index} scope="col" className="border-b border-border-subtle px-2 py-1.5 font-medium">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-divider-row last:border-0">
              {row.map((cell, column) => (
                <td key={column} className="px-2 py-1.5 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Source({ text, language }: { text: string; language?: string | undefined }) {
  const fence = "`".repeat(
    Math.max(
      3,
      (text.match(/`+/g) ?? []).reduce((max, run) => Math.max(max, run.length + 1), 3),
    ),
  );
  return (
    <MarkdownView className="text-[12.5px]">{`${fence}${language ?? ""}\n${text}\n${fence}`}</MarkdownView>
  );
}

function parsedJson(text: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch {
    return { ok: false };
  }
}

function TextPreview({
  kind,
  text,
  filename,
  mode,
}: {
  kind: ViewerKind;
  text: string;
  filename: string;
  mode: Mode;
}) {
  if (mode === "source" || kind === "text") {
    const language =
      kind === "code"
        ? codeLanguage(filename)
        : kind === "html" || kind === "svg"
          ? "html"
          : kind === "json"
            ? "json"
            : kind === "markdown"
              ? "markdown"
              : undefined;
    return <Source text={text} language={language} />;
  }
  if (kind === "markdown") return <MarkdownView>{text}</MarkdownView>;
  if (kind === "csv") return <CsvTable text={text} />;
  if (kind === "json") {
    const parsed = parsedJson(text);
    return parsed.ok ? (
      <JsonView value={parsed.value} label={filename} />
    ) : (
      <Source text={text} language="json" />
    );
  }
  return <Source text={text} language={codeLanguage(filename)} />;
}

function HtmlFrame({ url, filename }: { url: string; filename: string }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5">
      <iframe
        title={`Preview of ${filename}`}
        src={url}
        // No allow-same-origin: the page gets an opaque origin, away from the app's cookies and storage.
        sandbox="allow-scripts allow-popups"
        referrerPolicy="no-referrer"
        className="bg-white min-h-[420px] w-full flex-1 rounded-tile border border-border"
      />
      <p className="text-[11.5px] text-fg-muted">
        Isolated preview: the page runs in a sandbox without access to this app, your session or the network.
      </p>
    </div>
  );
}

function BinaryNotice({ source }: { source: ArtifactSource }) {
  return (
    <Callout tone="info" title="No preview for this kind of file">
      {source.contentType}
      {source.size ? ` · ${formatBytes(source.size)}` : ""}. Download it to open it with another app.
    </Callout>
  );
}

/** Preview of one artefact. `kind` defaults to what its type and name say. */
export function ArtifactPreview({ source }: { source: ArtifactSource }) {
  const kind = viewerKind(source.contentType, source.filename);
  const [mode, setMode] = useState<Mode>("preview");
  const needsBytes =
    kind !== "audio" && kind !== "video" && kind !== "binary" && !(kind === "html" && mode === "preview");
  const blob = useBlob(source.url, needsBytes);
  const textual = ["markdown", "csv", "json", "code", "text"].includes(kind) || mode === "source";
  const text = useText(textual ? blob.data : undefined);
  const objectUrl = useObjectUrl(kind === "image" || kind === "svg" ? blob.data : undefined);
  const pdfBytes = useQuery({
    queryKey: ["artifact-pdf", blob.data],
    queryFn: () => (blob.data ? blob.data.arrayBuffer() : Promise.resolve(new ArrayBuffer(0))),
    enabled: kind === "pdf" && blob.data !== undefined,
    staleTime: Infinity,
  });

  let body: React.ReactNode;
  if (needsBytes && blob.isPending) body = <LoadingRows rows={4} label={`Loading ${source.filename}`} />;
  else if (needsBytes && blob.isError)
    body = (
      <Callout tone="danger" title="This file could not be loaded">
        {blob.error instanceof Error ? blob.error.message : "The instance did not return it."}
      </Callout>
    );
  else if (textual) {
    body = text.data ? (
      <>
        {text.data.truncated && (
          <Callout tone="info">
            Showing the first {formatBytes(MAX_TEXT)}; download the file for all of it.
          </Callout>
        )}
        <TextPreview kind={kind} text={text.data.text} filename={source.filename} mode={mode} />
      </>
    ) : (
      <LoadingRows rows={3} label="Reading the file" />
    );
  } else if (kind === "html") body = <HtmlFrame url={source.url} filename={source.filename} />;
  else if ((kind === "image" || kind === "svg") && objectUrl)
    body = (
      <div className="grid place-items-center rounded-tile border border-border bg-[repeating-conic-gradient(var(--color-surface)_0%_25%,transparent_0%_50%)] bg-[length:16px_16px] p-3">
        <img src={objectUrl} alt={source.filename} className="max-h-[70vh] max-w-full object-contain" />
      </div>
    );
  else if (kind === "audio")
    body = (
      <audio controls src={source.url} className="w-full" aria-label={source.filename}>
        <track kind="captions" />
      </audio>
    );
  else if (kind === "video")
    body = (
      <video
        controls
        src={source.url}
        className="bg-black max-h-[70vh] w-full rounded-tile"
        aria-label={source.filename}
      >
        <track kind="captions" />
      </video>
    );
  else if (kind === "pdf")
    body = pdfBytes.data ? (
      <Suspense fallback={<LoadingRows rows={3} label="Loading the PDF viewer" />}>
        <PdfView data={pdfBytes.data} />
      </Suspense>
    ) : (
      <LoadingRows rows={3} label="Opening the PDF" />
    );
  else body = <BinaryNotice source={source} />;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {WITH_SOURCE.has(kind) && (
        <SegmentedControl
          label="Show"
          size="mini"
          className="self-start"
          value={mode}
          onValueChange={setMode}
          options={[
            { value: "preview", label: kind === "html" ? "Rendered" : "Preview" },
            { value: "source", label: "Source" },
          ]}
        />
      )}
      {body}
    </div>
  );
}
