// An answer as it is written: the worker's events (`…/messages/{id}/events`) folded into one state, with
// reconnects that resume from Last-Event-ID and a fallback to the stored answer.
import {
  apiUrl,
  assistantCancelMessage,
  assistantGetMessage,
  describeError,
  type MessageOut,
} from "@agnostic/api";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useCallback, useEffect, useReducer } from "react";

export type AnswerTool = {
  id: string;
  name: string;
  status: "running" | "done" | "denied" | "not_found" | "error";
  durationMs?: number | null | undefined;
  detail?: string | null | undefined;
};

export type AnswerSource = { kind: string; label: string; path: string };

export type AnswerStatus = "idle" | "queued" | "streaming" | "completed" | "failed" | "cancelled";

export type AnswerState = {
  status: AnswerStatus;
  content: string;
  tools: AnswerTool[];
  sources: AnswerSource[];
  model: string | null;
  error: string | null;
  tokens: number | null;
};

export type AnswerEvent = { event: string } & Record<string, unknown>;

export const initialAnswer: AnswerState = {
  status: "idle",
  content: "",
  tools: [],
  sources: [],
  model: null,
  error: null,
  tokens: null,
};

const TERMINAL = new Set(["answer.completed", "answer.failed", "answer.cancelled"]);
const RETRIES = [500, 1500, 4000];

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function settled(state: AnswerState): boolean {
  return state.status === "completed" || state.status === "failed" || state.status === "cancelled";
}

export function reduceAnswer(state: AnswerState, event: AnswerEvent | { event: "reset" }): AnswerState {
  switch (event.event) {
    case "reset":
      return initialAnswer;
    case "answer.started":
      return { ...state, status: "streaming", model: text(event.model) || state.model };
    case "answer.tool_started": {
      const id = text(event.id);
      if (state.tools.some((tool) => tool.id === id)) return state;
      return {
        ...state,
        status: "streaming",
        tools: [...state.tools, { id, name: text(event.name), status: "running" }],
      };
    }
    case "answer.tool_completed": {
      const done = event;
      const finished: AnswerTool = {
        id: text(done.id),
        name: text(done.name),
        status: (text(done.status) || "done") as AnswerTool["status"],
        durationMs: typeof done.duration_ms === "number" ? done.duration_ms : null,
        detail: text(done.detail) || null,
      };
      const known = state.tools.some((tool) => tool.id === finished.id);
      return {
        ...state,
        tools: known
          ? state.tools.map((tool) => (tool.id === finished.id ? finished : tool))
          : [...state.tools, finished],
      };
    }
    case "answer.content":
      return { ...state, status: "streaming", content: state.content + text(event.delta) };
    case "answer.sources": {
      const sources = event.sources;
      return { ...state, sources: Array.isArray(sources) ? (sources as AnswerSource[]) : [] };
    }
    case "answer.completed": {
      const done = event;
      const tokens = Number(done.input_tokens ?? 0) + Number(done.output_tokens ?? 0);
      return {
        ...state,
        status: "completed",
        content: text(done.content) || state.content,
        model: text(done.model) || state.model,
        tokens,
      };
    }
    case "answer.failed":
      return { ...state, status: "failed", error: text(event.reason) || "The answer failed." };
    case "answer.cancelled":
      return { ...state, status: "cancelled", content: text(event.content) || state.content };
    default:
      return state;
  }
}

/** A stored message, as the state its stream would have reached. */
export function fromMessage(message: MessageOut): AnswerState {
  const status: AnswerStatus =
    message.status === "queued" ? "queued" : message.status === "running" ? "streaming" : message.status;
  return {
    status,
    content: message.content,
    tools: message.tool_calls.map((call) => ({
      id: call.id,
      name: call.name,
      status: call.status,
      durationMs: call.duration_ms,
      detail: call.detail,
    })),
    sources: message.sources,
    model: message.model,
    error: message.error,
    tokens: message.input_tokens + message.output_tokens || null,
  };
}

function messagesPath(instance: string, messageId: string): string {
  return `/api/v1/instances/${encodeURIComponent(instance)}/assistant/messages/${encodeURIComponent(messageId)}`;
}

class Closed extends Error {}

/** Follows one answer until it settles; `undefined` follows nothing. */
export function useAnswer(instance: string, messageId: string | undefined) {
  const [state, dispatch] = useReducer(reduceAnswer, initialAnswer);

  useEffect(() => {
    dispatch({ event: "reset" });
    if (!messageId) return;
    const controller = new AbortController();
    let lastId: string | undefined;
    const progress = { done: false };
    // Read through a function: the flags change inside callbacks, after the checks below.
    const stopped = () => progress.done || controller.signal.aborted;
    const run = async () => {
      for (let attempt = 0; attempt <= RETRIES.length && !stopped(); attempt += 1) {
        try {
          await fetchEventSource(apiUrl(`${messagesPath(instance, messageId)}/events`), {
            method: "GET",
            headers: { Accept: "text/event-stream", ...(lastId ? { "Last-Event-ID": lastId } : {}) },
            credentials: "same-origin",
            signal: controller.signal,
            openWhenHidden: true,
            onopen: async (response) => {
              if (!response.ok) throw new Closed(`HTTP ${String(response.status)}`);
              await Promise.resolve();
            },
            onmessage: (message) => {
              if (message.id) lastId = message.id;
              if (!message.data) return;
              const event = JSON.parse(message.data) as AnswerEvent;
              if (TERMINAL.has(event.event)) progress.done = true;
              dispatch(event);
            },
            onerror: (error: unknown) => {
              throw error;
            },
          });
        } catch (error) {
          if (error instanceof Closed) break;
        }
        if (stopped()) return;
        await new Promise((resolve) => setTimeout(resolve, RETRIES[attempt] ?? 0));
      }
      if (stopped()) return;
      // The stream is gone (proxy, sleep): the stored answer is the truth.
      try {
        const stored = await assistantGetMessage({
          path: { instance, message_id: messageId },
          throwOnError: true,
          signal: controller.signal,
        });
        const message = fromMessage(stored.data);
        if (settled(message)) {
          dispatch({ event: "answer.sources", sources: message.sources });
          for (const tool of message.tools)
            dispatch({ event: "answer.tool_completed", ...tool, duration_ms: tool.durationMs });
          dispatch(
            message.status === "completed"
              ? { event: "answer.completed", content: message.content, model: message.model }
              : message.status === "cancelled"
                ? { event: "answer.cancelled", content: message.content }
                : { event: "answer.failed", reason: message.error ?? "The answer failed." },
          );
        } else {
          dispatch({ event: "answer.failed", reason: "Lost the connection; reload to see the answer." });
        }
      } catch (error) {
        if (!stopped()) dispatch({ event: "answer.failed", reason: describeError(error).reason });
      }
    };
    void run();
    return () => {
      controller.abort();
    };
  }, [instance, messageId]);

  const stop = useCallback(async () => {
    if (!messageId) return;
    await assistantCancelMessage({ path: { instance, message_id: messageId } });
  }, [instance, messageId]);

  return { state, stop };
}
