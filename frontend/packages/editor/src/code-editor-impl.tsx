// The CodeMirror side of CodeEditor: like CodeView, one EditorView per mount kept in sync through compartments, plus
// edits reported to `onChange`, diagnostics in the lint gutter and code-owned lines. A `value` that differs from what
// the person typed (the server rewrote the code after a form edit) replaces the document; typing never round-trips.
import { setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { Compartment, EditorState, type Text } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { cn } from "@agnostic/ui";
import { useEffect, useRef } from "react";

import {
  changeMarks,
  codeNotes,
  editableExtensions,
  focusLine,
  languageExtension,
  lineRange,
  ownedLines,
} from "./extensions";
import type { CodeDiagnostic, CodeEditorProps } from "./types";

const NO_MARKS = {};
const NO_NOTES: CodeEditorProps["notes"] = [];
const NO_DIAGNOSTICS: CodeEditorProps["diagnostics"] = [];
const NO_OWNED: CodeEditorProps["ownedLines"] = [];

/** Offsets of a diagnostic in `doc`, clamped to the document. */
export function diagnosticRange(doc: Text, item: CodeDiagnostic): { from: number; to: number } {
  const clampLine = (line: number) => Math.min(Math.max(line, 1), doc.lines);
  const start = doc.line(clampLine(item.line));
  const end = doc.line(clampLine(item.endLine));
  const from = start.from + Math.min(Math.max(item.column, 0), start.length);
  const to = end.from + Math.min(Math.max(item.endColumn, 0), end.length);
  return to > from ? { from, to } : { from, to: Math.min(from + 1, doc.length) };
}

function lint(doc: Text, items: readonly CodeDiagnostic[]): Diagnostic[] {
  return items.map((item) => ({
    ...diagnosticRange(doc, item),
    severity: item.severity,
    message: item.message,
  }));
}

export default function CodeEditorImpl({
  value,
  onChange,
  language,
  marks = NO_MARKS,
  focusLine: line,
  focusRange,
  notes = NO_NOTES,
  diagnostics = NO_DIAGNOSTICS,
  ownedLines: owned = NO_OWNED,
  readOnly = false,
  onCursor,
  ariaLabel,
  className,
}: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView>(undefined);
  const typed = useRef(value);
  const focus = lineRange(line, focusRange);
  const focusFrom = focus?.from;
  const focusTo = focus?.to;
  const compartments = useRef({
    language: new Compartment(),
    marks: new Compartment(),
    focus: new Compartment(),
    notes: new Compartment(),
    owned: new Compartment(),
    readOnly: new Compartment(),
    label: new Compartment(),
  });
  const handlers = useRef({ onChange, onCursor });
  useEffect(() => {
    handlers.current = { onChange, onCursor };
  }, [onChange, onCursor]);

  useEffect(() => {
    if (!host.current) return;
    const parts = compartments.current;
    const created = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          editableExtensions(),
          parts.language.of(languageExtension(language)),
          parts.marks.of(changeMarks.of(marks)),
          parts.focus.of(focusLine.of(focus)),
          parts.notes.of(codeNotes.of(notes ?? [])),
          parts.owned.of(ownedLines.of(owned ?? [])),
          parts.readOnly.of(EditorState.readOnly.of(readOnly)),
          parts.label.of(EditorView.contentAttributes.of({ "aria-label": ariaLabel })),
          EditorView.updateListener.of((update) => {
            // A new `value` from outside sets `typed` first, so only the person's edits are reported.
            if (update.docChanged) {
              const text = update.state.doc.toString();
              if (text !== typed.current) {
                typed.current = text;
                handlers.current.onChange(text);
              }
            }
            if (update.selectionSet && handlers.current.onCursor) {
              const head = update.state.selection.main.head;
              const at = update.state.doc.lineAt(head);
              handlers.current.onCursor(at.number, head - at.from + 1);
            }
          }),
        ],
      }),
    });
    view.current = created;
    return () => {
      created.destroy();
      view.current = undefined;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- later prop changes are applied by the effects below
  }, []);

  useEffect(() => {
    const current = view.current;
    if (!current || value === typed.current || current.state.doc.toString() === value) return;
    typed.current = value;
    const head = Math.min(current.state.selection.main.head, value.length);
    current.dispatch({
      changes: { from: 0, to: current.state.doc.length, insert: value },
      selection: { anchor: head },
    });
  }, [value]);

  useEffect(() => {
    const current = view.current;
    if (!current) return;
    current.dispatch(setDiagnostics(current.state, lint(current.state.doc, diagnostics ?? [])));
  }, [diagnostics, value]);

  useEffect(() => {
    view.current?.dispatch({
      effects: compartments.current.language.reconfigure(languageExtension(language)),
    });
  }, [language]);

  useEffect(() => {
    view.current?.dispatch({ effects: compartments.current.marks.reconfigure(changeMarks.of(marks)) });
  }, [marks]);

  useEffect(() => {
    view.current?.dispatch({ effects: compartments.current.notes.reconfigure(codeNotes.of(notes ?? [])) });
  }, [notes]);

  useEffect(() => {
    view.current?.dispatch({ effects: compartments.current.owned.reconfigure(ownedLines.of(owned ?? [])) });
  }, [owned]);

  useEffect(() => {
    view.current?.dispatch({
      effects: compartments.current.readOnly.reconfigure(EditorState.readOnly.of(readOnly)),
    });
  }, [readOnly]);

  useEffect(() => {
    view.current?.dispatch({
      effects: compartments.current.label.reconfigure(
        EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
      ),
    });
  }, [ariaLabel]);

  useEffect(() => {
    const current = view.current;
    if (!current) return;
    const range =
      focusFrom === undefined || focusTo === undefined ? undefined : { from: focusFrom, to: focusTo };
    const effects = [compartments.current.focus.reconfigure(focusLine.of(range))];
    if (
      focusFrom !== undefined &&
      focusFrom >= 1 &&
      focusFrom <= current.state.doc.lines &&
      !current.hasFocus
    ) {
      effects.push(EditorView.scrollIntoView(current.state.doc.line(focusFrom).from, { y: "center" }));
    }
    current.dispatch({ effects });
  }, [focusFrom, focusTo]);

  return (
    <div ref={host} data-slot="code-editor" className={cn("h-full min-h-0 overflow-hidden", className)} />
  );
}
