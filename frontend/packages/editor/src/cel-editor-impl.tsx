// The CodeMirror side of CelEditor: a small editor for one expression, with the context's completion and hover
// docs, the checker's findings underlined, and an imperative handle so variable chips insert at the cursor.
import { closeBrackets } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { setDiagnostics } from "@codemirror/lint";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView, keymap, placeholder as placeholderText } from "@codemirror/view";
import { cn } from "@agnostic/ui";
import { useEffect, useImperativeHandle, useRef } from "react";

import { celExtensions } from "./cel-language";
import { editorTheme } from "./extensions";
import type { CelEditorProps } from "./types";

const NO_DIAGNOSTICS: CelEditorProps["diagnostics"] = [];

export default function CelEditorImpl({
  value,
  onChange,
  symbols,
  diagnostics = NO_DIAGNOSTICS,
  ariaLabel,
  placeholder,
  readOnly = false,
  className,
  ref,
}: CelEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView>(undefined);
  const typed = useRef(value);
  const changed = useRef(onChange);
  const compartments = useRef({
    symbols: new Compartment(),
    readOnly: new Compartment(),
    label: new Compartment(),
  });
  useEffect(() => {
    changed.current = onChange;
  }, [onChange]);

  useImperativeHandle(
    ref,
    () => ({
      insert: (text: string) => {
        const current = view.current;
        if (!current) return;
        const { from, to } = current.state.selection.main;
        current.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length } });
        current.focus();
      },
      focus: () => view.current?.focus(),
    }),
    [],
  );

  useEffect(() => {
    if (!host.current) return;
    const parts = compartments.current;
    const created = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          history(),
          closeBrackets(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          EditorView.lineWrapping,
          editorTheme,
          placeholderText(placeholder ?? ""),
          parts.symbols.of(celExtensions(symbols)),
          parts.readOnly.of(EditorState.readOnly.of(readOnly)),
          parts.label.of(EditorView.contentAttributes.of({ "aria-label": ariaLabel })),
          EditorView.updateListener.of((update) => {
            if (!update.docChanged) return;
            const text = update.state.doc.toString();
            if (text === typed.current) return;
            typed.current = text;
            changed.current(text);
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
    current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: value } });
  }, [value]);

  useEffect(() => {
    const current = view.current;
    if (!current) return;
    const length = current.state.doc.length;
    const items = (diagnostics ?? []).map((item) => {
      const from = Math.min(Math.max(item.from, 0), length);
      const to = Math.min(Math.max(item.to, from), length);
      return {
        from,
        to: to > from ? to : Math.min(from + 1, length),
        severity: item.severity,
        message: item.message,
      };
    });
    current.dispatch(setDiagnostics(current.state, items));
  }, [diagnostics, value]);

  useEffect(() => {
    view.current?.dispatch({ effects: compartments.current.symbols.reconfigure(celExtensions(symbols)) });
  }, [symbols]);

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

  return (
    <div
      ref={host}
      data-slot="cel-editor"
      className={cn(
        "min-h-16 overflow-hidden rounded-control border border-border bg-inset [&_.cm-content]:px-1",
        className,
      )}
    />
  );
}
