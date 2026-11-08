// The chat's context meter: the latest run of the session (live while it streams, otherwise the newest stored one)
// measured against the model's context window.
import { ContextMeter } from "@agnostic/ui";
import { useMemo } from "react";

import { contextShares, contextWindow, declaredWindow, inputTokens, usedTokens } from "./context";
import { fromStoredRun, storedMessages, type StoredRun } from "./history";
import { isSettled } from "./reducer";
import type { RunStream } from "./run-stream";
import { useRunStream } from "./store";

export function ChatContextMeter({
  stream,
  stored,
  model,
  metadata,
}: {
  /** The newest live run of the session, if any. */
  stream?: RunStream | undefined;
  /** The session's newest stored run. Once the live run is stored, its messages give the split by source. */
  stored?: StoredRun | undefined;
  /** The component's model id, for the window when the run does not name one. */
  model?: string | undefined;
  /** The component's metadata: `context_window` overrides the known window of its model. */
  metadata?: Record<string, unknown> | undefined;
}) {
  const live = useRunStream(stream);
  const storedUsage = useMemo(() => (stored ? fromStoredRun(stored).context : undefined), [stored]);
  const liveIsNewer =
    live?.context !== undefined &&
    (!isSettled(live) || (stored !== undefined && live.runId !== stored.run_id));
  const usage = liveIsNewer ? live.context : (storedUsage ?? live?.context);
  const messages = !liveIsNewer && storedUsage !== undefined && stored ? storedMessages(stored) : undefined;
  const shares = useMemo(() => (usage ? contextShares(usage, messages) : []), [usage, messages]);
  if (!usage) return null;
  const modelId = usage.model ?? live?.model ?? model;
  const cached = usage.cacheReadTokens;
  return (
    <ContextMeter
      used={usedTokens(usage)}
      window={declaredWindow(metadata) ?? contextWindow(modelId)}
      shares={shares}
      model={modelId}
      cachedTokens={cached > 0 && cached <= inputTokens(usage) ? cached : 0}
      reasoningTokens={usage.reasoningTokens}
      estimated={messages !== undefined}
      updating={live !== undefined && !isSettled(live)}
    />
  );
}
