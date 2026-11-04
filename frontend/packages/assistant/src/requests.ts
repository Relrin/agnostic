// Asking a question and requesting an explanation: both are queued on the server; the answer is followed with
// useAnswer. An explanation of the same thing is reused (no tokens) unless regenerated.
import { assistantAskQuestion, assistantExplain, describeError, type AcceptedOut } from "@agnostic/api";
import { useCallback, useState } from "react";

import { useAnswer } from "./answer";

export type AskInput = {
  question: string;
  conversationId?: string | undefined;
  /** What the person is looking at: "trace:<id>", "page:home", … */
  context?: string | undefined;
  files?: readonly File[] | undefined;
};

export async function askQuestion(instance: string, input: AskInput): Promise<AcceptedOut> {
  const response = await assistantAskQuestion({
    path: { instance },
    body: {
      question: input.question,
      ...(input.conversationId ? { conversation_id: input.conversationId } : {}),
      ...(input.context ? { context: input.context } : {}),
      ...(input.files?.length ? { files: [...input.files] } : {}),
    },
    throwOnError: true,
  });
  return response.data;
}

export type ExplanationRequest = {
  kind: string;
  subject: Record<string, string | number>;
  /** What the page shows that isn't stored yet (an unsaved draft, a preview). */
  material?: unknown;
};

/** One explanation next to a page's own text: nothing is requested until `start()`. */
export function useExplanation(instance: string, request: ExplanationRequest) {
  const [messageId, setMessageId] = useState<string>();
  const [error, setError] = useState<string>();
  const [pending, setPending] = useState(false);
  const answer = useAnswer(instance, messageId);
  const { kind, subject, material } = request;

  const start = useCallback(
    async (regenerate = false) => {
      setPending(true);
      setError(undefined);
      try {
        const accepted = await assistantExplain({
          path: { instance },
          body: { kind, subject, material: material ?? null, regenerate },
          throwOnError: true,
        });
        setMessageId(accepted.data.message_id);
      } catch (failure) {
        setError(describeError(failure).reason);
      } finally {
        setPending(false);
      }
    },
    [instance, kind, subject, material],
  );

  return { start, state: answer.state, error, pending, requested: messageId !== undefined };
}
