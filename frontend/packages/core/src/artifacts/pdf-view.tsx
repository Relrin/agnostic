// PDF pages drawn to canvases by pdf.js. No text or annotation layers: they write HTML, which the app's Trusted
// Types policy refuses, and a canvas cannot run anything a crafted file carries. pdf.js 6 never compiles font
// programs to script, and XFA forms and embedded fonts are off.
import { Button, Callout, LoadingRows } from "@agnostic/ui";
import { ChevronLeft, ChevronRight, Minus, Plus } from "lucide-react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2] as const;

async function openDocument(data: ArrayBuffer): Promise<PDFDocumentLoadingTask> {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  return pdfjs.getDocument({
    data: new Uint8Array(data),
    enableXfa: false,
    disableFontFace: true,
    useSystemFonts: false,
  });
}

function Page({ document, number, zoom }: { document: PDFDocumentProxy; number: number; zoom: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    let task: { cancel: () => void } | undefined;
    void document.getPage(number).then((page) => {
      const element = canvas.current;
      if (cancelled || !element) return;
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: zoom * ratio });
      element.width = Math.floor(viewport.width);
      element.height = Math.floor(viewport.height);
      element.style.width = `${String(Math.floor(viewport.width / ratio))}px`;
      element.style.height = `${String(Math.floor(viewport.height / ratio))}px`;
      const rendering = page.render({ canvas: element, viewport });
      task = rendering;
      rendering.promise.catch(() => undefined);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [document, number, zoom]);
  return (
    <canvas
      ref={canvas}
      aria-label={`Page ${String(number)}`}
      className="bg-white mx-auto block rounded-[2px] shadow-popover"
    />
  );
}

export function PdfView({ data }: { data: ArrayBuffer }) {
  const [document, setDocument] = useState<PDFDocumentProxy>();
  const [error, setError] = useState<string>();
  const [zoomIndex, setZoomIndex] = useState(2);
  const [page, setPage] = useState(1);

  // One document per mount: the viewer is keyed by the file, so a new file is a new PdfView.
  useEffect(() => {
    const run: { cancelled: boolean; task?: PDFDocumentLoadingTask } = { cancelled: false };
    openDocument(data.slice(0))
      .then(async (loading) => {
        run.task = loading;
        const opened = await loading.promise;
        if (!run.cancelled) setDocument(opened);
      })
      .catch((reason: unknown) => {
        if (!run.cancelled)
          setError(reason instanceof Error ? reason.message : "This PDF could not be read.");
      });
    return () => {
      run.cancelled = true;
      void run.task?.destroy();
    };
  }, [data]);

  if (error)
    return (
      <Callout tone="danger" title="This PDF could not be shown">
        {error}
      </Callout>
    );
  if (!document) return <LoadingRows rows={3} label="Opening the PDF" />;
  const zoom = ZOOMS[zoomIndex] ?? 1;
  const pages = document.numPages;
  return (
    <div className="flex min-h-0 flex-col gap-2">
      <div
        className="flex items-center gap-1 text-[12px] text-fg-muted"
        role="toolbar"
        aria-label="PDF controls"
      >
        <Button
          variant="icon"
          size="28"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => {
            setPage(page - 1);
          }}
        >
          <ChevronLeft aria-hidden />
        </Button>
        <span className="tabular-nums">
          Page {page} of {pages}
        </span>
        <Button
          variant="icon"
          size="28"
          aria-label="Next page"
          disabled={page >= pages}
          onClick={() => {
            setPage(page + 1);
          }}
        >
          <ChevronRight aria-hidden />
        </Button>
        <span className="ml-auto tabular-nums">{Math.round(zoom * 100)}%</span>
        <Button
          variant="icon"
          size="28"
          aria-label="Zoom out"
          disabled={zoomIndex === 0}
          onClick={() => {
            setZoomIndex(zoomIndex - 1);
          }}
        >
          <Minus aria-hidden />
        </Button>
        <Button
          variant="icon"
          size="28"
          aria-label="Zoom in"
          disabled={zoomIndex === ZOOMS.length - 1}
          onClick={() => {
            setZoomIndex(zoomIndex + 1);
          }}
        >
          <Plus aria-hidden />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto rounded-tile border border-border bg-surface p-3">
        <Page document={document} number={page} zoom={zoom} />
      </div>
    </div>
  );
}
