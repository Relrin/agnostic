// Chat widgets: Composer (attachments, mentions, Enter to send, Stop while streaming), SessionList and ContextMeter.
import { AtSign, Brain, Paperclip, Search, Send, Square, X } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { cn } from "../lib/cn";
import { groupDigits } from "../lib/format";
import { StatusPill } from "../primitives/badge";
import { Button } from "../primitives/button";
import { Popover, PopoverContent, PopoverTrigger } from "../primitives/popover";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../primitives/dropdown-menu";
import { Kbd } from "../primitives/small";
import { Tooltip } from "../primitives/tooltip";

export type AttachmentRule = { maxBytes: number; maxFiles: number; accept: readonly string[] };

/** How hard the model thinks before answering, in the runtime's provider-neutral vocabulary. */
export type ReasoningLevel = "off" | "minimal" | "low" | "medium" | "high" | "max";

export const REASONING_LEVELS: Record<ReasoningLevel, { label: string; description: string }> = {
  off: { label: "Off", description: "Answer without a thinking step." },
  minimal: { label: "Minimal", description: "Barely think: fastest and cheapest." },
  low: { label: "Low", description: "Think briefly: quick answers to simple asks." },
  medium: { label: "Medium", description: "Balance speed and depth." },
  high: { label: "High", description: "Think it through: slower, more tokens." },
  max: { label: "Max", description: "The deepest thinking the model offers." },
};

/** The effort picker: the levels the component's model supports and the person's pick (undefined: as configured). */
export type ComposerReasoning = {
  levels: readonly ReasoningLevel[];
  value: ReasoningLevel | undefined;
  onChange: (value: ReasoningLevel | undefined) => void;
  /** The level the component is configured with, when the runtime reports it ("Default · Medium"). */
  configured?: ReasoningLevel | undefined;
  /** "OpenAI reasoning_effort": what the level is sent as, for the picker's footnote. */
  parameter?: string | undefined;
};

function SendHint() {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-fg-secondary">
      <Kbd>Enter</Kbd> to send
      <span aria-hidden className="text-fg-faint">
        ·
      </span>
      <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> for a new line
    </span>
  );
}

