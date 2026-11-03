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

export type CodeViewProps = {
  value: string;
  language: CodeLanguage;
  /** Change marks by 1-based line number. */
  marks?: Record<number, ChangeMark> | undefined;
  /** 1-based line to highlight and scroll into view (e.g. the line a form field maps to). */
  focusLine?: number | undefined;
  notes?: readonly CodeNote[] | undefined;
  /** Called when the cursor moves, with a 1-based line and column. */
  onCursor?: ((line: number, col: number) => void) | undefined;
  ariaLabel: string;
  className?: string | undefined;
};
