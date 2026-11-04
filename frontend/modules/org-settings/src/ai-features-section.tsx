// AI features: which model answers "Ask your OS" and writes explanations, what it may see, and how much it may
// spend. Off (the default): no model is called and nothing AI-related shows outside this section.
import {
  assistantCheckConnectionMutation,
  assistantGetSettingsOptions,
  assistantGetSettingsQueryKey,
  assistantUpdateSettingsMutation,
  describeError,
  systemListFeaturesQueryKey,
  type AiSettingsIn,
  type AiSettingsOut,
} from "@agnostic/api";
import { formatWhen, useReauth, withQueryFn, withReauth } from "@agnostic/core";
import {
  Button,
  Callout,
  ErrorState,
  Field,
  Input,
  LoadingRows,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
  toast,
} from "@agnostic/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { Section, optionalNumber, useWritable } from "./shared";

type AiForm = {
  enabled: boolean;
  provider: string;
  model: string;
  summariesModel: string;
  suggestionsModel: string;
  endpoint: string;
  apiVersion: string;
  /** `undefined` keeps the saved key, "" removes it. */
  apiKey: string | undefined;
  temperature: string;
  assistant: boolean;
  summaries: boolean;
  suggestions: boolean;
  monthlyBudget: string;
  userBudget: string;
  requestsPerMinute: string;
  redactToolArgs: boolean;
  redactUserMessages: boolean;
  auditQuestionText: boolean;
  retentionDays: string;
  notice: string;
};

const ENDPOINT_HINT: Record<string, string> = {
  vllm: "The OpenAI-compatible base URL of your vLLM server, e.g. http://vllm.internal:8000/v1.",
  ollama: "Your Ollama server, e.g. http://ollama.internal:11434.",
  "openai-like": "Any OpenAI-compatible base URL (LiteLLM, LM Studio, llama.cpp, a gateway).",
  "azure-openai":
    "Your Azure OpenAI resource, e.g. https://acme.openai.azure.com. The model is the deployment name.",
  openai: "Empty uses api.openai.com.",
  "openai-chat": "Empty uses api.openai.com.",
  anthropic: "Empty uses api.anthropic.com.",
};

function aiForm(settings: AiSettingsOut): AiForm {
  const assistant = settings.models.assistant ?? "";
  const [provider = "ollama", ...rest] = assistant.split(":");
  return {
    enabled: settings.enabled,
    provider: assistant ? provider : "ollama",
    model: rest.join(":"),
    summariesModel: settings.models.summaries ?? "",
    suggestionsModel: settings.models.suggestions ?? "",
    endpoint: settings.endpoint ?? "",
    apiVersion: settings.api_version ?? "",
    apiKey: undefined,
    temperature: String(settings.temperature),
    assistant: settings.features.assistant ?? true,
    summaries: settings.features.summaries ?? true,
    suggestions: settings.features.suggestions ?? true,
    monthlyBudget: settings.monthly_token_budget === null ? "" : String(settings.monthly_token_budget),
    userBudget: settings.user_monthly_tokens === null ? "" : String(settings.user_monthly_tokens),
    requestsPerMinute: String(settings.requests_per_minute),
    redactToolArgs: settings.redact_tool_args,
    redactUserMessages: settings.redact_user_messages,
    auditQuestionText: settings.audit_question_text,
    retentionDays: String(settings.retention_days),
    notice: settings.data_notice ?? "",
  };
}

/** The PUT body: every field the form shows; the key only when typed (or "" to remove it). */
export function aiBody(form: AiForm, version: number): AiSettingsIn {
  const model = form.model.trim();
  return {
    enabled: form.enabled,
    models: {
      assistant: model ? `${form.provider}:${model}` : "",
      summaries: form.summariesModel.trim(),
      suggestions: form.suggestionsModel.trim(),
    },
    endpoint: form.endpoint.trim() || null,
    api_version: form.apiVersion.trim() || null,
    temperature: optionalNumber(form.temperature) ?? 0.1,
    features: { assistant: form.assistant, summaries: form.summaries, suggestions: form.suggestions },
    monthly_token_budget: optionalNumber(form.monthlyBudget) ?? 0,
    user_monthly_tokens: optionalNumber(form.userBudget) ?? 0,
    requests_per_minute: optionalNumber(form.requestsPerMinute) ?? 10,
    redact_tool_args: form.redactToolArgs,
    redact_user_messages: form.redactUserMessages,
    audit_question_text: form.auditQuestionText,
    retention_days: optionalNumber(form.retentionDays) ?? 90,
    data_notice: form.notice.trim() || null,
    version,
    ...(form.apiKey !== undefined ? { api_key: form.apiKey } : {}),
  };
}

