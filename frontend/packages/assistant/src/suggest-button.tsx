// "Suggest …" next to a field: the model drafts, the page may validate the draft (e.g. a CEL check), and the
// person inserts it with "Use". Nothing is applied on its own.
import { Badge, Button, Popover, PopoverContent, PopoverTrigger } from "@agnostic/ui";
import { RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { settled } from "./answer";
import { useExplanation, type ExplanationRequest } from "./requests";
import { useAssistant, type AssistantFeature } from "./use-assistant";

export function SuggestButton({
  instance,
  request,
  label,
  feature = "suggestions",
  onUse,
  validate,
  disabled = false,
}: {
  instance: string;
  request: ExplanationRequest;
  /** "Suggest message", "From description". */
  label: string;
  feature?: AssistantFeature;
  onUse: (text: string) => void;
  /** A reason the draft can't be used, or undefined when it can. */
  validate?: ((text: string) => Promise<string | undefined>) | undefined;
  disabled?: boolean;
}) {
  const { available } = useAssistant(feature);
  const explanation = useExplanation(instance, request);
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState<{ content: string; problem: string | undefined }>();
  const { state } = explanation;
  const done = explanation.requested && settled(state);
  const ready = done && state.status === "completed";
  const problem = checked?.content === state.content ? checked.problem : undefined;
  const validating = ready && validate !== undefined && checked?.content !== state.content;

  useEffect(() => {
    if (!ready || !validate) return;
    let current = true;
    const content = state.content;
    void validate(content).then((reason) => {
      if (current) setChecked({ content, problem: reason });
    });
    return () => {
      current = false;
    };
  }, [ready, state.content, validate]);

  if (!available) return null;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="28"
          disabled={disabled}
          onClick={() => {
            if (!explanation.requested) void explanation.start();
          }}
        >
          <Sparkles aria-hidden /> {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="flex w-[420px] flex-col gap-2" aria-label={label}>
        <header className="flex items-center gap-2 text-[12px] text-fg-muted">
          <Badge tone="info">Generated</Badge>
          <span>{state.model ? `by ${state.model}` : done ? null : "writing…"}</span>
        </header>
        {state.content && (
          <pre className="max-h-64 overflow-auto rounded-control bg-inset p-2 font-mono text-[12px] whitespace-pre-wrap text-fg-prose">
            {state.content}
          </pre>
        )}
        {(state.status === "failed" || explanation.error) && (
          <p role="alert" className="text-[12px] text-danger">
            {state.error ?? explanation.error}
          </p>
        )}
        {problem && (
          <p role="alert" className="text-[12px] text-warning">
            {problem}
          </p>
        )}
        <div className="flex justify-end gap-1.5">
          <Button
            variant="ghost"
            size="28"
            disabled={!done || explanation.pending}
            onClick={() => void explanation.start(true)}
          >
            <RefreshCw aria-hidden /> Regenerate
          </Button>
          <Button
            variant="primary"
            size="28"
            disabled={!ready || validating || problem !== undefined}
            onClick={() => {
              onUse(state.content);
              setOpen(false);
            }}
          >
            Use
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
