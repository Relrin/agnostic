// Ask your OS fixtures: "Why did daily-brief fail last night?" answered from the schedule and the trace, the org's
// AI settings (Ollama on the internal network), and handlers that stream answers as the worker would.
import type {
  AiSettingsIn,
  AiSettingsOut,
  AssistantStatusOut,
  ConversationOut,
  MessageOut,
} from "@agnostic/api";
import { http, HttpResponse } from "msw";

import { API } from "./base";

const T = "2026-11-04T08:00:00Z";

export const ALL_ASSISTANT_FEATURES = {
  assistant: true,
  "assistant.summaries": true,
  "assistant.suggestions": true,
};

export const sampleAiSettings: AiSettingsOut = {
  enabled: true,
  models: { assistant: "ollama:qwen3:8b", summaries: null, suggestions: null },
  endpoint: "http://ollama.internal:11434",
  api_version: null,
  has_api_key: false,
  temperature: 0.1,
  features: { assistant: true, summaries: true, suggestions: true },
  monthly_token_budget: 5_000_000,
  user_monthly_tokens: null,
  requests_per_minute: 10,
  redact_tool_args: false,
  redact_user_messages: true,
  audit_question_text: false,
  retention_days: 90,
  data_notice: "Answers are generated on our own Ollama server.",
  version: 3,
  updated_by: "usr_daniel",
  updated_at: T,
  providers: [
    { id: "openai", label: "OpenAI (Responses API)" },
    { id: "vllm", label: "vLLM" },
    { id: "ollama", label: "Ollama" },
    { id: "openai-like", label: "OpenAI-compatible endpoint" },
    { id: "anthropic", label: "Anthropic" },
    { id: "azure-openai", label: "Azure OpenAI" },
  ],
};

export const sampleAssistantStatus: AssistantStatusOut = {
  features: { assistant: true, summaries: true, suggestions: true },
  can_use: true,
  provider: "ollama",
  data_notice: sampleAiSettings.data_notice,
  budget: {
    month: "2026-11",
    org_tokens: 12_400,
    org_limit: 5_000_000,
    user_tokens: 3_100,
    user_limit: null,
  },
  requests_per_minute: 10,
};

export const DAILY_BRIEF_ANSWER =
  "daily-brief failed because `web_search` timed out twice (30 s each) in *Gather news*, so it never reached *Write brief*.";

export const dailyBriefEvents: ({ event: string; eventId: string } & Record<string, unknown>)[] = [
  { eventId: "1", event: "answer.started", model: "ollama:qwen3:8b" },
  { eventId: "2", event: "answer.tool_started", id: "call_1", name: "get_schedule_runs" },
  {
    eventId: "3",
    event: "answer.tool_completed",
    id: "call_1",
    name: "get_schedule_runs",
    status: "done",
    duration_ms: 120,
  },
  { eventId: "4", event: "answer.tool_started", id: "call_2", name: "get_trace" },
  {
    eventId: "5",
    event: "answer.tool_completed",
    id: "call_2",
    name: "get_trace",
    status: "done",
    duration_ms: 340,
  },
  { eventId: "6", event: "answer.content", delta: DAILY_BRIEF_ANSWER },
  {
    eventId: "7",
    event: "answer.sources",
    sources: [
      {
        kind: "schedule",
        label: "Schedule daily-brief",
        path: "/i/prod-agentos/scheduler?schedule=sch_daily_brief",
      },
      { kind: "trace", label: "Trace daily-brief · 9c1e7d40", path: "/i/prod-agentos/traces/tr_9c1e7d40" },
    ],
  },
  { eventId: "8", event: "answer.completed", content: DAILY_BRIEF_ANSWER, model: "ollama:qwen3:8b" },
];

/** SSE text for a list of answer events. */
export function answerStream(
  events: readonly ({ event: string; eventId?: string } & Record<string, unknown>)[],
): string {
  return events
    .map(({ eventId, ...event }, index) => {
      const data = JSON.stringify(event);
      return `id: ${eventId ?? String(index + 1)}\nevent: ${event.event}\ndata: ${data}\n\n`;
    })
    .join("");
}

export const sampleConversation: ConversationOut = {
  id: "conv_1",
  title: "Why did daily-brief fail last night?",
  created_at: T,
  updated_at: T,
};

