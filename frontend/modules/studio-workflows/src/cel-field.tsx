// A node's CEL field (Condition evaluator, Loop end condition, Router selector): CEL or a registered function, the
// expression editor with the context's variables as chips, the server's type and exhaustiveness check as you type,
// and "Try the expression" on a sample, evaluated by the instance's own agno when it can.
import {
  studioCelContextsOptions,
  studioCheckCel,
  studioEvaluateCel,
  type CelEvaluateOut,
} from "@agnostic/api";
import { SuggestButton, useAssistant } from "@agnostic/assistant";
import { withQueryFn } from "@agnostic/core";
import { CelEditor, type CelEditorHandle, type CelSymbol } from "@agnostic/editor";
import { useDebouncedValue } from "@agnostic/studio";
import { Button, Combobox, Input, SegmentedControl, Textarea, cn } from "@agnostic/ui";
import { skipToken, useMutation, useQuery } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Play } from "lucide-react";
import { useMemo, useRef, useState } from "react";

export type CelContext = "condition" | "router" | "loop";

const CHECK_MS = 300;

function useSymbols(context: CelContext): { symbols: CelSymbol[]; variables: string[] } {
  const query = useQuery({ ...withQueryFn(studioCelContextsOptions()), staleTime: Infinity });
  return useMemo(() => {
    const data = query.data;
    const variables = data?.contexts[context]?.variables ?? [];
    const symbols: CelSymbol[] = [
      ...variables.map((item) => ({
        name: item.name,
        detail: item.type,
        doc: item.doc,
        kind: "variable" as const,
      })),
      ...(data?.functions ?? []).map((item) => ({
        name: item.name,
        detail: item.signature,
        doc: item.doc,
        kind: item.method ? ("method" as const) : ("function" as const),
      })),
      ...(data?.macros ?? []).map((item) => ({
        name: item.name,
        detail: item.name,
        doc: item.doc,
        kind: "macro" as const,
      })),
    ];
    return { symbols, variables: variables.map((item) => item.name) };
  }, [query.data, context]);
}

export function CelField({
  id,
  label,
  instance,
  context,
  value,
  kind,
  choices,
  functions,
  readOnly,
  onChange,
}: {
  id: string;
  label: string;
  instance: string;
  context: CelContext;
  value: unknown;
  /** `cel` or `function` (a Condition's `bool` shows as CEL `true`/`false`). */
  kind: string | undefined;
  /** A Router's choice names. */
  choices?: string[] | undefined;
  functions: string[];
  readOnly: boolean;
  onChange: (value: string | undefined, kind: "cel" | "function") => void;
}) {
  const mode = kind === "function" ? "function" : "cel";
  const text = typeof value === "string" ? value : typeof value === "boolean" ? String(value) : "";
  const editor = useRef<CelEditorHandle>(null);
  const { symbols, variables } = useSymbols(context);
  const settled = useDebouncedValue(text, CHECK_MS);
  const check = useQuery({
    queryKey: ["studio", "cel", "check", context, settled, choices ?? null],
    queryFn:
      mode === "cel" && settled.trim()
        ? async () =>
            (
              await studioCheckCel({
                body: { expression: settled, context, choices: choices ?? null },
                throwOnError: true,
              })
            ).data
        : skipToken,
    staleTime: Infinity,
    retry: false,
  });
  const result = settled === text ? check.data : undefined;
  const diagnostics = useMemo(
    () =>
      (result?.findings ?? [])
        .filter((item) => item.severity !== "info")
        .map((item) => ({
          from: item.span.start,
          to: item.span.end,
          severity: item.severity,
          message: item.message,
        })),
    [result],
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="text-[12.5px] font-medium text-fg-secondary">
          {label}
        </label>
        <span className="flex-1" />
        <SegmentedControl
          size="mini"
          label={`${label}: CEL or a function`}
          value={mode}
          onValueChange={(next) => {
            if (readOnly) return;
            onChange(next === "cel" ? "" : functions[0], next);
          }}
          options={[
            { value: "cel", label: "CEL" },
            { value: "function", label: "Python fn" },
          ]}
        />
      </div>
      {mode === "function" ? (
        <Combobox
          id={id}
          aria-label={`${label} function`}
          mono
          value={text || undefined}
          placeholder={functions.length ? "Pick a registered function" : "No functions registered"}
          options={functions.map((name) => ({ value: name, label: name }))}
          disabled={readOnly}
          onValueChange={(name) => {
            onChange(name, "function");
          }}
        />
      ) : (
        <>
          <div id={id}>
            <CelEditor
              ref={editor}
              value={text}
              onChange={(next) => {
                onChange(next, "cel");
              }}
              symbols={symbols}
              diagnostics={diagnostics}
              ariaLabel={`${label} expression`}
              placeholder={
                context === "router" ? '"Choice name" or a ternary' : "An expression returning bool"
              }
              readOnly={readOnly}
            />
          </div>
          {text.trim() && (
            <p
              className={cn(
                "inline-flex items-center gap-1.5 text-[12px]",
                result && !result.ok ? "text-danger" : "text-fg-secondary",
              )}
              aria-live="polite"
            >
              {result?.ok ? (
                <CircleCheck aria-hidden className="size-3.5 text-accent" />
              ) : result ? (
                <CircleAlert aria-hidden className="size-3.5" />
              ) : null}
              {result ? result.summary : "Checking…"}
            </p>
          )}
          {!readOnly && variables.length > 0 && (
            <div className="flex flex-wrap gap-1.5" aria-label="Variables">
              {variables.map((name) => (
                <button
                  key={name}
                  type="button"
                  className="rounded-type border border-border px-1.5 py-0.5 font-mono text-[11px] text-fg-secondary hover:border-accent hover:text-accent"
                  onClick={() => editor.current?.insert(name)}
                >
                  {name}
                </button>
              ))}
            </div>
          )}
          {!readOnly && (
            <CelFromDescription
              instance={instance}
              context={context}
              choices={choices}
              symbols={symbols}
              onUse={(expression) => {
                onChange(expression, "cel");
              }}
            />
          )}
          <Sandbox instance={instance} context={context} expression={text} choices={choices} />
        </>
      )}
    </div>
  );
}