function ReasoningPicker({ reasoning, disabled }: { reasoning: ComposerReasoning; disabled: boolean }) {
  const { levels, value, onChange, configured, parameter } = reasoning;
  const current = value ? REASONING_LEVELS[value].label : "Default";
  const defaultLabel = configured ? `Default · ${REASONING_LEVELS[configured].label}` : "Default";
  return (
    <DropdownMenu>
      <Tooltip content="How hard the model thinks before it answers, for the messages you send next">
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="28"
            disabled={disabled}
            aria-label={`Reasoning effort: ${current}`}
            className={cn(value && "text-fg")}
          >
            <Brain aria-hidden />
            <span className="hidden sm:inline">Effort:</span> {current}
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" side="top" className="w-72">
        <DropdownMenuLabel>Reasoning effort</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={value ?? "default"}
          onValueChange={(next) => {
            onChange(next === "default" ? undefined : (next as ReasoningLevel));
          }}
        >
          <DropdownMenuRadioItem value="default">
            <span className="flex flex-col">
              <span>{defaultLabel}</span>
              <span className="text-[11.5px] text-fg-muted">What the component is configured with.</span>
            </span>
          </DropdownMenuRadioItem>
          {levels.map((level) => (
            <DropdownMenuRadioItem key={level} value={level}>
              <span className="flex flex-col">
                <span>{REASONING_LEVELS[level].label}</span>
                <span className="text-[11.5px] text-fg-muted">{REASONING_LEVELS[level].description}</span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <p className="px-2 pt-0.5 pb-1.5 text-[11.5px] leading-snug text-fg-faint">
          The levels depend on the model&apos;s provider
          {parameter ? (
            <>
              {" "}
              (sent as <span className="font-mono">{parameter}</span>)
            </>
          ) : null}
          .
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

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
  accessory,
  reasoning,
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
  /** Shown at the end of the action row, before Send (the context meter). */
  accessory?: ReactNode;
  /** The reasoning effort picker; omit when the component's model has no effort to choose. */
  reasoning?: ComposerReasoning | undefined;
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
        aria-keyshortcuts="Enter Shift+Enter"
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
        {accessory}
        <span className="ml-auto" />
        {reasoning && reasoning.levels.length > 0 && (
          <ReasoningPicker reasoning={reasoning} disabled={disabled} />
        )}
        {streaming ? (
          <Button variant="outline" size="30" onClick={onStop}>
            <Square aria-hidden />
            Stop
          </Button>
        ) : (
          <Tooltip content={<SendHint />} side="top">
            {/* A span keeps the hint on hover while the button is disabled (disabled buttons get no pointer events). */}
            <span className="inline-flex">
              <Button
                variant="primary"
                size="30"
                disabled={disabled || !text.trim()}
                aria-keyshortcuts="Enter"
                onClick={send}
              >
                <Send aria-hidden />
                Send
              </Button>
            </span>
          </Tooltip>
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

export type ContextMeterShare = { key: string; label: string; tokens: number };

const SHARE_COLORS: Record<string, string> = {
  conversation: "var(--chart-1)",
  tools: "var(--chart-2)",
  definitions: "var(--chart-3)",
  system: "var(--warning)",
  output: "var(--info)",
};

function compact(tokens: number): string {
  if (tokens >= 1_000_000) {
    const millions = tokens / 1_000_000;
    return `${Number.isInteger(millions) ? String(millions) : millions.toFixed(1)}M`;
  }
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}k`;
  return String(tokens);
}

function exact(tokens: number): string {
  return groupDigits(tokens);
}

/** A share of the window, to one decimal: "18.2%". */
function share(tokens: number, window: number): string {
  return `${((tokens / window) * 100).toFixed(1)}%`;
}

type Level = "ok" | "warning" | "danger";

/** Below 70% the meter stays quiet, then it warns, and past 90% the next turns may not fit. */
function level(percent: number | undefined): Level {
  if (percent === undefined || percent < 70) return "ok";
  return percent < 90 ? "warning" : "danger";
}

const LEVEL_COLOR: Record<Level, string> = {
  ok: "var(--fg-secondary)",
  warning: "var(--warning)",
  danger: "var(--danger)",
};

function Ring({ percent, tone }: { percent: number | undefined; tone: Level }) {
  const radius = 6;
  const circumference = 2 * Math.PI * radius;
  const filled = percent === undefined ? 0 : Math.min(100, percent) / 100;
  return (
    <svg viewBox="0 0 16 16" className="size-4 shrink-0 -rotate-90" aria-hidden>
      <circle cx="8" cy="8" r={radius} fill="none" stroke="var(--border-strong)" strokeWidth="2.5" />
      <circle
        cx="8"
        cy="8"
        r={radius}
        fill="none"
        stroke={LEVEL_COLOR[tone]}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={`${String(filled * circumference)} ${String(circumference)}`}
        className="transition-[stroke-dasharray] duration-500 ease-out motion-reduce:transition-none"
      />
    </svg>
  );
}

function percentText(used: number, percent: number | undefined): string | undefined {
  if (percent === undefined) return undefined;
  if (percent < 1 && used > 0) return "<1%";
  return `${String(Math.round(percent))}%`;
}

function Swatch({ color, faint = false }: { color: string; faint?: boolean }) {
  return (
    <span
      aria-hidden
      className="size-2.5 shrink-0 rounded-[2px]"
      style={{ backgroundColor: color, opacity: faint ? 0.35 : 1 }}
    />
  );
}

/**
 * How full the model's context window is after the latest request: a ring with the share used and, on click, the
 * tokens against the window and what they are spent on, largest first, with the free space last.
 */
export function ContextMeter({
  used,
  window,
  shares,
  model,
  cachedTokens = 0,
  reasoningTokens = 0,
  estimated = false,
  updating = false,
}: {
  /** Tokens the conversation occupies (the latest request's input plus its output). */
  used: number;
  /** The model's context window; omit when unknown, and only the count is shown. */
  window?: number | undefined;
  shares: readonly ContextMeterShare[];
  model?: string | undefined;
  cachedTokens?: number;
  reasoningTokens?: number;
  /** The split by source is estimated from message lengths. */
  estimated?: boolean;
  /** A run is in progress: the numbers are from its latest model request. */
  updating?: boolean;
}) {
  const percent = window ? (used / window) * 100 : undefined;
  const tone = level(percent);
  const headline = percentText(used, percent);
  const scale = Math.max(1, window ?? used);
  const visible = shares.filter((item) => item.tokens > 0).sort((a, b) => b.tokens - a.tokens);
  const toneStyle = tone === "ok" ? undefined : { color: LEVEL_COLOR[tone] };
  const summary = window
    ? `Context ${headline ?? ""} used: ${exact(used)} of ${exact(window)} tokens`
    : `Context: ${exact(used)} tokens used`;
  const notes = [
    cachedTokens > 0 ? `${compact(cachedTokens)} input tokens read from cache` : undefined,
    reasoningTokens > 0 ? `${compact(reasoningTokens)} reasoning tokens` : undefined,
  ].filter(Boolean);
  const row = "grid grid-cols-[auto_1fr_auto_3.5rem] items-center gap-x-2.5";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={summary}
          title={summary}
          className="inline-flex h-7 shrink-0 cursor-pointer items-center gap-1.5 rounded-control px-2 text-[12px] whitespace-nowrap text-fg-muted tabular-nums transition-colors hover:bg-surface-hover hover:text-fg"
          style={toneStyle}
        >
          <Ring percent={percent} tone={tone} />
          {headline ? `${headline} used` : `${compact(used)} tokens`}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" className="w-80 p-3.5" aria-label="Context usage">
        <div className="flex flex-col gap-3 text-[13px]">
          <div className="flex items-baseline justify-between gap-3 tabular-nums">
            <span className="font-semibold text-fg" style={toneStyle}>
              {headline ?? `${compact(used)} tokens`}
            </span>
            <span className="text-fg-muted">
              {window ? `${compact(used)} / ${compact(window)}` : "window size unknown"}
            </span>
          </div>
          <div
            role="img"
            aria-label={visible.map((item) => `${item.label} ${exact(item.tokens)}`).join(", ")}
            className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-hover"
          >
            {visible.map((item) => (
              <span
                key={item.key}
                className="h-full transition-[width] duration-500 ease-out motion-reduce:transition-none"
                style={{
                  width: `${String((item.tokens / scale) * 100)}%`,
                  backgroundColor: SHARE_COLORS[item.key] ?? "var(--fg-muted)",
                }}
              />
            ))}
          </div>
          <ul className="flex flex-col gap-1.5 tabular-nums">
            {visible.map((item) => (
              <li key={item.key} className={row}>
                <Swatch color={SHARE_COLORS[item.key] ?? "var(--fg-muted)"} />
                <span className="truncate text-fg-secondary">{item.label}</span>
                <span className="text-right text-fg-secondary">{compact(item.tokens)}</span>
                <span className="text-right text-fg-muted">{share(item.tokens, scale)}</span>
              </li>
            ))}
            {window !== undefined && (
              <li className={row}>
                <Swatch color="var(--fg-muted)" faint />
                <span className="text-fg-secondary">Free space</span>
                <span className="text-right text-fg-secondary">{compact(Math.max(0, window - used))}</span>
                <span className="text-right text-fg-muted">{share(Math.max(0, window - used), window)}</span>
              </li>
            )}
          </ul>
          {notes.length > 0 && (
            <p className="border-t border-border pt-2 text-[11.5px] text-fg-muted">{notes.join(" · ")}</p>
          )}
          <p className="text-[11.5px] leading-snug text-fg-faint">
            {model ? <span className="font-mono">{model}</span> : null}
            {model ? " · " : null}
            {updating ? "updating as the run makes model requests." : "as of the latest model request."}
            {estimated ? " The split by source is estimated from message lengths." : null}
            {tone === "danger" ? " Start a new session to free up room." : null}
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
