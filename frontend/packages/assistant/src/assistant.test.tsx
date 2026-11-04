import {
  API,
  assistantCalls,
  assistantHandlers,
  dailyBriefEvents,
  sampleOrgHandlers,
  renderPage,
} from "@agnostic/testing";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { initialAnswer, reduceAnswer, type AnswerEvent } from "./answer";
import { GeneratedText } from "./generated-text";
import { completion, suggestionsFor } from "./suggestions";

const server = setupServer(...sampleOrgHandlers());

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
});
afterEach(() => {
  server.resetHandlers(...sampleOrgHandlers());
});
afterAll(() => {
  server.close();
});

describe("answer events", () => {
  it("fold into chips, text, sources and a completed answer", () => {
    const state = (dailyBriefEvents as AnswerEvent[]).reduce(reduceAnswer, initialAnswer);
    expect(state.status).toBe("completed");
    expect(state.tools.map((tool) => [tool.name, tool.status])).toEqual([
      ["get_schedule_runs", "done"],
      ["get_trace", "done"],
    ]);
    expect(state.content).toContain("never reached");
    expect(state.sources).toHaveLength(2);
    expect(state.model).toBe("ollama:qwen3:8b");
  });

  it("report failures and keep what was written when stopped", () => {
    const failed = reduceAnswer(initialAnswer, {
      event: "answer.failed",
      reason: "The model provider returned an error",
    });
    expect([failed.status, failed.error]).toEqual(["failed", "The model provider returned an error"]);
    const written = reduceAnswer(initialAnswer, { event: "answer.content", delta: "Half an" });
    expect(reduceAnswer(written, { event: "answer.cancelled" })).toMatchObject({
      status: "cancelled",
      content: "Half an",
    });
  });
});

describe("suggestions", () => {
  it("put failing components first and complete what was typed", () => {
    const templates = suggestionsFor("home", ["daily-brief"]);
    expect(templates[0]).toBe("Why did daily-brief fail last night?");
    expect(completion("why did d", templates)).toBe("aily-brief fail last night?");
    expect(completion("Which agent", templates)).toBe(" used the most tokens this week?");
    expect(completion("Something else entirely", templates)).toBe("");
  });
});

function Diagnosis() {
  return (
    <GeneratedText
      instance="prod-agentos"
      request={{ kind: "trace.diagnosis", subject: { trace_id: "tr_9c1e7d40" } }}
      label="Generated diagnosis"
    >
      <p>Same version, same input shape.</p>
    </GeneratedText>
  );
}

describe("GeneratedText", () => {
  it("shows only the page's own text while AI summaries are off", async () => {
    renderPage(Diagnosis);
    expect(await screen.findByText("Same version, same input shape.")).toBeInTheDocument();
    // Give the feature check a moment; the button never appears.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByRole("button", { name: /Rewrite with AI/ })).not.toBeInTheDocument();
  });

  it("asks for a labelled, regenerable rewrite on demand", async () => {
    const calls = assistantCalls();
    server.use(
      ...assistantHandlers(calls, {
        events: [
          { event: "answer.started", model: "ollama:qwen3:8b" },
          { event: "answer.tool_started", id: "gather_0", name: "compare_trace" },
          { event: "answer.tool_completed", id: "gather_0", name: "compare_trace", status: "done" },
          { event: "answer.content", delta: "web_search now times out twice." },
          { event: "answer.sources", sources: [] },
          { event: "answer.completed", content: "web_search now times out twice.", model: "ollama:qwen3:8b" },
        ],
      }),
    );
    const user = userEvent.setup();
    renderPage(Diagnosis);
    await user.click(await screen.findByRole("button", { name: /Rewrite with AI/ }));

    const generated = await screen.findByRole("region", { name: "Generated diagnosis" });
    expect(await within(generated).findByText("web_search now times out twice.")).toBeInTheDocument();
    expect(within(generated).getByText("by ollama:qwen3:8b")).toBeInTheDocument();
    expect(screen.getByText("Same version, same input shape.")).toBeInTheDocument();
    expect(calls.explanations).toEqual([
      { kind: "trace.diagnosis", subject: { trace_id: "tr_9c1e7d40" }, material: null, regenerate: false },
    ]);

    await user.click(within(generated).getByRole("button", { name: "Regenerate" }));
    await within(generated).findByText("web_search now times out twice.");
    expect(calls.explanations).toHaveLength(2);
    expect(calls.explanations[1]).toMatchObject({ regenerate: true });
  });

  it("says why when the feature was switched off meanwhile", async () => {
    server.use(
      http.post(`${API}/instances/:instance/assistant/explanations`, () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "This AI feature is off",
            status: 409,
            code: "ai_feature_off",
            detail: "AI summaries is turned off.",
          },
          { status: 409, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
      ...assistantHandlers(),
    );
    const user = userEvent.setup();
    renderPage(Diagnosis);
    await user.click(await screen.findByRole("button", { name: /Rewrite with AI/ }));
    expect(await screen.findByText("AI summaries is turned off.")).toBeInTheDocument();
  });
});
