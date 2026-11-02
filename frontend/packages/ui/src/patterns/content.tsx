// Content patterns: MarkdownView (GFM, code highlighted by Shiki on demand), JsonView, JsonEditor, Toaster.
import { useEffect, useId, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Toaster as Sonner, toast } from "sonner";

import { cn } from "../lib/cn";
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

const highlighted = new Map<string, string>();

/** Highlights with Shiki, loaded on first use (keeps it out of the initial bundle). */
function HighlightedCode({ code, language }: { code: string; language: string }) {
  const cacheKey = `${language}\u0000${code}`;
  const [html, setHtml] = useState(() => highlighted.get(cacheKey));
  useEffect(() => {
    if (html !== undefined) return;
    let cancelled = false;
    void import("shiki")
      .then(({ codeToHtml }) => codeToHtml(code, { lang: language, theme: "github-dark-default" }))
      .then((result) => {
        highlighted.set(cacheKey, result);
        if (!cancelled) setHtml(result);
      })
      .catch(() => {
        // Unknown language or no network for the grammar: plain text is fine.
      });
    return () => {
      cancelled = true;
    };
  }, [cacheKey, code, html, language]);
  if (html === undefined) {
    return (
      <pre className="overflow-x-auto rounded-tile border border-border bg-inset px-3 py-2.5 font-mono text-[12px]">
        <code>{code}</code>
      </pre>
    );
  }
  return (
    <div
      className="overflow-x-auto rounded-tile border border-border text-[12px] [&_pre]:!bg-inset [&_pre]:px-3 [&_pre]:py-2.5"
      // Shiki escapes the source; the HTML is spans with inline colours only.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/** Rendered model output: GitHub-flavoured Markdown, links open in a new tab, code highlighted. */
export function MarkdownView({ children, className }: { children: string; className?: string }) {
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
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children: label }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {label}
            </a>
          ),
          code: ({ className: languageClass, children: source }) => {
            const language = /language-(\w+)/.exec(languageClass ?? "")?.[1];
            const raw = typeof source === "string" ? source : Array.isArray(source) ? source.join("") : "";
            const code = raw.replace(/\n$/, "");
            if (!language) {
              return (
                <code className="rounded-type bg-surface-hover px-1 py-px font-mono text-[12.5px]">
                  {code}
                </code>
              );
            }
            return <HighlightedCode code={code} language={language} />;
          },
          pre: ({ children: block }) => <>{block}</>,
        }}
      >
        {children}
      </ReactMarkdown>
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
