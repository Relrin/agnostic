// Next to a page's own (deterministic) text: an on-demand, labelled AI rewrite or explanation that can be
// regenerated. Nothing renders beyond `children` when the feature is off.
import { Badge, Button, Callout, MarkdownView } from "@agnostic/ui";
import { RefreshCw, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { settled } from "./answer";
import { SourceList, ToolChips } from "./answer-view";
import { useExplanation, type ExplanationRequest } from "./requests";
import { useAssistant, type AssistantFeature } from "./use-assistant";

export function GeneratedText({
  instance,
  request,
  feature = "summaries",
  action = "Rewrite with AI",
  label = "Generated",
  children,
}: {
  instance: string;
  request: ExplanationRequest;
  feature?: AssistantFeature;
  /** The button that asks for it: "Rewrite with AI", "Explain", "Summarize". */
  action?: string;
  label?: string;
  /** The page's own text, always shown. */
  children?: ReactNode;
}) {
  const { available } = useAssistant(feature);
  const explanation = useExplanation(instance, request);
  if (!available) return <>{children}</>;
  const { state } = explanation;
  const writing = explanation.requested && !settled(state);
  return (
    <div className="flex flex-col gap-2">
      {children}
      {!explanation.requested ? (
        <div>
          <Button
            variant="ghost"
            size="28"
            disabled={explanation.pending}
            onClick={() => void explanation.start()}
          >
            <Sparkles aria-hidden /> {action}
          </Button>
          {explanation.error && <p className="text-[12px] text-danger">{explanation.error}</p>}
        </div>
      ) : (
        <section
          aria-label={label}
          aria-busy={writing}
          className="flex flex-col gap-2 rounded-tile border border-border-strong bg-inset px-3 py-2.5"
        >
          <header className="flex items-center gap-2 text-[12px] text-fg-muted">
            <Badge tone="info">{label}</Badge>
            <span>{state.model ? `by ${state.model}` : writing ? "writing…" : null}</span>
            <span className="flex-1" />
            {!writing && (
              <Button
                variant="ghost"
                size="28"
                aria-label="Regenerate"
                disabled={explanation.pending}
                onClick={() => void explanation.start(true)}
              >
                <RefreshCw aria-hidden /> Regenerate
              </Button>
            )}
          </header>
          {state.tools.length > 0 && writing && (
            <div className="flex flex-wrap gap-1.5">
              <ToolChips tools={state.tools} />
            </div>
          )}
          {state.content && <MarkdownView className="text-[13px]">{state.content}</MarkdownView>}
          {state.status === "failed" && <Callout tone="danger">{state.error}</Callout>}
          {explanation.error && <Callout tone="danger">{explanation.error}</Callout>}
          <SourceList sources={state.sources} />
        </section>
      )}
    </div>
  );
}
