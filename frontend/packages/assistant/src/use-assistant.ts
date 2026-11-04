// Whether an AI feature may show at all: the backend module is enabled, the org configured and switched it on,
// and the signed-in person holds assistant:use. When it isn't, callers render nothing AI-related.
import { assistantGetStatusOptions } from "@agnostic/api";
import { STALE_TIME, useCan, useFeatures } from "@agnostic/core";
import { skipToken, useQuery } from "@tanstack/react-query";

export type AssistantFeature = "assistant" | "summaries" | "suggestions";

const FEATURE_KEY: Record<AssistantFeature, string> = {
  assistant: "assistant",
  summaries: "assistant.summaries",
  suggestions: "assistant.suggestions",
};

export function useAssistant(feature: AssistantFeature = "assistant") {
  const features = useFeatures();
  const can = useCan("assistant:use");
  const available = features.data?.[FEATURE_KEY[feature]] === true && can.allowed === true;
  const options = assistantGetStatusOptions();
  const status = useQuery({
    ...options,
    queryFn: available ? (options.queryFn ?? skipToken) : skipToken,
    staleTime: STALE_TIME.list,
  });
  return { available, status: status.data };
}
