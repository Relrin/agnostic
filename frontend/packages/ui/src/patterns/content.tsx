// Content patterns: MarkdownView (GFM, code highlighted by Shiki on demand), JsonView, JsonEditor, Toaster.
import { memo, useEffect, useId, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BundledLanguage } from "shiki";
import { Toaster as Sonner, toast } from "sonner";

import { cn } from "../lib/cn";
import { useSmoothText } from "../lib/smooth-text";
import { Button } from "../primitives/button";

export { toast };

/** Toasts (bottom right; "Undo"/"Open" actions go in `toast(…, { action })`). Mount once in the shell. */
export function Toaster() {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      toastOptions={{
        className: "!rounded-tile !border !border-border !bg-surface-raised !text-fg !text-[13px]",
      }}
    />
  );
}

type Token = { content: string; color?: string | undefined; fontStyle?: number | undefined };
type Highlighted = { lines: Token[][]; fg: string | undefined; bg: string | undefined };

const highlighted = new Map<string, Highlighted>();
/** Shiki's font-style bit flags. */
const ITALIC = 1;
const BOLD = 2;
const UNDERLINE = 4;

/**
 * Highlights with Shiki, loaded on first use (keeps it out of the initial bundle). Tokens are rendered as React
 * elements, never as an HTML string, so the web app has no HTML sink for Trusted Types to guard.
 */
function HighlightedCode({ code, language }: { code: string; language: string }) {
  const cacheKey = `${language}\u0000${code}`;
  const [result, setResult] = useState(() => highlighted.get(cacheKey));
  useEffect(() => {
    if (result !== undefined) return;
    let cancelled = false;
    void import("shiki")
      .then(({ codeToTokens }) =>
        codeToTokens(code, { lang: language as BundledLanguage, theme: "github-dark-default" }),
      )
      .then((tokens) => {
        const value: Highlighted = { lines: tokens.tokens, fg: tokens.fg, bg: tokens.bg };
        highlighted.set(cacheKey, value);
        if (!cancelled) setResult(value);
      })
      .catch(() => {
        // Unknown language or no grammar available: plain text is fine.
      });
    return () => {
      cancelled = true;
    };
  }, [cacheKey, code, result, language]);
  if (result === undefined) {
    return (
      <pre className="overflow-x-auto rounded-tile border border-border bg-inset px-3 py-2.5 font-mono text-[12px]">
        <code>{code}</code>
      </pre>
    );
  }
  return (
    <pre
      className="overflow-x-auto rounded-tile border border-border bg-inset px-3 py-2.5 font-mono text-[12px]"
      style={{ color: result.fg }}
    >
      <code>
        {result.lines.map((line, index) => (
          // Lines and tokens never reorder: their position is their identity.
          <span key={index} className="block">
            {line.map((token, position) => (
              <span key={position} style={tokenStyle(token)}>
                {token.content}
              </span>
            ))}
            {line.length === 0 ? "\n" : null}
          </span>
        ))}
      </code>
    </pre>
  );
}

function tokenStyle(token: Token): CSSProperties {
  const flags = token.fontStyle ?? 0;
  return {
    color: token.color,
    fontStyle: flags & ITALIC ? "italic" : undefined,
    fontWeight: flags & BOLD ? 600 : undefined,
    textDecoration: flags & UNDERLINE ? "underline" : undefined,
  };
}

type LinkMapper = (href: string) => string | undefined;

function markdownComponents(internalLink: LinkMapper | undefined, highlight: boolean): Components {
  return {
    a: ({ href, children: label }) => {
      const inside = href ? internalLink?.(href) : undefined;
      return inside ? (
        <a href={inside}>{label}</a>
      ) : (
        <a href={href} target="_blank" rel="noreferrer noopener">
          {label}
        </a>
      );
    },
    code: ({ className: languageClass, children: source }) => {
      const language = /language-(\w+)/.exec(languageClass ?? "")?.[1];
      const raw = typeof source === "string" ? source : Array.isArray(source) ? source.join("") : "";
      const code = raw.replace(/\n$/, "");
      if (!language) {
        return (
          <code className="rounded-type bg-surface-hover px-1 py-px font-mono text-[12.5px]">{code}</code>
        );
      }
      if (!highlight) {
        return (
          <pre className="overflow-x-auto rounded-tile border border-border bg-inset px-3 py-2.5 font-mono text-[12px]">
            <code>{code}</code>
          </pre>
        );
      }
      return <HighlightedCode code={code} language={language} />;
    },
    pre: ({ children: block }) => <>{block}</>,
  };
}