export function sampleAnswerMessage(overrides: Partial<MessageOut> = {}): MessageOut {
  return {
    id: "msg_answer",
    conversation_id: "conv_1",
    role: "assistant",
    feature: "assistant",
    kind: "ask",
    content: DAILY_BRIEF_ANSWER,
    status: "completed",
    tool_calls: [
      { id: "call_2", name: "get_schedule_runs", status: "done", duration_ms: 120, detail: null },
      { id: "call_4", name: "get_trace", status: "done", duration_ms: 340, detail: null },
    ],
    sources: [
      { kind: "trace", label: "Trace daily-brief · 9c1e7d40", path: "/i/prod-agentos/traces/tr_9c1e7d40" },
    ],
    model: "ollama:qwen3:8b",
    input_tokens: 2_400,
    output_tokens: 120,
    error: null,
    created_at: T,
    completed_at: T,
    attachments: [],
    generated: true,
    ...overrides,
  };
}

export type AssistantCalls = {
  questions: FormData[];
  explanations: unknown[];
  settings: AiSettingsIn[];
};

export function assistantCalls(): AssistantCalls {
  return { questions: [], explanations: [], settings: [] };
}

/** Everything on, answers streamed from `events` (default: the daily-brief answer). */
export function assistantHandlers(
  calls: AssistantCalls = assistantCalls(),
  options: {
    features?: Record<string, boolean>;
    events?: readonly ({ event: string } & Record<string, unknown>)[];
    settings?: AiSettingsOut;
  } = {},
) {
  let settings = options.settings ?? sampleAiSettings;
  const events = options.events ?? dailyBriefEvents;
  return [
    http.get(`${API}/system/features`, () =>
      HttpResponse.json({ features: options.features ?? ALL_ASSISTANT_FEATURES }),
    ),
    http.get(`${API}/system/modules`, () =>
      HttpResponse.json({
        enabled: [
          {
            name: "assistant",
            version: "0.1.0",
            depends_on: [],
            scopes: [],
            jobs: [],
            audit_actions: [],
            assistant_tools: [],
          },
        ],
        disabled: [],
      }),
    ),
    http.get(`${API}/assistant/status`, () => HttpResponse.json(sampleAssistantStatus)),
    http.get(`${API}/assistant/settings`, () => HttpResponse.json(settings)),
    http.put(`${API}/assistant/settings`, async ({ request }) => {
      const body = (await request.json()) as AiSettingsIn;
      calls.settings.push(body);
      settings = { ...settings, enabled: body.enabled ?? settings.enabled, version: settings.version + 1 };
      return HttpResponse.json(settings);
    }),
    http.post(`${API}/assistant/settings/check`, () =>
      HttpResponse.json({
        ok: true,
        model: "ollama:qwen3:8b",
        latency_ms: 420,
        detail: "The model answered in 420 ms: 'ready'",
      }),
    ),
    http.post(`${API}/instances/:instance/assistant/questions`, async ({ request }) => {
      calls.questions.push(await request.formData());
      return HttpResponse.json(
        { message_id: "msg_answer", conversation_id: "conv_1", reused: false },
        { status: 202 },
      );
    }),
    http.post(`${API}/instances/:instance/assistant/explanations`, async ({ request }) => {
      calls.explanations.push(await request.json());
      return HttpResponse.json(
        { message_id: "msg_explained", conversation_id: null, reused: false },
        { status: 202 },
      );
    }),
    http.get(
      `${API}/instances/:instance/assistant/messages/:message/events`,
      () => new HttpResponse(answerStream(events), { headers: { "Content-Type": "text/event-stream" } }),
    ),
    http.get(`${API}/instances/:instance/assistant/messages/:message`, () =>
      HttpResponse.json(sampleAnswerMessage()),
    ),
    http.get(`${API}/instances/:instance/assistant/conversations`, () =>
      HttpResponse.json([sampleConversation]),
    ),
    http.get(`${API}/instances/:instance/assistant/conversations/:conversation`, () =>
      HttpResponse.json({
        conversation: sampleConversation,
        messages: [
          sampleAnswerMessage({
            id: "msg_question",
            role: "user",
            content: sampleConversation.title,
            tool_calls: [],
            sources: [],
            generated: false,
          }),
          sampleAnswerMessage(),
        ],
      }),
    ),
  ];
}
