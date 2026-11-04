// The "Ask your OS" box: one line with a suggestion shown as ghost text (Tab accepts it), attachments as chips,
// and a hint that says which data answers use.
import { describeError, type AcceptedOut } from "@agnostic/api";
import { formatBytes } from "@agnostic/core";
import { Button, Kbd, cn } from "@agnostic/ui";
import { ArrowUp, Paperclip, X } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent, type SyntheticEvent } from "react";

import { GROUNDING } from "./answer-view";
import { askQuestion } from "./requests";
import { completion } from "./suggestions";

const ACCEPT =
  ".log,.txt,.json,.jsonl,.ndjson,.csv,.md,.yaml,.yml,.xml,.toml,image/png,image/jpeg,image/webp,image/gif";
const MAX_FILES = 4;

export function AskBox({
  instance,
  suggestions = [],
  context,
  conversationId,
  notice,
  label = "Ask your OS",
  placeholder = "Why did daily-brief fail last night?",
  initial = "",
  onAsked,
}: {
  instance: string;
  suggestions?: readonly string[];
  context?: string | undefined;
  conversationId?: string | undefined;
  /** The org's data-handling notice, e.g. "Answers are generated on our own vLLM cluster". */
  notice?: string | null | undefined;
  label?: string;
  placeholder?: string;
  initial?: string;
  onAsked: (accepted: AcceptedOut, question: string) => void;
}) {
  const id = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [text, setText] = useState(initial);
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const rest = completion(text, suggestions);

  const submit = async (event?: SyntheticEvent) => {
    event?.preventDefault();
    const question = text.trim();
    if (!question || sending) return;
    setSending(true);
    setError(undefined);
    try {
      const accepted = await askQuestion(instance, { question, conversationId, context, files });
      setText("");
      setFiles([]);
      onAsked(accepted, question);
    } catch (failure) {
      setError(describeError(failure).reason);
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Tab" && !event.shiftKey && rest) {
      event.preventDefault();
      setText(text.trimStart() + rest);
    }
  };

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="mx-auto flex w-full max-w-[860px] flex-col gap-2 rounded-[14px] border border-border-strong bg-inset px-4 py-3"
    >
      <label htmlFor={id} className="text-[12px] text-fg-muted">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 overflow-hidden text-[14.5px] whitespace-pre text-fg-faint"
          >
            <span className="invisible">{text.trimStart() ? text : ""}</span>
            {text.trimStart() ? rest : ""}
          </div>
          <input
            id={id}
            value={text}
            placeholder={suggestions[0] ?? placeholder}
            autoComplete="off"
            onChange={(event) => {
              setText(event.target.value);
            }}
            onKeyDown={onKeyDown}
            className="relative w-full bg-transparent text-[14.5px] text-fg outline-none placeholder:text-fg-faint"
          />
        </div>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          accept={ACCEPT}
          aria-label="Attach file"
          onChange={(event) => {
            const picked = Array.from(event.target.files ?? []);
            setFiles((current) => [...current, ...picked].slice(0, MAX_FILES));
            event.target.value = "";
          }}
        />
        <Button
          type="button"
          variant="icon"
          size="32"
          aria-label="Attach file"
          title="Attach a log or a screenshot"
          onClick={() => fileInput.current?.click()}
        >
          <Paperclip aria-hidden />
        </Button>
        <Button
          type="submit"
          variant="primary"
          size="32"
          className="w-8 rounded-full px-0"
          aria-label="Send"
          disabled={!text.trim() || sending}
        >
          <ArrowUp aria-hidden />
        </Button>
      </div>
      {files.length > 0 && (
        <ul aria-label="Attachments" className="flex flex-wrap gap-1.5">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${String(index)}`}
              className="inline-flex h-[30px] items-center gap-2 rounded-tile border border-border-strong px-2.5 text-[12px]"
            >
              <span className="max-w-48 truncate">{file.name}</span>
              <span className="text-fg-muted">{formatBytes(file.size)}</span>
              <button
                type="button"
                aria-label={`Remove ${file.name}`}
                className="text-fg-muted hover:text-fg"
                onClick={() => {
                  setFiles((current) => current.filter((_, at) => at !== index));
                }}
              >
                <X className="size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="text-[12px] text-danger">
          {error}
        </p>
      )}
      <p className={cn("text-[11.5px] text-fg-muted")}>
        <Kbd>Tab</Kbd> to use suggestion · {GROUNDING}
        {notice ? ` · ${notice}` : ""}
      </p>
    </form>
  );
}