const FENCE = /^\s{0,3}(```|~~~)/;

/**
 * Splits Markdown into top-level blocks at blank lines, keeping fenced code and indented continuations (a list
 * item's second paragraph, nested code) with the block they belong to. Lets a streaming answer re-render only its
 * last, still-growing block.
 */
export function markdownBlocks(source: string): string[] {
  const blocks: string[] = [];
  const lines = source.split("\n");
  let current: string[] = [];
  let fence: string | undefined;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    const marker = FENCE.exec(line)?.[1];
    if (marker && (fence === undefined || marker === fence)) fence = fence === undefined ? marker : undefined;
    current.push(line);
    if (fence !== undefined || line.trim() !== "") continue;
    let ahead = index + 1;
    while (ahead < lines.length && (lines[ahead] ?? "").trim() === "") ahead += 1;
    const following = lines[ahead];
    if (following !== undefined && /^\s/.test(following)) continue;
    if (current.some((item) => item.trim() !== "")) blocks.push(current.join("\n"));
    current = [];
  }
  if (current.length > 0) blocks.push(current.join("\n"));
  return blocks;
}

const MarkdownBlock = memo(function MarkdownBlock({
  source,
  components,
}: {
  source: string;
  components: Components;
}) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {source}
    </ReactMarkdown>
  );
});

/**
 * Rendered model output: GitHub-flavoured Markdown, links open in a new tab, code highlighted. With `streaming`,
 * text is revealed at a steady reading pace, finished blocks stay put while the last one grows, and code in the
 * growing block is highlighted once it is complete.
 */
export function MarkdownView({
  children,
  className,
  internalLink,
  streaming = false,
}: {
  children: string;
  className?: string;
  /** Map a link to a page of the app (opened in place), or `undefined` to open it in a new tab. */
  internalLink?: LinkMapper;
  /** The text is still arriving. */
  streaming?: boolean;
}) {
  const shown = useSmoothText(children, streaming);
  const revealing = streaming || shown.length < children.length;
  const components = useMemo(() => markdownComponents(internalLink, true), [internalLink]);
  const growing = useMemo(() => markdownComponents(internalLink, false), [internalLink]);
  const blocks = useMemo(() => (revealing ? markdownBlocks(shown) : undefined), [revealing, shown]);
  return (
    <div
      className={cn(
        "flex flex-col gap-2.5 text-[14px] leading-relaxed break-words text-fg-prose",
        "[&_a]:text-info [&_a:hover]:underline [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5",
        "[&_h1]:text-[16px] [&_h1]:font-semibold [&_h2]:text-[15px] [&_h2]:font-semibold [&_h3]:font-semibold",
        "[&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:px-2 [&_th]:border [&_th]:border-border [&_th]:px-2",
        "[&_blockquote]:border-l-2 [&_blockquote]:border-border-strong [&_blockquote]:pl-3 [&_blockquote]:text-fg-secondary",
        className,
      )}
      data-streaming={revealing ? "" : undefined}
    >
      {blocks ? (
        blocks.map((block, index) => (
          <MarkdownBlock
            // Blocks only ever grow at the end, so the index is a stable identity.
            key={index}
            source={block}
            components={index === blocks.length - 1 ? growing : components}
          />
        ))
      ) : (
        <MarkdownBlock source={children} components={components} />
      )}
    </div>
  );
}

function jsonText(value: unknown): string {
  if (value === undefined) return "";
  return JSON.stringify(value, null, 2);
}

/** Read-only JSON (session_state, tool args), monospace with an optional label. */
export function JsonView({
  value,
  label,
  className,
}: {
  value: unknown;
  label?: string;
  className?: string;
}) {
  return (
    <pre
      aria-label={label}
      className={cn(
        "max-h-80 overflow-auto rounded-tile border border-border bg-inset px-3 py-2.5 font-mono text-[12px] leading-relaxed whitespace-pre text-fg",
        className,
      )}
    >
      {jsonText(value) || "{}"}
    </pre>
  );
}

/** Editable JSON object with validation; `onSave` receives the parsed object. */
export function JsonEditor({
  value,
  label,
  onSave,
  saving = false,
  footer,
}: {
  value: Record<string, unknown> | undefined;
  label: string;
  onSave: (value: Record<string, unknown>) => void;
  saving?: boolean;
  footer?: ReactNode;
}) {
  const id = useId();
  const original = jsonText(value ?? {});
  const [draft, setDraft] = useState(original);
  const [error, setError] = useState<string | undefined>();
  const [baseline, setBaseline] = useState(original);
  if (baseline !== original) {
    // The stored state changed (saved, or refetched): start over from it.
    setBaseline(original);
    setDraft(original);
  }

  const parse = (): Record<string, unknown> | undefined => {
    try {
      const parsed = JSON.parse(draft) as unknown;
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setError("This must be a JSON object.");
        return undefined;
      }
      setError(undefined);
      return parsed as Record<string, unknown>;
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "Not valid JSON.");
      return undefined;
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-[12px] text-fg-muted">
        {label}
      </label>
      <textarea
        id={id}
        spellCheck={false}
        value={draft}
        aria-invalid={error !== undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => {
          setDraft(event.target.value);
        }}
        className="min-h-48 resize-y rounded-tile border border-border-input bg-inset px-3 py-2.5 font-mono text-[12px] leading-relaxed text-fg focus-visible:outline-2 focus-visible:outline-accent"
      />
      {error && (
        <p id={`${id}-error`} className="text-[12px] text-danger">
          {error}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button
          size="30"
          variant="primary"
          disabled={saving || draft === original}
          onClick={() => {
            const parsed = parse();
            if (parsed) onSave(parsed);
          }}
        >
          {saving ? "Saving…" : "Save state"}
        </Button>
        <Button
          size="30"
          variant="ghost"
          disabled={draft === original}
          onClick={() => {
            setDraft(original);
            setError(undefined);
          }}
        >
          Reset
        </Button>
        {footer}
      </div>
    </div>
  );
}
