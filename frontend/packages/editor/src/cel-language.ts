// CEL for CodeMirror: a stream tokenizer (strings, numbers, operators, keywords, identifiers and method names),
// completion of the context's variables and functions, and hover docs. The server checks types; this only helps
// people write the expression.
import {
  autocompletion,
  type Completion,
  type CompletionContext,
  type CompletionResult,
} from "@codemirror/autocomplete";
import { StreamLanguage, type StringStream } from "@codemirror/language";
import type { Extension } from "@codemirror/state";
import { hoverTooltip } from "@codemirror/view";

import type { CelSymbol } from "./types";

type State = { afterDot: boolean };

const KEYWORDS = new Set(["true", "false", "null", "in"]);
const OPERATORS = /^(?:\|\||&&|==|!=|<=|>=|[<>+\-*/%!?:])/;

function token(stream: StringStream, state: State): string | null {
  if (stream.eatSpace()) return null;
  if (stream.match("//")) {
    stream.skipToEnd();
    return "comment";
  }
  const quote = stream.match(/^[rRbB]{0,2}("""|'''|"|')/);
  if (quote) {
    const close = (quote as RegExpMatchArray)[1] ?? '"';
    let escaped = false;
    while (!stream.eol()) {
      if (!escaped && stream.match(close)) break;
      escaped = !escaped && stream.next() === "\\";
    }
    state.afterDot = false;
    return "string";
  }
  if (stream.match(/^(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[uU]?/)) {
    state.afterDot = false;
    return "number";
  }
  if (stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)) {
    const word = stream.current();
    const wasMember = state.afterDot;
    state.afterDot = false;
    if (KEYWORDS.has(word)) return word === "in" ? "operatorKeyword" : "atom";
    if (stream.peek() === "(") return wasMember ? "propertyName function" : "variableName function";
    return wasMember ? "propertyName" : "variableName";
  }
  if (stream.eat(".")) {
    state.afterDot = true;
    return "punctuation";
  }
  if (stream.match(OPERATORS)) {
    state.afterDot = false;
    return "operator";
  }
  stream.next();
  state.afterDot = false;
  return "punctuation";
}

export const celLanguage = StreamLanguage.define<State>({
  name: "cel",
  startState: () => ({ afterDot: false }),
  token,
  languageData: { closeBrackets: { brackets: ["(", "[", "{", '"', "'"] } },
});

function completions(symbols: readonly CelSymbol[]) {
  return (context: CompletionContext): CompletionResult | null => {
    const word = context.matchBefore(/[A-Za-z_][A-Za-z0-9_]*$/);
    const before = context.state.sliceDoc(
      Math.max((word?.from ?? context.pos) - 1, 0),
      word?.from ?? context.pos,
    );
    const member = before === ".";
    if (!word && !context.explicit && !member) return null;
    const options: Completion[] = symbols
      .filter((symbol) =>
        member ? symbol.kind === "method" || symbol.kind === "macro" : symbol.kind !== "method",
      )
      .map((symbol) => ({
        label: symbol.name,
        type: symbol.kind === "variable" ? "variable" : "function",
        detail: symbol.detail,
        info: symbol.doc,
        apply: symbol.kind === "variable" ? symbol.name : `${symbol.name}(`,
      }));
    return { from: word?.from ?? context.pos, options, validFor: /^[A-Za-z0-9_]*$/ };
  };
}

function hover(symbols: readonly CelSymbol[]) {
  return hoverTooltip((view, pos) => {
    const line = view.state.doc.lineAt(pos);
    const text = line.text;
    let start = pos - line.from;
    let end = start;
    while (start > 0 && /[A-Za-z0-9_]/.test(text[start - 1] ?? "")) start -= 1;
    while (end < text.length && /[A-Za-z0-9_]/.test(text[end] ?? "")) end += 1;
    if (start === end) return null;
    const name = text.slice(start, end);
    const symbol = symbols.find((item) => item.name === name);
    if (!symbol) return null;
    return {
      pos: line.from + start,
      end: line.from + end,
      above: true,
      create: () => {
        const dom = document.createElement("div");
        dom.className = "cm-cel-hover";
        const title = document.createElement("code");
        title.textContent = symbol.kind === "variable" ? `${symbol.name}: ${symbol.detail}` : symbol.detail;
        const doc = document.createElement("div");
        doc.textContent = symbol.doc;
        dom.append(title, doc);
        return { dom };
      },
    };
  });
}

/** The language, completion and hover docs for one context's symbols. */
export function celExtensions(symbols: readonly CelSymbol[]): Extension[] {
  return [celLanguage, autocompletion({ override: [completions(symbols)] }), hover(symbols)];
}
