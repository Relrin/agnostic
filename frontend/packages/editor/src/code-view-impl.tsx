// The CodeMirror side of CodeView: one EditorView per mount; prop changes reconfigure compartments or replace the
// document instead of rebuilding the view, so scroll position and selection survive.
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { cn } from "@agnostic/ui";
import { useEffect, useRef } from "react";

import {
  baseExtensions,
  changeMarks,
  codeNotes,
  focusLine,
  languageExtension,
  lineRange,
} from "./extensions";
import type { CodeViewProps } from "./types";

const NO_MARKS = {};
const NO_NOTES: CodeViewProps["notes"] = [];

export default function CodeViewImpl({
  value,
  language,
  marks = NO_MARKS,
  focusLine: line,
  focusRange,
  notes = NO_NOTES,
  onCursor,
  ariaLabel,
  className,
}: CodeViewProps) {
  const host = useRef<HTMLDivElement>(null);
  const focus = lineRange(line, focusRange);
  const focusFrom = focus?.from;
  const focusTo = focus?.to;
  const view = useRef<EditorView>(undefined);
  const compartments = useRef({
    language: new Compartment(),
    marks: new Compartment(),
    focus: new Compartment(),
    notes: new Compartment(),
    label: new Compartment(),
  });
  const cursor = useRef(onCursor);
  useEffect(() => {
    cursor.current = onCursor;
  }, [onCursor]);

  // Created once; the effects below keep it in sync with the props.
  useEffect(() => {
    if (!host.current) return;
    const parts = compartments.current;
    const created = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          baseExtensions(),
          parts.language.of(languageExtension(language)),
          parts.marks.of(changeMarks.of(marks)),
          parts.focus.of(focusLine.of(focus)),
          parts.notes.of(codeNotes.of(notes ?? [])),
          parts.label.of(EditorView.contentAttributes.of({ "aria-label": ariaLabel })),
          EditorView.updateListener.of((update) => {
            if (!update.selectionSet || !cursor.current) return;
            const head = update.state.selection.main.head;
            const line = update.state.doc.lineAt(head);
            cursor.current(line.number, head - line.from + 1);
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
    if (!current || current.state.doc.toString() === value) return;
    current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: value } });
  }, [value]);

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
    if (focusFrom !== undefined && focusFrom >= 1 && focusFrom <= current.state.doc.lines) {
      effects.push(EditorView.scrollIntoView(current.state.doc.line(focusFrom).from, { y: "center" }));
    }
    current.dispatch({ effects });
  }, [focusFrom, focusTo, value]);

  return <div ref={host} data-slot="code-view" className={cn("h-full min-h-0 overflow-hidden", className)} />;
}