function text(
  label: string,
  value: string,
  onChange: (value: string) => void,
  options: { hint?: string; placeholder?: string; type?: string; mono?: boolean } = {},
) {
  return (
    <Field label={label} hint={options.hint}>
      {({ id, describedBy }) => (
        <Input
          id={id}
          mono={options.mono ?? true}
          type={options.type ?? "text"}
          placeholder={options.placeholder}
          aria-describedby={describedBy}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      )}
    </Field>
  );
}

function SettingsForm({ settings, writable }: { settings: AiSettingsOut; writable: boolean }) {
  const queryClient = useQueryClient();
  const reauth = useReauth();
  const [form, setForm] = useState(() => aiForm(settings));
  const dirty = JSON.stringify(form) !== JSON.stringify(aiForm(settings));
  const set =
    <K extends keyof AiForm>(key: K) =>
    (value: AiForm[K]) => {
      setForm((current) => ({ ...current, [key]: value }));
    };
  const save = useMutation({
    ...withReauth(reauth, assistantUpdateSettingsMutation()),
    onSuccess: (data) => {
      queryClient.setQueryData(assistantGetSettingsQueryKey(), data);
      void queryClient.invalidateQueries({ queryKey: systemListFeaturesQueryKey() });
      setForm(aiForm(data));
      toast("AI features saved");
    },
  });
  const check = useMutation(assistantCheckConnectionMutation());

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate({ body: aiBody(form, settings.version) });
  };

  const keyHint =
    form.apiKey === ""
      ? "The saved key is removed when you save."
      : settings.has_api_key
        ? "Saved. Leave empty to keep it."
        : "Write-only: stored encrypted. Self-hosted servers often need none.";

  return (
    <form className="flex flex-col gap-5" onSubmit={submit}>
      <Callout tone="info" title="What leaves the control plane">
        When AI features are on, a question, what the assistant's tools return for it (traces, sessions,
        schedules, approvals, configuration, the audit log, all limited to what the asking person may see) and
        attached files are sent to the provider below. Pick a local provider (vLLM, Ollama, an
        OpenAI-compatible server) to keep everything inside your network, and use redaction to leave tool
        arguments and end-user messages out.
      </Callout>
      <Section
        title="Provider"
        description="The model that answers Ask your OS. Summaries and suggestions use it too unless you name another."
      >
        <fieldset disabled={!writable} className="flex flex-col gap-4">
          <Switch
            label="AI features"
            description="Off: no model is called, and Ask your OS and the AI explanations don't show anywhere."
            checked={form.enabled}
            disabled={!writable}
            onCheckedChange={set("enabled")}
          />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Provider">
              {({ id }) => (
                <Select value={form.provider} onValueChange={set("provider")} disabled={!writable}>
                  <SelectTrigger id={id} aria-label="Provider">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {settings.providers.map((provider) => (
                      <SelectItem key={provider.id} value={provider.id}>
                        {provider.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
            {text("Model", form.model, set("model"), {
              placeholder: form.provider === "ollama" ? "qwen3:8b" : "Qwen/Qwen3-32B",
              hint: "As the provider names it.",
            })}
            {text("Endpoint", form.endpoint, set("endpoint"), {
              placeholder: "http://vllm.internal:8000/v1",
              hint: ENDPOINT_HINT[form.provider] ?? "",
            })}
            <Field label="API key" hint={keyHint}>
              {({ id, describedBy }) => (
                <div className="flex items-center gap-2">
                  <Input
                    id={id}
                    type="password"
                    mono
                    autoComplete="off"
                    placeholder={settings.has_api_key && form.apiKey === undefined ? "•••••• (saved)" : ""}
                    aria-describedby={describedBy}
                    value={form.apiKey ?? ""}
                    onChange={(event) => {
                      set("apiKey")(event.target.value === "" ? undefined : event.target.value);
                    }}
                  />
                  {settings.has_api_key && form.apiKey === undefined && (
                    <Button
                      size="30"
                      variant="ghost"
                      onClick={() => {
                        set("apiKey")("");
                      }}
                    >
                      Remove
                    </Button>
                  )}
                </div>
              )}
            </Field>
            {form.provider === "azure-openai" &&
              text("API version", form.apiVersion, set("apiVersion"), { placeholder: "2026-10-01-preview" })}
            {text("Temperature", form.temperature, set("temperature"), {
              type: "number",
              hint: "Low keeps answers close to the data (default 0.1).",
              mono: false,
            })}
            {text("Summaries model", form.summariesModel, set("summariesModel"), {
              placeholder: "provider:model (empty: the assistant's)",
            })}
            {text("Suggestions model", form.suggestionsModel, set("suggestionsModel"), {
              placeholder: "provider:model (empty: the assistant's)",
            })}
          </div>
        </fieldset>
        {check.data && (
          <Callout
            tone={check.data.ok ? "insight" : "danger"}
            title={check.data.ok ? "The model answered" : "The model didn't answer"}
          >
            {check.data.detail}
          </Callout>
        )}
      </Section>
      <Section title="Features" description="Each can be turned off on its own.">
        <fieldset disabled={!writable} className="flex flex-col gap-3">
          <Switch
            label="Ask your OS"
            description="Questions on Home and the Ask page, the Traces follow-ups, and free-text permission checks."
            checked={form.assistant}
            disabled={!writable}
            onCheckedChange={set("assistant")}
          />
          <Switch
            label="Summaries"
            description="Rewritten trace diagnoses, eval insights, change summaries, config and audit explanations."
            checked={form.summaries}
            disabled={!writable}
            onCheckedChange={set("summaries")}
          />
          <Switch
            label="Suggestions"
            description="Drafts people insert themselves: commit messages, release notes, CEL from a description."
            checked={form.suggestions}
            disabled={!writable}
            onCheckedChange={set("suggestions")}
          />
        </fieldset>
      </Section>
      <Section title="Data handling" description="What the model sees, and what is kept.">
        <fieldset disabled={!writable} className="flex flex-col gap-3">
          <Switch
            label="Leave out tool arguments"
            description="Arguments runtimes passed to tools (search queries, customer ids) are replaced with [redacted]."
            checked={form.redactToolArgs}
            disabled={!writable}
            onCheckedChange={set("redactToolArgs")}
          />
          <Switch
            label="Leave out end-user messages"
            description="What people typed into your agents (run inputs, session messages) is replaced with [redacted]."
            checked={form.redactUserMessages}
            disabled={!writable}
            onCheckedChange={set("redactUserMessages")}
          />
          <Switch
            label="Keep the question text in the audit log"
            description="Off: the audit log records who asked, the tools used and the sources, not the question."
            checked={form.auditQuestionText}
            disabled={!writable}
            onCheckedChange={set("auditQuestionText")}
          />
          <div className="grid grid-cols-2 gap-3">
            {text("Keep conversations for (days)", form.retentionDays, set("retentionDays"), {
              type: "number",
              hint: "Default 90 days.",
              mono: false,
            })}
          </div>
          <Field
            label="Notice under the Ask box"
            hint="E.g. “Answers are generated on our own vLLM cluster.”"
          >
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                rows={2}
                aria-describedby={describedBy}
                value={form.notice}
                className="font-sans"
                onChange={(event) => {
                  set("notice")(event.target.value);
                }}
              />
            )}
          </Field>
        </fieldset>
      </Section>
      <Section
        title="Limits"
        description="Empty budgets mean no limit. Budgets reset on the first of each month (UTC)."
      >
        <fieldset disabled={!writable} className="grid grid-cols-3 gap-3">
          {text("Organization tokens per month", form.monthlyBudget, set("monthlyBudget"), {
            type: "number",
            mono: false,
          })}
          {text("Tokens per person per month", form.userBudget, set("userBudget"), {
            type: "number",
            mono: false,
          })}
          {text("Requests per person per minute", form.requestsPerMinute, set("requestsPerMinute"), {
            type: "number",
            mono: false,
          })}
        </fieldset>
      </Section>
      {(save.error ?? check.error) && (
        <Callout tone="danger">{describeError(save.error ?? check.error).reason}</Callout>
      )}
      {writable && (
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" disabled={!dirty || save.isPending}>
            {save.isPending ? "Saving…" : "Save AI features"}
          </Button>
          <Button
            variant="secondary"
            disabled={dirty || !settings.models.assistant || check.isPending}
            title={dirty ? "Save first: the test uses the saved settings." : undefined}
            onClick={() => {
              check.mutate({ body: { feature: "assistant" } });
            }}
          >
            {check.isPending ? "Asking…" : "Test connection"}
          </Button>
          {settings.updated_at && (
            <span className="text-[12px] text-fg-muted">Last changed {formatWhen(settings.updated_at)}</span>
          )}
        </div>
      )}
    </form>
  );
}

export function AiFeaturesSection() {
  const { writable, note } = useWritable("settings:write");
  const settings = useQuery(withQueryFn(assistantGetSettingsOptions()));
  return (
    <div className="flex flex-col gap-5">
      {note}
      {settings.isPending ? (
        <LoadingRows rows={4} label="Loading AI features" />
      ) : settings.isError ? (
        <ErrorState reason={describeError(settings.error).reason} onRetry={() => void settings.refetch()} />
      ) : (
        <SettingsForm key={settings.data.version} settings={settings.data} writable={writable} />
      )}
    </div>
  );
}
