// Chat widgets: Composer (attachments, mentions, Enter to send, Stop while streaming) and SessionList.
import { AtSign, Paperclip, Search, Send, Square, X } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { StatusPill } from "../primitives/badge";
import { Button } from "../primitives/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../primitives/dropdown-menu";
import { Tooltip } from "../primitives/tooltip";

export type AttachmentRule = { maxBytes: number; maxFiles: number; accept: readonly string[] };

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${String(Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function accepted(file: File, accept: readonly string[]): boolean {
  if (accept.length === 0) return true;
  return accept.some((rule) =>
    rule.startsWith(".")
      ? file.name.toLowerCase().endsWith(rule)
      : rule.endsWith("/*")
        ? file.type.startsWith(rule.slice(0, -1))
        : file.type === rule,
  );
}

export function Composer({
  label,
  placeholder,
  onSend,
  onStop,
  streaming = false,
  disabled = false,
  disabledReason,
  attachments,
  members,
}: {
  /** "Message support-triage". */
  label: string;
  placeholder: string;
  onSend: (message: string, files: File[]) => void;
  onStop?: () => void;
  streaming?: boolean;
  disabled?: boolean;
  disabledReason?: string | undefined;
  /** Omit to hide "Attach files" (workflows take no files). */
  attachments?: AttachmentRule | undefined;
  /** Team members for "@ Mention member"; undefined disables it with a reason. */
  members?: readonly string[] | undefined;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [problem, setProblem] = useState<string | undefined>();
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  const send = () => {
    const message = text.trim();
    if (!message || disabled || streaming) return;
    onSend(message, files);
    setText("");
    setFiles([]);
    setProblem(undefined);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  };

  const addFiles = (list: FileList | null) => {
    if (!list || !attachments) return;
    const next = [...files];
    for (const file of Array.from(list)) {
      if (!accepted(file, attachments.accept)) {
        setProblem(`${file.name}: this file type isn't accepted.`);
        continue;
      }
      if (file.size > attachments.maxBytes) {
        setProblem(`${file.name} is larger than ${sizeLabel(attachments.maxBytes)}.`);
        continue;
      }
      if (next.length >= attachments.maxFiles) {
        setProblem(`At most ${String(attachments.maxFiles)} files per message.`);
        break;
      }
      next.push(file);
    }
    setFiles(next);
  };

  const mention = (name: string) => {
    setText((current) => `${current}${current && !current.endsWith(" ") ? " " : ""}@${name} `);
    textarea.current?.focus();
  };

  return (
    <div className="flex flex-col gap-2 rounded-card border border-border-input bg-surface px-3 py-2.5 focus-within:border-border-strong">
      {files.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Attachments">
          {files.map((file) => (
            <li
              key={`${file.name}-${String(file.size)}`}
              className="inline-flex items-center gap-1.5 rounded-control border border-border-strong px-2 py-0.5 text-[12px]"
            >
              <span className="font-mono">{file.name}</span>
              <span className="text-fg-muted">{sizeLabel(file.size)}</span>
              <button
                type="button"
                className="cursor-pointer text-fg-muted hover:text-fg"
                aria-label={`Remove ${file.name}`}
                onClick={() => {
                  setFiles(files.filter((item) => item !== file));
                }}
              >
                <X className="size-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <textarea
        id={id}
        ref={textarea}
        aria-label={label}
        rows={2}
        value={text}
        disabled={disabled}
        placeholder={disabled && disabledReason ? disabledReason : placeholder}
        onChange={(event) => {
          setText(event.target.value);
        }}
        onKeyDown={onKeyDown}
        className="max-h-60 min-h-12 resize-none bg-transparent text-[14px] text-fg outline-none placeholder:text-fg-faint"
      />
      {problem && (
        <p role="alert" className="text-[12px] text-danger">
          {problem}
        </p>
      )}
      <div className="flex items-center gap-1">
        {attachments && (
          <>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              accept={attachments.accept.join(",")}
              onChange={(event) => {
                addFiles(event.target.files);
                event.target.value = "";
              }}
            />
            <Button
              variant="ghost"
              size="28"
              disabled={disabled}
              onClick={() => {
                fileInput.current?.click();
              }}
            >
              <Paperclip aria-hidden />
              Attach files
            </Button>
          </>
        )}
        {members && members.length > 0 ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="28" disabled={disabled}>
                <AtSign aria-hidden />
                Mention member
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {members.map((member) => (
                <DropdownMenuItem
                  key={member}
                  onSelect={() => {
                    mention(member);
                  }}
                >
                  {member}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <Tooltip content="Available when chatting with an agent team">
            <span>
              <Button variant="ghost" size="28" disabled title="Available when chatting with an agent team">
                <AtSign aria-hidden />
                Mention member
              </Button>
            </span>
          </Tooltip>
        )}
        <span className="ml-auto hidden text-[11.5px] text-fg-faint sm:inline">
          Enter to send · Shift+Enter for a new line
        </span>
        {streaming ? (
          <Button variant="outline" size="30" onClick={onStop}>
            <Square aria-hidden />
            Stop
          </Button>
        ) : (
          <Button variant="primary" size="30" disabled={disabled || !text.trim()} onClick={send}>
            <Send aria-hidden />
            Send
          </Button>
        )}
      </div>
    </div>
  );
}

export type SessionListItem = {
  id: string;
  name: string;
  status?: string | undefined;
  meta: ReactNode;
};

/** Date-grouped sessions with search; the selected one is highlighted. */
export function SessionList({
  label,
  groups,
  selectedId,
  onSelect,
  search,
  onSearch,
  footer,
}: {
  label: string;
  groups: readonly { label: string; items: readonly SessionListItem[] }[];
  selectedId?: string | undefined;
  onSelect: (id: string) => void;
  search: string;
  onSearch: (value: string) => void;
  footer?: ReactNode;
}) {
  const searchId = useId();
  return (
    <nav aria-label={label} className="flex min-h-0 flex-col gap-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-fg-muted" aria-hidden />
        <label htmlFor={searchId} className="sr-only">
          Search sessions
        </label>
        <input
          id={searchId}
          type="search"
          value={search}
          placeholder="Search sessions"
          onChange={(event) => {
            onSearch(event.target.value);
          }}
          className="h-8 w-full rounded-control border border-border-input bg-surface pr-2 pl-8 text-[13px] outline-none placeholder:text-fg-faint focus:border-border-strong"
        />
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
        {groups.map((group) => (
          <section key={group.label} className="flex flex-col gap-0.5">
            <h3 className="px-2 text-[11px] font-semibold tracking-[0.06em] text-fg-faint uppercase">
              {group.label}
            </h3>
            <ul className="flex flex-col">
              {group.items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    aria-current={selectedId === item.id ? "true" : undefined}
                    onClick={() => {
                      onSelect(item.id);
                    }}
                    className={cn(
                      "flex w-full cursor-pointer flex-col gap-0.5 rounded-control px-2 py-1.5 text-left hover:bg-surface-hover",
                      selectedId === item.id && "bg-surface-selected",
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <span className="min-w-0 flex-1 truncate text-[13px]">{item.name}</span>
                      {item.status && <StatusPill status={item.status} />}
                    </span>
                    <span className="truncate text-[11.5px] text-fg-muted">{item.meta}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {footer}
      </div>
    </nav>
  );
}
