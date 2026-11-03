// CodeEditor and CelEditor load CodeMirror on first render (their own chunks), showing a skeleton meanwhile.
import { lazy, Suspense } from "react";

import { CodeViewSkeleton } from "./code-view";
import type { CelEditorProps, CodeEditorProps } from "./types";

const loadCode = () => import("./code-editor-impl");
const loadCel = () => import("./cel-editor-impl");
const LazyCodeEditor = lazy(loadCode);
const LazyCelEditor = lazy(loadCel);

/** Start fetching the editor chunks early. */
export function preloadCodeEditor(): void {
  void loadCode();
  void loadCel();
}

/** Editable Python or JSON: edits reach `onChange`, diagnostics show in the gutter, code-owned lines are tinted. */
export function CodeEditor(props: CodeEditorProps) {
  return (
    <Suspense fallback={<CodeViewSkeleton className={props.className} />}>
      <LazyCodeEditor {...props} />
    </Suspense>
  );
}

/** One CEL expression, with completion and hover docs for its context and the checker's findings. */
export function CelEditor(props: CelEditorProps) {
  return (
    <Suspense fallback={<CodeViewSkeleton lines={2} className={props.className} />}>
      <LazyCelEditor {...props} />
    </Suspense>
  );
}