/** Describe the condition in words; the suggestion is checked like a typed expression before it can be used. */
function CelFromDescription({
  instance,
  context,
  choices,
  symbols,
  onUse,
}: {
  instance: string;
  context: CelContext;
  choices: string[] | undefined;
  symbols: readonly CelSymbol[];
  onUse: (expression: string) => void;
}) {
  const { available } = useAssistant("suggestions");
  const [description, setDescription] = useState("");
  const validate = useMemo(
    () => async (expression: string) => {
      const checked = (
        await studioCheckCel({ body: { expression, context, choices: choices ?? null }, throwOnError: true })
      ).data;
      return checked.ok ? undefined : `The suggestion doesn't check: ${checked.summary}`;
    },
    [context, choices],
  );
  if (!available) return null;
  return (
    <div className="flex items-center gap-2">
      <Input
        aria-label="Describe the expression"
        className="h-8"
        placeholder="Describe it: “the customer is on the gold tier and asked about billing”"
        value={description}
        onChange={(event) => {
          setDescription(event.target.value);
        }}
      />
      <SuggestButton
        key={description}
        instance={instance}
        label="Write CEL"
        disabled={!description.trim()}
        request={{
          kind: "studio.cel",
          subject: { description: description.trim() },
          material: {
            context,
            choices: choices ?? [],
            symbols: symbols.map((symbol) => ({ name: symbol.name, kind: symbol.kind, type: symbol.detail })),
          },
        }}
        validate={validate}
        onUse={onUse}
      />
    </div>
  );
}

function Sandbox({
  instance,
  context,
  expression,
  choices,
}: {
  instance: string;
  context: CelContext;
  expression: string;
  choices?: string[] | undefined;
}) {
  const [input, setInput] = useState("");
  const [previous, setPrevious] = useState("");
  const [iteration, setIteration] = useState("1");
  const evaluate = useMutation({
    mutationFn: async () => {
      const sample: Record<string, unknown> =
        context === "loop"
          ? { last_step_content: previous, current_iteration: Number(iteration) || 1 }
          : { input, previous_step_content: previous };
      return (
        await studioEvaluateCel({
          path: { instance },
          body: { expression, context, sample, choices: choices ?? null },
          throwOnError: true,
        })
      ).data;
    },
  });
  const answer: CelEvaluateOut | undefined = evaluate.data;
  return (
    <section aria-label="Try the expression" className="flex flex-col gap-2 rounded-control bg-inset p-3">
      <h3 className="text-[12px] font-medium text-fg-secondary">Try the expression</h3>
      {context === "loop" ? (
        <div className="flex gap-2">
          <Input
            aria-label="last_step_content"
            placeholder="last_step_content"
            value={previous}
            onChange={(event) => {
              setPrevious(event.target.value);
            }}
          />
          <Input
            aria-label="current_iteration"
            className="w-20"
            inputMode="numeric"
            value={iteration}
            onChange={(event) => {
              setIteration(event.target.value);
            }}
          />
        </div>
      ) : (
        <>
          <Textarea
            aria-label="Sample input"
            rows={2}
            placeholder="I was charged twice, need a refund"
            value={input}
            onChange={(event) => {
              setInput(event.target.value);
            }}
          />
          <Input
            aria-label="previous_step_content"
            placeholder="previous_step_content"
            value={previous}
            onChange={(event) => {
              setPrevious(event.target.value);
            }}
          />
        </>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="28"
          disabled={!expression.trim() || evaluate.isPending}
          onClick={() => {
            evaluate.mutate();
          }}
        >
          <Play aria-hidden />
          Evaluate
        </Button>
        {answer && (
          <span
            aria-live="polite"
            className={cn("font-mono text-[12px]", answer.error ? "text-danger" : "text-accent")}
          >
            {answer.error ?? `→ ${JSON.stringify(answer.result)}`}
          </span>
        )}
      </div>
      {answer && (
        <p className="text-[11px] text-fg-muted">
          {answer.evaluator === "agno" ? "Evaluated by agno on the instance." : answer.note}
        </p>
      )}
    </section>
  );
}
