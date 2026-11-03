import type { Ref } from "react";

export type CodeLanguage = "python" | "json";

/** How a line differs from the saved version: drawn as a 3px strip next to the line numbers. */
export type ChangeMark = "added" | "modified";

/** A diagnostic or hint shown as a block under `line`, with a wavy underline on columns `from..to`. */
export type CodeNote = {
  /** 1-based line number. */
  line: number;
  /** 0-based column where the underline starts. */
  from: number;
  /** 0-based column where the underline ends (exclusive). */
  to: number;
  text: string;
  action?: { label: string; href: string } | undefined;
};

/** Lines from `from` to `to`, 1-based and inclusive. */
export type LineRange = { from: number; to: number };

/** A problem found in the code, shown underlined and in the lint gutter. Lines are 1-based, columns 0-based. */
export type CodeDiagnostic = {
  line: number;
  column: number;
  endLine: number;
  endColumn: number;
  severity: "error" | "warning" | "info";
  message: string;
};

export type CodeViewProps = {
  value: string;
  language: CodeLanguage;
  /** Change marks by 1-based line number. */
  marks?: Record<number, ChangeMark> | undefined;
  /** 1-based line to highlight and scroll into view (e.g. the line a form field maps to). */
  focusLine?: number | undefined;
  /** Lines to highlight instead of one (e.g. the lines of a selected workflow step); wins over `focusLine`. */
  focusRange?: LineRange | undefined;
  notes?: readonly CodeNote[] | undefined;
  /** Called when the cursor moves, with a 1-based line and column. */
  onCursor?: ((line: number, col: number) => void) | undefined;
  ariaLabel: string;
  className?: string | undefined;
};

export type CodeEditorProps = CodeViewProps & {
  /** Called with the whole document after every edit. */
  onChange: (value: string) => void;
  diagnostics?: readonly CodeDiagnostic[] | undefined;
  /** Lines set in code in a way the form can't edit, tinted so they read as code-owned. */
  ownedLines?: readonly LineRange[] | undefined;
  readOnly?: boolean | undefined;
};

/** A variable or function the expression editor completes and explains on hover. */
export type CelSymbol = {
  name: string;
  /** A variable's type ("map<string, string>") or a function's signature. */
  detail: string;
  doc: string;
  kind: "variable" | "function" | "method" | "macro";
};

/** A finding on an expression, by character offsets. */
export type CelDiagnostic = {
  from: number;
  to: number;
  severity: "error" | "warning" | "info";
  message: string;
};

export type CelEditorHandle = {
  /** Insert text at the cursor (or over the selection) and focus the editor. */
  insert: (text: string) => void;
  focus: () => void;
};

export type CelEditorProps = {
  value: string;
  onChange: (value: string) => void;
  symbols: readonly CelSymbol[];
  diagnostics?: readonly CelDiagnostic[] | undefined;
  ariaLabel: string;
  placeholder?: string | undefined;
  readOnly?: boolean | undefined;
  className?: string | undefined;
  ref?: Ref<CelEditorHandle> | undefined;
};
