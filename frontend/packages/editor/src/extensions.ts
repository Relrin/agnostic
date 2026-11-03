// CodeMirror extensions for the read-only code view: design-token theme and highlighting, the change-mark strip,
// the focused line, and inline notes. Marks, focus and notes are facets so prop changes only reconfigure them.
import { json } from "@codemirror/lang-json";
import { python } from "@codemirror/lang-python";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState, Facet, RangeSetBuilder, type Extension } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  GutterMarker,
  WidgetType,
  gutter,
  gutterLineClass,
  lineNumbers,
  type DecorationSet,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";

import type { ChangeMark, CodeLanguage, CodeNote } from "./types";

export function languageExtension(language: CodeLanguage): Extension {
  return language === "python" ? python() : json();
}

const highlight = HighlightStyle.define([
  {
    tag: [
      tags.keyword,
      tags.controlKeyword,
      tags.definitionKeyword,
      tags.moduleKeyword,
      tags.operatorKeyword,
    ],
    color: "var(--syntax-keyword)",
  },
  { tag: [tags.bool, tags.null, tags.self], color: "var(--syntax-keyword)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--syntax-string)" },
  { tag: tags.number, color: "var(--syntax-number)" },
  { tag: tags.propertyName, color: "var(--syntax-key)" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "var(--syntax-call)" },
  { tag: [tags.definition(tags.variableName), tags.className], color: "var(--syntax-call)" },
  { tag: tags.comment, color: "var(--syntax-comment)", fontStyle: "italic" },
  {
    tag: [tags.punctuation, tags.bracket, tags.separator, tags.operator],
    color: "var(--syntax-punctuation)",
  },
  { tag: [tags.variableName, tags.attributeName], color: "var(--syntax-identifier)" },
]);

const theme = EditorView.theme(
  {
    "&": {
      height: "100%",
      color: "var(--fg-prose)",
      backgroundColor: "var(--bg-inset)",
      fontSize: "12.5px",
    },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "20px" },
    ".cm-content": { caretColor: "var(--accent)", padding: "8px 0" },
    ".cm-cursor": { borderLeftColor: "var(--accent)" },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
      backgroundColor: "var(--info-tint-strong)",
    },
    ".cm-gutters": {
      backgroundColor: "var(--bg-inset)",
      color: "var(--fg-line-number)",
      border: "none",
    },
    ".cm-lineNumbers .cm-gutterElement": { padding: "0 8px 0 12px", minWidth: "36px" },
    ".cm-change-gutter": { width: "3px" },
    ".cm-change-gutter .cm-gutterElement": { padding: "0" },
    ".cm-change-mark": { width: "3px", height: "100%" },
    ".cm-change-added": { backgroundColor: "var(--accent)" },
    ".cm-change-modified": { backgroundColor: "var(--modified)" },
    ".cm-line": { padding: "0 12px" },
    ".cm-line.cm-focus-line, .cm-gutterElement.cm-focus-line": {
      backgroundColor: "color-mix(in srgb, var(--accent) 10%, transparent)",
    },
    ".cm-gutterElement.cm-focus-line": { color: "var(--accent)" },
    ".cm-note-mark": {
      textDecoration: "underline wavy var(--warning)",
      textDecorationSkipInk: "none",
      textUnderlineOffset: "3px",
    },
    ".cm-note": {
      margin: "2px 12px 4px",
      padding: "6px 10px",
      borderLeft: "2px solid var(--warning)",
      borderRadius: "var(--radius-control)",
      backgroundColor: "var(--warning-pill-bg)",
      color: "var(--warning-pill-fg)",
      fontFamily: "var(--font-sans)",
      fontSize: "12px",
      lineHeight: "18px",
      display: "flex",
      flexWrap: "wrap",
      gap: "2px 8px",
      alignItems: "baseline",
      // The content is as wide as its longest line: keep the note readable at the left edge of the view.
      whiteSpace: "normal",
      maxWidth: "480px",
      position: "sticky",
      left: "0",
    },
    ".cm-note a": { color: "var(--info)", marginLeft: "auto", whiteSpace: "nowrap" },
    ".cm-note a:hover": { color: "var(--info-hover)", textDecoration: "underline" },
  },
  { dark: true },
);

// ---------------------------------------------------------------- change marks

export const changeMarks = Facet.define<Record<number, ChangeMark>, Record<number, ChangeMark>>({
  combine: (values) => values.at(-1) ?? {},
});

class ChangeMarker extends GutterMarker {
  constructor(readonly kind: ChangeMark) {
    super();
  }
  override eq(other: GutterMarker): boolean {
    return other instanceof ChangeMarker && other.kind === this.kind;
  }
  override toDOM(): Node {
    const element = document.createElement("div");
    element.className = `cm-change-mark cm-change-${this.kind}`;
    element.title = this.kind === "added" ? "Added" : "Modified";
    return element;
  }
}

const markers = { added: new ChangeMarker("added"), modified: new ChangeMarker("modified") };

const changeGutter = gutter({
  class: "cm-change-gutter",
  lineMarker: (view, line) => {
    const kind = view.state.facet(changeMarks)[view.state.doc.lineAt(line.from).number];
    return kind ? markers[kind] : null;
  },
  lineMarkerChange: (update) => update.startState.facet(changeMarks) !== update.state.facet(changeMarks),
});

// ---------------------------------------------------------------- focused line

export const focusLine = Facet.define<number | undefined, number | undefined>({
  combine: (values) => values.at(-1),
});

const focusGutterMarker = new (class extends GutterMarker {
  override elementClass = "cm-focus-line";
})();

function focusedLine(state: EditorState): number | undefined {
  const line = state.facet(focusLine);
  return line !== undefined && line >= 1 && line <= state.doc.lines ? line : undefined;
}

const focusDecorations = EditorView.decorations.compute([focusLine, "doc"], (state): DecorationSet => {
  const line = focusedLine(state);
  if (line === undefined) return Decoration.none;
  return Decoration.set([Decoration.line({ class: "cm-focus-line" }).range(state.doc.line(line).from)]);
});

const focusGutter = gutterLineClass.compute([focusLine, "doc"], (state) => {
  const line = focusedLine(state);
  const builder = new RangeSetBuilder<GutterMarker>();
  if (line !== undefined) {
    const from = state.doc.line(line).from;
    builder.add(from, from, focusGutterMarker);
  }
  return builder.finish();
});

// ---------------------------------------------------------------- notes

export const codeNotes = Facet.define<readonly CodeNote[], readonly CodeNote[]>({
  combine: (values) => values.at(-1) ?? [],
});

class NoteWidget extends WidgetType {
  constructor(readonly note: CodeNote) {
    super();
  }
  override eq(other: NoteWidget): boolean {
    return (
      other.note.text === this.note.text &&
      other.note.action?.label === this.note.action?.label &&
      other.note.action?.href === this.note.action?.href
    );
  }
  override toDOM(): HTMLElement {
    const element = document.createElement("div");
    element.className = "cm-note";
    element.setAttribute("role", "note");
    const text = document.createElement("span");
    text.textContent = this.note.text;
    element.append(text);
    if (this.note.action) {
      const link = document.createElement("a");
      link.href = this.note.action.href;
      link.textContent = this.note.action.label;
      element.append(link);
    }
    return element;
  }
}

const noteMark = Decoration.mark({ class: "cm-note-mark" });

const noteDecorations = EditorView.decorations.compute([codeNotes, "doc"], (state): DecorationSet => {
  const ranges = [];
  for (const note of state.facet(codeNotes)) {
    if (note.line < 1 || note.line > state.doc.lines) continue;
    const line = state.doc.line(note.line);
    const from = line.from + Math.min(Math.max(note.from, 0), line.length);
    const to = line.from + Math.min(Math.max(note.to, 0), line.length);
    if (to > from) ranges.push(noteMark.range(from, to));
    ranges.push(Decoration.widget({ widget: new NoteWidget(note), block: true, side: 1 }).range(line.to));
  }
  return Decoration.set(ranges, true);
});

// ---------------------------------------------------------------- assembly

/** Everything except the language and the per-prop facets, which live in compartments. */
export function baseExtensions(): Extension[] {
  return [
    EditorState.readOnly.of(true),
    EditorView.contentAttributes.of({ "aria-readonly": "true" }),
    lineNumbers(),
    changeGutter,
    focusGutter,
    focusDecorations,
    noteDecorations,
    syntaxHighlighting(highlight),
    theme,
  ];
}
